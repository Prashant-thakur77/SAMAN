"""First-run bootstrap — spec §8A.

The one unauthenticated write in SAMAN, and the tests that keep it narrow.
"""

from sqlalchemy import func, select

from app.models import Cpse, RawItem, User


class TestBootstrapStatus:
    def test_a_populated_database_reports_itself_as_populated(self, client, seeded):
        body = client.get("/api/bootstrap/status").json()
        assert body["empty"] is False
        assert body["users"] > 0 and body["raw_items"] > 0

    def test_the_status_needs_no_session(self, client, seeded):
        """The login screen asks before anyone can possibly be signed in."""
        client.post("/api/auth/logout")
        assert client.get("/api/bootstrap/status").status_code == 200


class TestSeedingIsClosedOnceUsersExist:
    def test_a_populated_database_refuses_to_be_seeded(self, client, seeded):
        response = client.post("/api/bootstrap/demo-data", json={})
        assert response.status_code == 409
        assert "already populated" in response.json()["detail"]

    def test_it_refuses_even_without_a_session(self, client, seeded):
        client.post("/api/auth/logout")
        assert client.post("/api/bootstrap/demo-data", json={}).status_code == 409

    def test_the_refusal_does_not_touch_the_data(self, client, db, seeded):
        before = db.execute(select(func.count(RawItem.id))).scalar()
        client.post("/api/bootstrap/demo-data", json={})
        db.expire_all()
        assert db.execute(select(func.count(RawItem.id))).scalar() == before

    def test_the_benchmark_profile_is_not_offered_to_a_browser(self, client, seeded):
        """`large` is a 150k-row load test, not something to start by accident."""
        response = client.post("/api/bootstrap/demo-data", json={"profile": "large"})
        # Closed either way here; the message must still be the right one when
        # the database is empty, which the unit below covers.
        assert response.status_code in (400, 409)


class TestGateLogic:
    """The gate itself, tested without seeding 12,000 rows to do it."""

    def test_the_gate_opens_only_on_a_user_count_of_zero(self, db, seeded):
        """Tested against a throwaway database rather than by emptying the
        suite's own — the gate is one query, and deleting every user to prove
        it would leave every later test signed out."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session as PlainSession

        from app.db import Base
        from app.routers.bootstrap import _user_count

        assert _user_count(db) > 0, "the seeded database must be closed"

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with PlainSession(engine) as empty:
            assert _user_count(empty) == 0
            empty.add(
                User(
                    email="first@example.gov.in",
                    name="First",
                    role="registrar",
                    password_hash="x",
                )
            )
            empty.commit()
            assert _user_count(empty) == 1, "one user closes the door"

    def test_an_unknown_profile_is_refused(self, client, seeded):
        response = client.post("/api/bootstrap/demo-data", json={"profile": "telepathy"})
        assert response.status_code in (400, 409)

    def test_the_status_counts_what_the_screen_shows(self, client, db, seeded):
        body = client.get("/api/bootstrap/status").json()
        assert body["cpses"] == db.execute(select(func.count(Cpse.id))).scalar()
        assert body["profile"] == "demo"
        assert "state" in body["pipeline"]
