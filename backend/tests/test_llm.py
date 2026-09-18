"""One model client, two paths. A remote OpenAI-compatible endpoint is a
working model that the health page calls remote; the guards on what the model
may say are the callers' and do not change with the path; sovereign mode
switches both paths off."""

import httpx
import pytest

from app import capabilities, llm
from app.config import Settings


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


@pytest.fixture
def remote(monkeypatch):
    """A remote endpoint that records what it was asked and answers as told."""
    seen: dict = {"reply": "A short sentence.", "calls": []}
    factory = lambda: Settings(  # noqa: E731
        saman_llm_url="https://api.example.test/openai/v1",
        saman_llm_model="llama-3.1-8b-instant",
        saman_llm_key="sk-test",
        saman_sovereign_mode=False,
    )
    monkeypatch.setattr(llm, "get_settings", factory)
    monkeypatch.setattr(capabilities, "get_settings", factory)

    def fake_get(url, headers=None, timeout=None):
        seen["calls"].append(("GET", url, headers))
        return _Response({"data": []})

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["calls"].append(("POST", url, headers, json))
        return _Response({"choices": [{"message": {"content": seen["reply"]}}]})

    monkeypatch.setattr(llm.httpx, "get", fake_get)
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    llm.forget()
    capabilities.detect.cache_clear()
    yield seen
    llm.forget()
    capabilities.detect.cache_clear()


class TestRemotePath:
    def test_it_is_a_working_model_the_health_page_calls_remote(self, remote):
        assert llm.provider() == "remote" and llm.available()
        report = capabilities.detect().as_dict()["llm"]
        assert report["mode"] == "remote" and report["degraded"] is False
        assert report["remote"] is True
        assert "llama-3.1-8b-instant" in report["engine"] and "api.example.test" in report["engine"]

    def test_the_probe_and_the_calls_carry_the_key_and_the_openai_shape(self, remote):
        assert llm.available()
        method, url, headers = remote["calls"][0]
        assert url.endswith("/v1/models") and headers["Authorization"] == "Bearer sk-test"
        assert llm.generate("say hi", temperature=0.3, max_tokens=12) == "A short sentence."
        method, url, headers, body = remote["calls"][-1]
        assert url.endswith("/v1/chat/completions")
        assert body["model"] == "llama-3.1-8b-instant" and body["stream"] is False
        assert body["messages"] == [{"role": "user", "content": "say hi"}]
        assert body["temperature"] == 0.3 and body["max_tokens"] == 12

    def test_chat_passes_the_system_prompt_through(self, remote):
        llm.chat([{"role": "system", "content": "be brief"}, {"role": "user", "content": "q"}])
        body = remote["calls"][-1][3]
        assert body["messages"][0] == {"role": "system", "content": "be brief"}

    def test_an_empty_choice_list_is_an_empty_answer_not_a_crash(self, remote, monkeypatch):
        monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _Response({"choices": []}))
        assert llm.generate("q") == ""


class TestPaths:
    def test_local_ollama_stays_the_default_path(self, monkeypatch):
        factory = lambda: Settings(ollama_url="http://localhost:11434", saman_sovereign_mode=False)  # noqa: E731
        monkeypatch.setattr(llm, "get_settings", factory)
        assert llm.provider() == "ollama"
        assert "on this machine" in llm.engine_label()

    def test_sovereign_mode_switches_both_off(self, monkeypatch):
        """Spec §6.13: the runtime switch wins over any model, local or remote."""
        from app.config import set_sovereign_mode

        factory = lambda: Settings(  # noqa: E731
            saman_llm_url="https://api.example.test/v1",
            saman_llm_key="k",
            saman_sovereign_mode=False,
        )
        monkeypatch.setattr(llm, "get_settings", factory)
        set_sovereign_mode(True)
        try:
            assert llm.provider() == "deterministic" and not llm.available()
        finally:
            set_sovereign_mode(None)
        assert llm.provider() == "remote"

    def test_nothing_configured_is_the_rule_based_path(self, monkeypatch):
        monkeypatch.setattr(llm, "get_settings", lambda: Settings(ollama_url=None))
        assert llm.provider() == "deterministic"
        assert llm.engine_label() == "rule-based adjudicator"
