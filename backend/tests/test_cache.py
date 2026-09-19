"""The dashboard memo: computed once per version of the estate, never served
stale, and cleared by any change that could move a figure."""

from datetime import date

from app import audit, cache
from app.models import Decision


class TestMemo:
    def test_the_same_version_computes_once(self, db, seeded):
        calls = []

        def compute():
            calls.append(1)
            return {"n": len(calls)}

        first = cache.memo(db, ("t", 1), compute)
        second = cache.memo(db, ("t", 1), compute)
        assert first is second and calls == [1]

    def test_keys_are_independent(self, db, seeded):
        assert cache.memo(db, ("a",), lambda: 1) == 1
        assert cache.memo(db, ("b",), lambda: 2) == 2

    def test_an_audited_action_moves_the_version(self, db, seeded):
        before = cache.version(db)
        audit.record(db, action="test.ping", entity="test", payload={}, user="tests")
        assert cache.version(db) != before

    def test_a_sign_in_leaves_the_version_alone(self, db, seeded):
        """A login is on the ledger for the record and changes no figure;
        recomputing every dashboard after it cost the person who signed in
        twenty seconds of Loading on the free host."""
        before = cache.version(db)
        audit.record(db, action="auth.login", entity="user", payload={}, user="tests")
        audit.record(db, action="scan.wrong_item", entity="scan", payload={}, user="tests")
        assert cache.version(db) == before

    def test_a_row_changed_behind_the_ledger_moves_the_version_too(self, db, pipeline_run):
        before = cache.version(db)
        # Flushed, never committed: the row is visible to this session's
        # version query and gone again before the next test.
        db.add(Decision(task_id=1, user_id=1, action="approve", note="raw"))
        db.flush()
        try:
            assert cache.version(db) != before
        finally:
            db.rollback()

    def test_the_day_is_part_of_the_version(self, db, seeded):
        assert cache.version(db)[0] == date.today().isoformat()

    def test_the_executive_dashboard_is_served_from_the_memo(self, as_registrar, pipeline_run):
        first = as_registrar.get("/api/dashboard/executive").json()
        second = as_registrar.get("/api/dashboard/executive").json()
        assert first == second

    def test_warming_runs_every_job_and_survives_a_failure(self):
        ran = []

        def bad():
            raise RuntimeError("no")

        thread = cache.warm([("bad", bad), ("good", lambda: ran.append(1))])
        thread.join(timeout=5)
        assert ran == [1]
