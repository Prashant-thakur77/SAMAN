"""The grounded local-model answerer: retrieval is local and relevant, the model
is only ever given passages, and its answer is checked back against them."""

import httpx
import pytest

from app import assistant, knowledge, llm
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
    llm.forget()
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _FakeResponse({"models": [{"name": "qwen2.5:3b"}]})
    )
    state = {"reply": "", "prompt": None}

    def fake_post(url, json=None, timeout=None):
        state["prompt"] = json
        return _FakeResponse({"message": {"content": state["reply"]}})

    monkeypatch.setattr(httpx, "post", fake_post)
    # Answers are memoised per question and model; each test starts clean.
    knowledge.forget_answers()
    yield state
    config.get_settings.cache_clear()
    llm.forget()
    knowledge.forget_answers()


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
        model_up["reply"] = (
            "Sub-blocking bought very little recall for a tenth more run time and was reverted."
        )
        reply = assistant.answer(
            db, "what did the sub-blocking experiment on oversized buckets find", REGISTRAR
        )
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
        llm.forget()
        try:
            reply = assistant.answer(
                db, "what did the sub-blocking experiment on oversized buckets find", REGISTRAR
            )
            assert reply.mode != "llm"
        finally:
            config.get_settings.cache_clear()


class TestTheFigureGuardReadsSentences:
    def test_a_trailing_full_stop_is_not_a_different_number(self):
        # "F1" is a name, but the guard counts its digit too, on both sides alike.
        assert knowledge._numbers("the score was 0.9775.") == {"0.9775"}
        assert knowledge._numbers("1,823 pairs, 0.11 recall.") == {"1823", "0.11"}

    def test_an_invented_figure_is_still_caught(self):
        assert knowledge._numbers("recall 0.96") - knowledge._numbers("recall 0.960") == {"0.96"}


@pytest.fixture
def model_streams(monkeypatch, model_up):
    """The same reachable model, answering through the streaming call with
    whatever pieces the test sets."""
    state = {"pieces": []}
    monkeypatch.setattr(llm, "stream_chat", lambda *a, **k: iter(state["pieces"]))
    return state


class TestStreaming:
    """Sentence-gated streaming: nothing the guard would refuse is ever shown."""

    def _events(self, question="how does the check digit work"):
        return list(knowledge.stream(question))

    def test_sentences_are_released_as_they_complete(self, model_streams):
        model_streams["pieces"] = ["The Damm digit catches ", "every transposition. ", "It is one digit."]
        events = self._events()
        kinds = [e["type"] for e in events]
        assert kinds[0] == "sources" and kinds[-1] == "done"
        deltas = [e["text"] for e in events if e["type"] == "delta"]
        assert deltas == ["The Damm digit catches every transposition.", " It is one digit."]
        assert events[-1]["accepted"] is True
        assert events[-1]["text"] == "The Damm digit catches every transposition. It is one digit."

    def test_an_invented_figure_stops_the_stream_before_that_sentence(self, model_streams):
        model_streams["pieces"] = ["The check digit is Damm. ", "It handles 4,000,000 rows a second."]
        events = self._events()
        deltas = [e["text"] for e in events if e["type"] == "delta"]
        assert deltas == ["The check digit is Damm."]
        done = events[-1]
        assert done["accepted"] is False and done["reason"] == "invented_figure"
        assert "4000000" in done["note"]

    def test_a_figure_split_across_pieces_is_still_checked_whole(self, model_streams):
        model_streams["pieces"] = ["Recall was 0.9", "9 on the split."]
        events = self._events()
        assert events[-1]["accepted"] is False
        assert [e for e in events if e["type"] == "delta"] == []

    def test_a_delta_ending_at_the_dot_inside_a_figure_is_not_a_sentence(self, model_streams):
        # 0.9949 is in the question, so it is a known figure. "0." arriving
        # alone must not be read as a sentence that says "0".
        model_streams["pieces"] = ["Blocking recall is 0.", "9949 on the split.", " That is all."]
        events = list(knowledge.stream("is blocking recall 0.9949 on the held-out split"))
        assert events[-1]["accepted"] is True, events[-1]
        deltas = [e["text"] for e in events if e["type"] == "delta"]
        assert deltas == ["Blocking recall is 0.9949 on the split.", " That is all."]

    def test_the_dont_know_phrase_ends_it_quietly(self, model_streams):
        model_streams["pieces"] = [knowledge.DONT_KNOW]
        events = self._events()
        assert events[-1]["accepted"] is False and events[-1]["reason"] == "declined"

    def test_an_accepted_stream_is_memoised_like_an_answer(self, model_streams):
        model_streams["pieces"] = ["The Damm digit catches every adjacent transposition."]
        self._events()
        hit = knowledge.cached("how does the check digit work")
        assert hit is not None and hit.text.startswith("The Damm")
        # The memo answers the next stream at once, without the model.
        model_streams["pieces"] = ["should not be used"]
        events = self._events()
        assert events[-1]["text"].startswith("The Damm")

    def test_a_dead_model_reports_unavailable(self, model_streams, monkeypatch):
        def boom(*a, **k):
            raise httpx.ConnectError("refused")
            yield  # pragma: no cover

        monkeypatch.setattr(llm, "stream_chat", boom)
        events = self._events()
        assert events[-1]["reason"] == "unavailable"


class TestStreamRoute:
    def test_query_offers_a_stream_only_when_the_model_would_answer(
        self, as_viewer, pipeline_run, model_streams
    ):
        # A navigation never streams; an open question about the system does.
        nav = as_viewer.post(
            "/api/assistant/query", json={"question": "open the workbench", "stream": True}
        ).json()
        assert nav["kind"] == "navigate"
        model_streams["pieces"] = ["Sub-blocking was reverted."]
        open_q = as_viewer.post(
            "/api/assistant/query",
            json={
                "question": "what did the sub-blocking experiment on oversized buckets find",
                "stream": True,
            },
        ).json()
        assert open_q["kind"] == "stream"

    def test_the_stream_ends_with_a_fallback_when_the_model_is_refused(
        self, as_viewer, pipeline_run, model_streams
    ):
        model_streams["pieces"] = ["SAMAN handles 4,000,000 rows a second."]
        with as_viewer.stream(
            "GET",
            "/api/assistant/stream",
            params={"q": "what did the sub-blocking experiment on oversized buckets find"},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())
        import json

        events = [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]
        done = events[-1]
        assert done["type"] == "done" and done["accepted"] is False
        assert done["fallback"]["kind"] in ("answer", "navigate", "copilot", "unknown")
        assert done["fallback"]["answer"]


class TestWarmAnswers:
    def test_the_demo_questions_are_answered_into_the_memo_at_start(self, model_up):
        from app.assistant import WARM_QUESTIONS
        from app.main import warm_answers

        model_up["reply"] = "The veto layer refuses on an identity attribute that differs."
        assert knowledge.cached(WARM_QUESTIONS[0]) is None
        assert warm_answers() == len(WARM_QUESTIONS)
        assert all(knowledge.cached(q) is not None for q in WARM_QUESTIONS)

    def test_nothing_is_warmed_without_a_model(self, monkeypatch):
        from app.main import warm_answers

        monkeypatch.setattr(knowledge, "available", lambda: False)
        assert warm_answers() == 0


class TestAnswerLog:
    """Every answer and every refusal, one line each, for the harness to replay."""

    def test_accepted_and_refused_answers_are_logged_with_their_reasons(
        self, model_up, monkeypatch, tmp_path
    ):
        import json

        from app import config

        monkeypatch.setattr(config.get_settings(), "saman_answer_log", str(tmp_path / "log.jsonl"))
        model_up["reply"] = "The Damm digit catches every adjacent transposition."
        knowledge.answer("how does the check digit work")
        model_up["reply"] = "It handles 4,000,000 rows a second."
        knowledge.answer("how fast is it")
        rows = [json.loads(line) for line in (tmp_path / "log.jsonl").read_text().splitlines()]
        assert [r["outcome"] for r in rows] == ["accepted", "invented_figure"]
        assert rows[0]["sources"] and rows[0]["answer_chars"] > 0
        assert "4000000" in rows[1]["note"]
        assert rows[0]["model"] and rows[0]["provider"] == "ollama"

    def test_the_harness_can_replay_the_log(self, model_up, monkeypatch, tmp_path):
        from app import config
        from app.cli import _cases_from_log

        monkeypatch.setattr(config.get_settings(), "saman_answer_log", str(tmp_path / "log.jsonl"))
        model_up["reply"] = "The veto refuses on identity."
        for q in ("first question", "second question", "first question"):
            knowledge.forget_answers()
            knowledge.answer(q)
        cases = _cases_from_log(10)
        assert [c["question"] for c in cases] == ["first question", "second question"]
        assert all(c["expect"] == [] for c in cases)

    def test_an_empty_setting_turns_the_log_off(self, monkeypatch):
        from app import config

        monkeypatch.setattr(config.get_settings(), "saman_answer_log", "")
        assert knowledge.answer_log_path() is None


class TestStreamIsRoutedLikeQuery:
    def test_a_visitors_data_question_never_reaches_the_model(self, client, pipeline_run, model_streams):
        import json

        model_streams["pieces"] = ["should not be used"]
        with client.stream(
            "GET", "/api/assistant/stream", params={"q": "how many CNMCs have been issued"}
        ) as response:
            body = "".join(response.iter_text())
        events = [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]
        assert len(events) == 1 and events[0]["reason"] == "routed"
        assert events[0]["fallback"]["matched"] == {"topic": "sign_in"}
        assert "should not be used" not in body
