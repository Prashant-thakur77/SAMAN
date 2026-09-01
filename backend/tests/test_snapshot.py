"""Demo snapshots and the Tier-1 engine pin — spec §8A, §0.4."""

import sqlite3

import pytest

from app import capabilities, snapshot


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Two throwaway databases standing in for the app and the mock ERP.

    The real ones are not used here: restoring the suite's own database
    mid-run would wipe the seeded state every later test depends on.
    """
    app_db, erp_db = tmp_path / "app.db", tmp_path / "erp.db"
    for path in (app_db, erp_db):
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE thing (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO thing (name) VALUES ('original')")

    monkeypatch.setattr(snapshot, "snapshot_dir", lambda: tmp_path / "snapshot")
    monkeypatch.setattr(snapshot, "_targets", lambda: [("app", app_db), ("erp", erp_db)])
    monkeypatch.setattr(snapshot, "_reset_caches", lambda: None)
    return app_db, erp_db


def _names(path):
    with sqlite3.connect(path) as conn:
        return [row[0] for row in conn.execute("SELECT name FROM thing ORDER BY id")]


class TestSnapshot:
    def test_capturing_writes_every_database(self, sandbox, tmp_path):
        result = snapshot.capture()
        assert sorted(result.files) == ["app.db", "erp.db"]
        assert snapshot.exists()

    def test_restoring_undoes_whatever_the_demo_did(self, sandbox):
        app_db, erp_db = sandbox
        snapshot.capture()
        for path in (app_db, erp_db):
            with sqlite3.connect(path) as conn:
                conn.execute("INSERT INTO thing (name) VALUES ('mistake made on stage')")
        assert "mistake made on stage" in _names(app_db)

        snapshot.restore()
        assert _names(app_db) == ["original"]
        assert _names(erp_db) == ["original"], "both systems, or neither"

    def test_a_restore_is_fast_enough_to_do_mid_demo(self, sandbox):
        """§8A gives this five seconds; it is the difference between a pause and
        an apology."""
        snapshot.capture()
        assert snapshot.restore().seconds < 5.0

    def test_the_write_ahead_log_is_not_left_behind(self, sandbox):
        """A stale -wal would replay writes the snapshot predates."""
        app_db, _ = sandbox
        snapshot.capture()
        wal = app_db.with_name(app_db.name + "-wal")
        wal.write_bytes(b"stale")
        snapshot.restore()
        assert not wal.exists()

    def test_restoring_without_a_snapshot_says_so(self, sandbox, tmp_path):
        with pytest.raises(FileNotFoundError, match="make demo-snapshot"):
            snapshot.restore()

    def test_capturing_twice_replaces_the_snapshot(self, sandbox):
        app_db, _ = sandbox
        snapshot.capture()
        with sqlite3.connect(app_db) as conn:
            conn.execute("UPDATE thing SET name = 'second state'")
        snapshot.capture()
        snapshot.restore()
        assert _names(app_db) == ["second state"]

    def test_a_missing_database_is_skipped_not_fatal(self, sandbox):
        """A fresh checkout has no mock ERP until the seed runs."""
        _, erp_db = sandbox
        erp_db.unlink()
        assert snapshot.capture().files == ["app.db"]


class TestTierOnePin:
    """§0.4: which engine runs must be a decision, not an accident of install."""

    def test_auto_prefers_splink_when_it_is_installed(self, monkeypatch):
        monkeypatch.setenv("SAMAN_TIER1_ENGINE", "auto")
        detected = capabilities.refresh()
        expected = "splink" if capabilities._importable("splink") else "rapidfuzz"
        assert detected.linkage_mode == expected

    def test_pinning_rapidfuzz_overrides_an_installed_splink(self, monkeypatch):
        monkeypatch.setenv("SAMAN_TIER1_ENGINE", "rapidfuzz")
        detected = capabilities.refresh()
        assert detected.linkage_mode == "rapidfuzz"
        assert any("pinned to rapidfuzz" in note for note in detected.degraded)

    def test_a_deliberate_pin_is_not_reported_as_degradation(self, monkeypatch):
        """An indicator that cries wolf about a chosen configuration is one
        people learn to ignore."""
        monkeypatch.setenv("SAMAN_TIER1_ENGINE", "rapidfuzz")
        linkage = capabilities.refresh().as_dict()["linkage"]
        assert linkage["degraded"] is False
        assert linkage["selected_by"] == "operator"

    def test_a_missing_splink_is_reported_as_degradation(self, monkeypatch):
        monkeypatch.setenv("SAMAN_TIER1_ENGINE", "auto")
        monkeypatch.setattr(capabilities, "_importable", lambda module: False)
        linkage = capabilities.refresh().as_dict()["linkage"]
        assert linkage["degraded"] is True
        assert linkage["selected_by"] == "availability"

    def test_pinning_a_missing_splink_degrades_and_says_why(self, monkeypatch):
        monkeypatch.setenv("SAMAN_TIER1_ENGINE", "splink")
        monkeypatch.setattr(capabilities, "_importable", lambda module: False)
        detected = capabilities.refresh()
        assert detected.linkage_mode == "rapidfuzz"
        assert any("pinned to splink" in note for note in detected.degraded)

    def test_the_pin_reaches_the_health_endpoint(self, client, monkeypatch):
        monkeypatch.setenv("SAMAN_TIER1_ENGINE", "rapidfuzz")
        capabilities.refresh()
        body = client.get("/api/health").json()
        assert body["capabilities"]["linkage"]["mode"] == "rapidfuzz"


@pytest.fixture(autouse=True)
def _restore_capabilities():
    """Every test here mutates global engine detection; put it back."""
    yield
    capabilities.refresh()
