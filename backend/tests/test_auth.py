"""Session auth, role gates and separation of duties — spec §0.9."""

import pytest
from fastapi import HTTPException

from app import auth
from app.auth import (
    enforce_separation_of_duties,
    hash_password,
    require_roles,
    verify_password,
)
from app.models import GoldenRecord, User


class TestPasswordHashing:
    def test_round_trip(self):
        stored = hash_password("demo")
        assert verify_password("demo", stored)
        assert not verify_password("Demo", stored)

    def test_hash_is_salted(self):
        assert hash_password("demo") != hash_password("demo")

    def test_plaintext_is_never_stored(self):
        assert "demo" not in hash_password("demo").split("$")[-1]

    @pytest.mark.parametrize("stored", ["", "garbage", "md5$1$aa$bb", "a$b$c"])
    def test_malformed_hash_fails_closed(self, stored):
        assert verify_password("demo", stored) is False


class TestLogin:
    def test_seeded_user_can_sign_in(self, client, seeded):
        r = client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
        assert r.status_code == 200
        assert r.json()["role"] == "steward"

    def test_wrong_password_is_rejected(self, client, seeded):
        r = client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "nope"})
        assert r.status_code == 401

    def test_unknown_user_is_rejected(self, client, seeded):
        r = client.post("/api/auth/login", json={"email": "nobody@nowhere", "password": "demo"})
        assert r.status_code == 401

    def test_me_requires_a_session(self, client, seeded):
        client.cookies.clear()
        assert client.get("/api/auth/me").status_code == 401

    def test_session_probe_returns_null_when_signed_out(self, client, seeded):
        client.cookies.clear()
        r = client.get("/api/auth/session")
        assert r.status_code == 200 and r.json() is None

    def test_logout_clears_the_session(self, as_steward):
        assert as_steward.get("/api/auth/me").status_code == 200
        as_steward.post("/api/auth/logout")
        assert as_steward.get("/api/auth/me").status_code == 401

    def test_forged_cookie_is_rejected(self, client, seeded):
        client.cookies.set("saman_session", "not-a-valid-signed-token")
        assert client.get("/api/auth/me").status_code == 401

    def test_demo_user_list_is_public_and_carries_no_hashes(self, client, seeded):
        r = client.get("/api/auth/demo-users")
        assert r.status_code == 200
        users = r.json()
        assert len(users) >= 6
        assert {u["role"] for u in users} >= {"registrar", "steward", "approver", "auditor"}
        assert all("password" not in str(k).lower() for u in users for k in u)


class TestRoleGates:
    def test_unknown_role_is_a_programming_error(self):
        with pytest.raises(ValueError):
            require_roles("wizard")

    def test_viewer_cannot_ingest(self, client, seeded):
        client.post("/api/auth/login", json={"email": "viewer@min.gov.in", "password": "demo"})
        r = client.post(
            "/api/ingest",
            data={"cpse_code": "CPCL"},
            files={"file": ("x.csv", b"legacy_code,description\nA,B\n", "text/csv")},
        )
        assert r.status_code == 403
        assert "viewer" in r.json()["detail"]

    def test_steward_can_ingest(self, as_steward):
        r = as_steward.post(
            "/api/ingest",
            data={"cpse_code": "CPCL", "dry_run": "true"},
            files={"file": ("x.csv", b"legacy_code,description\nZZ1,BEARING 6205\n", "text/csv")},
        )
        assert r.status_code == 200

    def test_anonymous_request_is_401_not_403(self, client, seeded):
        client.cookies.clear()
        r = client.post("/api/pipeline/run")
        assert r.status_code == 401


class TestSeparationOfDuties:
    """§0.9: the proposer of a golden record may not approve it."""

    def test_self_approval_is_refused_with_409(self):
        user = User(id=7, email="a@b", name="A", role="approver", password_hash="x")
        golden = GoldenRecord(id=1, cluster_id=1, std_description="X", proposed_by=7)
        with pytest.raises(HTTPException) as exc:
            enforce_separation_of_duties(golden, user)
        assert exc.value.status_code == 409
        assert "cannot" in exc.value.detail.lower()

    def test_a_different_approver_is_allowed(self):
        user = User(id=8, email="b@b", name="B", role="approver", password_hash="x")
        golden = GoldenRecord(id=1, cluster_id=1, std_description="X", proposed_by=7)
        enforce_separation_of_duties(golden, user)  # must not raise

    def test_unattributed_proposal_does_not_block_approval(self):
        """Pipeline-proposed records have no human proposer to conflict with."""
        user = User(id=8, email="b@b", name="B", role="approver", password_hash="x")
        golden = GoldenRecord(id=1, cluster_id=1, std_description="X", proposed_by=None)
        enforce_separation_of_duties(golden, user)


class TestSessionExpiry:
    """A signature without a timestamp is a credential that never expires."""

    def test_a_session_token_expires_on_its_own(self, client, seeded, monkeypatch):
        client.post(
            "/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"}
        )
        assert client.get("/api/auth/me").status_code == 200

        # Move the clock past the signature's own lifetime. The cookie is still
        # in the jar; the point is that the server stops accepting it.
        import itsdangerous.timed

        real = itsdangerous.timed.time.time
        monkeypatch.setattr(
            itsdangerous.timed.time, "time", lambda: real() + auth.SESSION_MAX_AGE + 60
        )
        assert client.get("/api/auth/me").status_code == 401

    def test_a_tampered_token_is_rejected(self, client, seeded):
        client.post(
            "/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"}
        )
        token = client.cookies.get(auth.SESSION_COOKIE)
        client.cookies.set(auth.SESSION_COOKIE, token[:-2] + "xy")
        assert client.get("/api/auth/me").status_code == 401

    def test_the_cookie_is_http_only(self, client, seeded):
        """A session readable from JavaScript is one an injected script steals."""
        response = client.post(
            "/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"}
        )
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie


class TestLoginThrottle:
    """An unlimited-guess password endpoint is a brute-force invitation."""

    def test_repeated_failures_lock_the_account_out(self, client, seeded):
        for _ in range(auth.LOGIN_ATTEMPTS):
            response = client.post(
                "/api/auth/login",
                json={"email": "steward@cpcl.in", "password": "wrong"},
            )
            assert response.status_code == 401

        blocked = client.post(
            "/api/auth/login", json={"email": "steward@cpcl.in", "password": "wrong"}
        )
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers

    def test_the_lockout_holds_even_with_the_right_password(self, client, seeded):
        """Otherwise a guesser learns when they have found it."""
        for _ in range(auth.LOGIN_ATTEMPTS):
            client.post(
                "/api/auth/login",
                json={"email": "steward@cpcl.in", "password": "wrong"},
            )
        assert (
            client.post(
                "/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"}
            ).status_code
            == 429
        )

    def test_a_success_clears_the_count(self, client, seeded):
        """The throttle stops guessing; it does not punish a typo."""
        for _ in range(auth.LOGIN_ATTEMPTS - 1):
            client.post(
                "/api/auth/login",
                json={"email": "steward@cpcl.in", "password": "wrong"},
            )
        assert (
            client.post(
                "/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"}
            ).status_code
            == 200
        )
        for _ in range(auth.LOGIN_ATTEMPTS - 1):
            assert (
                client.post(
                    "/api/auth/login",
                    json={"email": "steward@cpcl.in", "password": "wrong"},
                ).status_code
                == 401
            )

    def test_one_account_being_attacked_does_not_lock_out_another(self, client, seeded):
        for _ in range(auth.LOGIN_ATTEMPTS + 2):
            client.post(
                "/api/auth/login",
                json={"email": "steward@cpcl.in", "password": "wrong"},
            )
        assert (
            client.post(
                "/api/auth/login",
                json={"email": "registrar@min.gov.in", "password": "demo"},
            ).status_code
            == 200
        )

    def test_the_window_expires(self, client, seeded, monkeypatch):
        for _ in range(auth.LOGIN_ATTEMPTS):
            client.post(
                "/api/auth/login",
                json={"email": "steward@cpcl.in", "password": "wrong"},
            )
        real = auth.time.time
        monkeypatch.setattr(
            auth.time, "time", lambda: real() + auth.LOGIN_WINDOW_SECONDS + 1
        )
        assert (
            client.post(
                "/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"}
            ).status_code
            == 200
        )
