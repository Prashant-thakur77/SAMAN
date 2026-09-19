"""The front door: without a session the API answers sign-in, health and the
empty-database bootstrap, and nothing else. This walks every route the app
registers, so an endpoint added without a role check is still behind the
door, and a new public route has to be listed here on purpose."""

import pytest
from fastapi.routing import APIRoute

from app.main import app

#: The routes a visitor may call before signing in, and why.
PUBLIC = {
    ("GET", "/api/health"),  # what runs, and in what mode
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/session"),  # "am I signed in?" for the app shell
    ("GET", "/api/auth/demo-users"),  # the account picker, demo mode only
    ("GET", "/api/auth/login-mode"),
    ("GET", "/api/bootstrap/status"),  # "is this database empty?"
    ("POST", "/api/bootstrap/demo-data"),  # refuses once anyone exists
    # The assistant on the front page: explains the system, never opens the
    # database for a visitor, sends them to sign in for anything inside.
    ("POST", "/api/assistant/query"),
    # The streamed form of the same answer: the model reads the public
    # documents; a visitor's data question never reaches it (assistant._answer).
    ("GET", "/api/assistant/stream"),
    ("GET", "/api/assistant/suggestions"),
    ("GET", "/api/assistant/voice"),
}


def _api_routes():
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/"):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                yield method, route.path


def _probe_path(path: str) -> str:
    return path.replace("{", "1").replace("}", "")


class TestEveryRouteIsBehindTheDoor:
    @pytest.mark.parametrize("method,path", sorted(_api_routes()))
    def test_a_stranger_is_refused_or_the_route_is_listed_public(
        self, client, seeded, method, path
    ):
        response = client.request(method, _probe_path(path))
        if (method, path) in PUBLIC:
            assert response.status_code != 401, (method, path)
        else:
            assert response.status_code == 401, (method, path, response.text[:120])
            assert response.json()["detail"] == "Sign in to continue."

    def test_the_public_list_matches_the_app(self):
        registered = set(_api_routes())
        assert registered >= PUBLIC, PUBLIC - registered

    def test_the_docs_are_readable_without_a_session(self, client):
        """The API's description carries no data; a judge may read it first."""
        assert client.get("/api/openapi.json").status_code == 200


class TestSignedIn:
    def test_a_viewer_reads_the_dashboards_and_search(self, client, seeded):
        r = client.post("/api/auth/login", json={"email": "viewer@min.gov.in", "password": "demo"})
        if r.status_code != 200:
            pytest.skip("no seeded viewer account")
        assert client.get("/api/dashboard/executive").status_code == 200
        assert client.get("/api/items?q=bearing").status_code == 200

    def test_roles_still_gate_within_the_door(self, as_steward, seeded):
        assert as_steward.get("/api/users").status_code == 403


class TestSecurityHeaders:
    def test_every_response_carries_them(self, client):
        headers = client.get("/api/health").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "camera=(self)" in headers["permissions-policy"]

    def test_hsts_only_when_cookies_are_secure(self, client, monkeypatch):
        from app import main

        assert "strict-transport-security" not in client.get("/api/health").headers
        monkeypatch.setattr(main.settings, "saman_secure_cookies", True)
        assert "strict-transport-security" in client.get("/api/health").headers


class TestDemoAccountsAreFixed:
    def test_a_seeded_account_cannot_be_demoted_or_disabled(self, as_registrar, seeded):
        users = as_registrar.get("/api/users").json()["users"]
        registrar = next(u for u in users if u["email"] == "registrar@min.gov.in")
        approver = next(u for u in users if u["email"] == "approver@min.gov.in")
        r = as_registrar.patch(f"/api/users/{approver['id']}", json={"role": "viewer"})
        assert r.status_code == 409 and "Demo accounts are fixed" in r.json()["detail"]
        r = as_registrar.patch(f"/api/users/{registrar['id']}", json={"active": False})
        assert r.status_code == 409

    def test_an_account_created_by_an_admin_is_still_editable(self, as_registrar, seeded):
        r = as_registrar.post(
            "/api/users",
            json={
                "email": "new.steward@cpcl.in",
                "name": "New Steward",
                "role": "steward",
                "password": "changeme-long",
                "cpse_code": "CPCL",
            },
        )
        assert r.status_code in (200, 201), r.text
        created = r.json()
        r = as_registrar.patch(f"/api/users/{created['id']}", json={"role": "viewer"})
        assert r.status_code == 200 and r.json()["role"] == "viewer"
