"""Session auth, role gates and separation of duties — spec §0.9."""

import pytest
from fastapi import HTTPException

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
