"""The grounded local-model answerer: retrieval is local and relevant, the model
is only ever given passages, and its answer is checked back against them."""

import httpx
import pytest

from app import assistant, knowledge
from app.visibility import Scope

REGISTRAR = Scope("registrar", None)


class TestRetrieval:
    def test_the_corpus_is_the_projects_own_documents(self):
        docs = knowledge.corpus()
        sources = {c.source for c in docs}
        assert {"README", "Known gaps", "Assistant"} <= sources
        assert len(docs) > 50

    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("how is the damm check digit computed", "damm"),
            ("what does restricted mode measure", "bloom"),
            ("why was zingg excluded", "zingg"),
        ],
    )
    def test_relevant_passages_come_first(self, question, expected):
        top = knowledge.retrieve(question, k=3)
        assert top, "nothing retrieved"
        assert any(expected in c.text.lower() for c, _ in top)


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


@pytest.fixture
def model_up(monkeypatch):
    """A reachable model that answers with whatever the test sets."""
    monkeypatch.setenv("OLLAMA_URL", "http://model.test")
    from app import config

    config.get_settings.cache_clear()
    knowledge._reachable.cache_clear()
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _FakeResponse({"models": [{"name": "qwen2.5:3b"}]})
    )
    state = {"reply": "", "prompt": None}

    def fake_post(url, json=None, timeout=None):
        state["prompt"] = json
        return _FakeResponse({"message": {"content": state["reply"]}})

    monkeypatch.setattr(httpx, "post", fake_post)
    yield state
    config.get_settings.cache_clear()
    knowledge._reachable.cache_clear()


class TestGrounding:
    def test_the_model_only_sees_passages(self, model_up):
        model_up["reply"] = "The Damm digit catches every adjacent transposition."
        result = knowledge.answer("how does the check digit work")
        assert result and not result.refused
        messages = model_up["prompt"]["messages"]
        assert messages[0]["role"] == "system"
        assert "Passages:" in messages[1]["content"]
        assert result.sources
        assert result.sources[0]["source"] in ("README", "Assistant", "Build spec", "Known gaps")

    def test_an_invented_figure_is_refused(self, model_up):
        model_up["reply"] = "SAMAN processes 4,000,000 rows a second across 93 CPSEs."
        result = knowledge.answer("how fast is it")
        assert result is None or result.refused

    def test_the_dont_know_phrase_yields_to_the_callers_words(self, model_up):
        model_up["reply"] = knowledge.DONT_KNOW
        assert knowledge.answer("what is the weather in chennai") is None

    def test_a_dead_model_is_a_note_not_a_crash(self, model_up, monkeypatch):
        def boom(*a, **k):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "post", boom)
        result = knowledge.answer("how does the check digit work")
        assert result is not None and result.refused
        assert "unavailable" in (result.note or "")


class TestAssistantIntegration:
    def test_open_questions_reach_the_model_when_it_is_up(self, db, pipeline_run, model_up):
        # A question no topic card covers and no Copilot template matches, so
        # only the documents can answer it.
        # Number-free on purpose: the figure check is the subject of another test.
        model_up["reply"] = "Sub-blocking bought very little recall for a tenth more run time and was reverted."
        reply = assistant.answer(db, "what did the sub-blocking experiment on oversized buckets find", REGISTRAR)
        assert reply.mode == "llm"
        assert reply.kind == "answer"
        assert reply.matched and "sources" in reply.matched

    def test_navigation_never_goes_to_the_model(self, db, pipeline_run, model_up):
        model_up["reply"] = "should not be used"
        reply = assistant.answer(db, "open the workbench", REGISTRAR)
        assert reply.kind == "navigate"
        assert model_up["prompt"] is None

    def test_data_questions_still_go_to_the_copilot(self, db, pipeline_run, model_up):
        model_up["reply"] = "should not be used"
        reply = assistant.answer(db, "how many CNMCs have been issued", REGISTRAR)
        assert reply.kind == "copilot"
        assert model_up["prompt"] is None

    def test_without_a_model_the_old_behaviour_holds(self, db, pipeline_run, monkeypatch):
        monkeypatch.delenv("OLLAMA_URL", raising=False)
        monkeypatch.setenv("SAMAN_OLLAMA_AUTODETECT", "false")
        from app import config

        config.get_settings.cache_clear()
        knowledge._reachable.cache_clear()
        try:
            reply = assistant.answer(
                db, "what did the sub-blocking experiment on oversized buckets find", REGISTRAR
            )
            assert reply.mode != "llm"
        finally:
            config.get_settings.cache_clear()
