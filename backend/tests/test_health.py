"""Health endpoint must always answer, whatever is installed (spec 0.4, 9)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["app"] == "SAMAN"
    assert body["offline"] is True


def test_health_reports_every_tier_mode():
    caps = client.get("/api/health").json()["capabilities"]
    assert caps["linkage"]["mode"] in {"splink", "rapidfuzz"}
    assert caps["embedding"]["mode"] in {"sentence-transformers", "tfidf"}
    assert caps["llm"]["mode"] in {"ollama", "deterministic"}
    for tier in ("linkage", "embedding", "llm"):
        assert isinstance(caps[tier]["degraded"], bool)
        assert caps[tier]["engine"]


def test_degradation_notice_matches_modes():
    """Every degraded tier must explain itself in the notices list."""
    caps = client.get("/api/health").json()["capabilities"]
    degraded_tiers = sum(1 for t in ("linkage", "embedding", "llm") if caps[t]["degraded"])
    assert len(caps["degraded"]) == degraded_tiers
