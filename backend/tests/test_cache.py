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


class TestStaleWhileRevalidate:
    """A slow host gets the last figures at once, marked stale, and the fresh
    ones as soon as they are computed; a fast host never sees stale ones."""

    @staticmethod
    def _value(n):
        return {"n": n, "provenance": {"audit_seq": n}}

    def _change(self, db):
        audit.record(db, action="test.estate", entity="test", payload={}, user="tests")

    def test_a_slow_recompute_serves_the_last_figures_marked_stale(self, db, seeded, monkeypatch):
        import time

        monkeypatch.setattr(cache, "_stale_wait", lambda: 0.05)
        key = ("swr", "slow")
        assert cache.memo(db, key, lambda: self._value(1)) == self._value(1)
        self._change(db)

        def slow(_session):
            time.sleep(0.5)
            return self._value(2)

        started = time.perf_counter()
        served = cache.memo(db, key, lambda: self._value(2), refresh=slow)
        assert time.perf_counter() - started < 0.4, "the reader must not wait for the recompute"
        assert served["n"] == 1 and served["provenance"]["stale"] is True
        cache.drain()
        fresh = cache.memo(db, key, lambda: self._value(3), refresh=slow)
        assert fresh == self._value(2), "the background recompute is what the next reader gets"

    def test_a_fast_recompute_is_served_fresh(self, db, seeded, monkeypatch):
        monkeypatch.setattr(cache, "_stale_wait", lambda: 5.0)
        key = ("swr", "fast")
        cache.memo(db, key, lambda: self._value(1))
        self._change(db)
        served = cache.memo(db, key, lambda: self._value(9), refresh=lambda _s: self._value(2))
        assert served == self._value(2)
        assert "stale" not in served["provenance"]

    def test_without_a_previous_value_the_first_reader_computes(self, db, seeded, monkeypatch):
        monkeypatch.setattr(cache, "_stale_wait", lambda: 0.0)
        key = ("swr", "first")
        served = cache.memo(db, key, lambda: self._value(7), refresh=lambda _s: self._value(8))
        assert served == self._value(7), "nothing stale to serve, so nothing is"

    def test_the_cached_value_is_not_mutated_by_marking_it_stale(self, db, seeded, monkeypatch):
        import time

        monkeypatch.setattr(cache, "_stale_wait", lambda: 0.0)
        key = ("swr", "immutable")
        cache.memo(db, key, lambda: self._value(1))
        self._change(db)
        cache.memo(db, key, lambda: self._value(2), refresh=lambda _s: (time.sleep(0.2), self._value(2))[1])
        cache.drain()
        with cache._guard:
            stored = cache._entries[key][1]
        assert "stale" not in stored["provenance"]
