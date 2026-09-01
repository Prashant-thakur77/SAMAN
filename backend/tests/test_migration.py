"""Two-way ERP migration — spec §2C.

The §2C acceptance criteria, each as a test: migrating a batch updates mock-ERP
rows, an item with an open purchase order is auto-held, and a rollback restores
the mock ERP to a byte-identical prior state.
"""

import json

import pytest
from sqlalchemy import func, select

from app import erp, migration
from app.models import ClusterMember, GoldenRecord, MigrationChange, User


@pytest.fixture(scope="module")
def migratable(pipeline_run):
    """Seed the mock ERP and issue a few codes, so there is something to migrate."""
    from fastapi.testclient import TestClient

    from app.db import SessionLocal
    from app.main import app

    with SessionLocal() as db:
        erp.seed_from_catalogue(db)

    with TestClient(app) as client:
        client.post(
            "/api/auth/login", json={"email": "registrar@min.gov.in", "password": "demo"}
        )
        with SessionLocal() as db:
            golden_ids = db.execute(
                select(GoldenRecord.id)
                .join(ClusterMember, ClusterMember.cluster_id == GoldenRecord.cluster_id)
                .where(GoldenRecord.status == "draft")
                .group_by(GoldenRecord.id)
                .having(func.count() >= 2)
                .limit(8)
            ).scalars().all()
        for golden_id in golden_ids:
            client.post(f"/api/cnmc/issue/{golden_id}")
    return len(golden_ids)


@pytest.fixture
def registrar(db):
    return db.execute(select(User).where(User.email == "registrar@min.gov.in")).scalar_one()


class TestMockErp:
    def test_the_mock_has_the_sap_tables_a_consolidation_touches(self, migratable):
        with erp.connect() as conn:
            for table in erp.TABLES:
                assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] >= 0

    def test_the_fingerprint_changes_only_when_the_data_does(self, migratable):
        first = erp.fingerprint()
        assert erp.fingerprint() == first
        adapter = erp.MockErpAdapter()
        with erp.connect() as conn:
            matnr = conn.execute("SELECT matnr FROM mara LIMIT 1").fetchone()[0]
        before = adapter.read_masters([matnr])[matnr]
        adapter.write_crossref(matnr, "TEST-000-000001-1")
        assert erp.fingerprint() != first
        adapter.restore(matnr, before)
        assert erp.fingerprint() == first

    def test_blocking_never_deletes(self, migratable):
        """§2C: a superseded material is blocked; the row and its history stay."""
        adapter = erp.MockErpAdapter()
        with erp.connect() as conn:
            matnr = conn.execute("SELECT matnr FROM mara LIMIT 1").fetchone()[0]
        before = adapter.read_masters([matnr])[matnr]
        adapter.block_material(matnr, "SURVIVOR-1")
        after = adapter.read_masters([matnr])[matnr]
        assert after["lvorm"] == "X" and after["zz_supersedes"] == "SURVIVOR-1"
        with erp.connect() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM mara WHERE matnr = ?", (matnr,)
            ).fetchone()[0] == 1
        adapter.restore(matnr, before)


class TestPlanAndDryRun:
    def test_only_approved_coded_clusters_are_planned(self, db, migratable):
        planned = migration.plan(db)
        assert planned["clusters"] > 0
        assert all(change["cnmc"] for change in planned["changes"])

    def test_one_member_survives_and_the_rest_are_blocked(self, db, migratable):
        planned = migration.plan(db)
        by_cluster: dict[int, list[dict]] = {}
        for change in planned["changes"]:
            by_cluster.setdefault(change["cluster_id"], []).append(change)
        for changes in by_cluster.values():
            survivors = [c for c in changes if c["action"] == "crossref"]
            assert len(survivors) == 1, "exactly one master survives per cluster"
            for blocked in (c for c in changes if c["action"] == "block"):
                assert blocked["surviving_matnr"] == survivors[0]["matnr"]

    def test_an_open_purchase_order_holds_the_record(self, db, migratable):
        """§2C acceptance: this is the step consolidations get wrong."""
        planned = migration.plan(db)
        with_pos = [c for c in planned["changes"] if c["open_po_lines"] > 0]
        assert with_pos, "the fixture needs a material with an open PO"
        assert all(c["impact"] == migration.IMPACT_HOLD for c in with_pos)

    def test_the_dry_run_shows_the_exact_diff(self, db, migratable):
        preview = migration.dry_run(db)
        crossref = next(c for c in preview["changes"] if c["action"] == "crossref")
        assert crossref["diff"]["zz_cnmc"]["after"] == crossref["cnmc"]
        block = next(c for c in preview["changes"] if c["action"] == "block")
        assert block["diff"]["lvorm"]["after"] == "X"

    def test_the_dry_run_writes_nothing(self, db, migratable):
        before = erp.fingerprint()
        migration.dry_run(db)
        assert erp.fingerprint() == before

    def test_held_records_are_excluded_from_what_would_apply(self, db, migratable):
        preview = migration.dry_run(db)
        assert preview["would_apply"] + preview["would_hold"] == len(preview["changes"])
        for change in preview["changes"]:
            assert change["will_apply"] == (change["impact"] == migration.IMPACT_SAFE)

    def test_exceptions_are_ordered_before_the_safe_majority(self, db, migratable):
        windowed = migration.paginate(migration.dry_run(db))
        ranks = [migration.IMPACT_ORDER[c["impact"]] for c in windowed["changes"]]
        assert ranks == sorted(ranks), "a reviewer meets the exceptions first"

    def test_a_window_keeps_the_totals_whole(self, db, migratable):
        """A paginated count is a wrong count, and the traffic light is the
        reason anyone opens this screen."""
        full = migration.dry_run(db)
        windowed = migration.paginate(full, limit=2)
        assert len(windowed["changes"]) == 2
        assert windowed["total_changes"] == full["summary"]["total"]
        assert windowed["summary"] == full["summary"]
        assert windowed["would_apply"] == full["would_apply"]
        assert windowed["truncated"] is True

    def test_the_window_walks_the_whole_plan(self, db, migratable):
        full = migration.dry_run(db)
        seen = []
        for offset in range(0, full["summary"]["total"], 3):
            seen += [c["matnr"] for c in migration.paginate(full, 3, offset)["changes"]]
        assert sorted(seen) == sorted(c["matnr"] for c in full["changes"])

    def test_the_conflict_threshold_is_stated(self, db, migratable):
        assert "₹" in migration.dry_run(db)["thresholds"]["note"]


class TestApplyAndRollback:
    def test_applying_changes_the_erp(self, db, registrar, migratable):
        before = erp.fingerprint()
        result = migration.apply(db, registrar)
        try:
            assert result["applied"] > 0
            assert result["erp_fingerprint_after"] != before
        finally:
            migration.rollback(db, result["batch_id"], registrar)

    def test_held_rows_are_journaled_but_not_written(self, db, registrar, migratable):
        result = migration.apply(db, registrar)
        try:
            held = db.execute(
                select(func.count(MigrationChange.id)).where(
                    MigrationChange.batch_id == result["batch_id"],
                    MigrationChange.state == migration.STATE_HELD,
                )
            ).scalar()
            assert held == result["held"]
            for change in db.execute(
                select(MigrationChange).where(
                    MigrationChange.batch_id == result["batch_id"],
                    MigrationChange.state == migration.STATE_HELD,
                )
            ).scalars():
                assert change.after_json is None, "a held row must have no after-image"
        finally:
            migration.rollback(db, result["batch_id"], registrar)

    def test_rollback_restores_a_byte_identical_erp(self, db, registrar, migratable):
        """§2C acceptance, asserted by hashing every row rather than assumed."""
        before = erp.fingerprint()
        result = migration.apply(db, registrar)
        assert erp.fingerprint() != before, "the apply must have changed something"
        rolled = migration.rollback(db, result["batch_id"], registrar)
        assert rolled["erp_fingerprint"] == before

    def test_verify_reports_the_batch_in_sync(self, db, registrar, migratable):
        result = migration.apply(db, registrar)
        try:
            assert migration.verify(db, result["batch_id"])["in_sync"] is True
        finally:
            migration.rollback(db, result["batch_id"], registrar)

    def test_verify_notices_drift(self, db, registrar, migratable):
        """Someone editing the ERP behind our back must be visible."""
        result = migration.apply(db, registrar)
        try:
            applied = db.execute(
                select(MigrationChange).where(
                    MigrationChange.batch_id == result["batch_id"],
                    MigrationChange.state == migration.STATE_APPLIED,
                ).limit(1)
            ).scalar_one()
            erp.MockErpAdapter().write_crossref(applied.erp_key, "TAMPERED-000-000001-1")
            report = migration.verify(db, result["batch_id"])
            assert not report["in_sync"]
            assert report["drifted"][0]["matnr"] == applied.erp_key
        finally:
            migration.rollback(db, result["batch_id"], registrar)

    def test_applying_twice_does_not_double_apply(self, db, registrar, migratable):
        first = migration.apply(db, registrar)
        after_first = erp.fingerprint()
        second = migration.apply(db, registrar)
        try:
            assert erp.fingerprint() == after_first, "a retried batch must be idempotent"
            assert second["already_in_state"] > 0
        finally:
            migration.rollback(db, second["batch_id"], registrar)
            migration.rollback(db, first["batch_id"], registrar)

    def test_every_batch_is_audited(self, db, registrar, migratable):
        from app.models import AuditEvent

        before = db.execute(select(func.count(AuditEvent.id))).scalar()
        result = migration.apply(db, registrar)
        migration.rollback(db, result["batch_id"], registrar)
        db.expire_all()
        assert db.execute(select(func.count(AuditEvent.id))).scalar() == before + 2

    def test_an_adapter_without_bulk_writes_still_works(self, db, registrar, migratable):
        """The Protocol declares bulk forms; an older adapter may not have them,
        and refusing to migrate against it would be the wrong failure."""

        class SingularOnly:
            """Exposes only the row-at-a-time methods."""

            def __init__(self):
                self._inner = erp.MockErpAdapter()

            def read_masters(self, matnrs):
                return self._inner.read_masters(matnrs)

            def read_open_transactions(self, matnrs):
                return self._inner.read_open_transactions(matnrs)

            def write_crossref(self, matnr, cnmc):
                return self._inner.write_crossref(matnr, cnmc)

            def block_material(self, matnr, supersedes):
                return self._inner.block_material(matnr, supersedes)

            def restore(self, matnr, before):
                return self._inner.restore(matnr, before)

        adapter = SingularOnly()
        before = erp.fingerprint()
        result = migration.apply(db, registrar, adapter=adapter)
        assert result["applied"] > 0
        assert erp.fingerprint() != before
        migration.rollback(db, result["batch_id"], registrar, adapter=adapter)
        assert erp.fingerprint() == before

    def test_bulk_and_singular_writes_produce_the_same_erp(self, db, registrar, migratable):
        adapter = erp.MockErpAdapter()
        baseline = erp.fingerprint()

        bulk = migration.apply(db, registrar)
        bulk_fingerprint = erp.fingerprint()
        migration.rollback(db, bulk["batch_id"], registrar)
        assert erp.fingerprint() == baseline

        pairs_crossref, pairs_block = [], []
        preview = migration.dry_run(db)
        for change in preview["changes"]:
            if not change["will_apply"]:
                continue
            if change["action"] == "crossref":
                pairs_crossref.append((change["matnr"], change["cnmc"]))
            else:
                pairs_block.append((change["matnr"], change["surviving_matnr"]))
        for matnr, cnmc in pairs_crossref:
            adapter.write_crossref(matnr, cnmc)
        for matnr, supersedes in pairs_block:
            adapter.block_material(matnr, supersedes)

        assert erp.fingerprint() == bulk_fingerprint
        adapter.restore_many(
            [
                (c["matnr"], c["before"])
                for c in preview["changes"]
                if c["will_apply"]
            ]
        )
        assert erp.fingerprint() == baseline

    def test_the_journal_holds_a_before_image_for_every_row(self, db, registrar, migratable):
        result = migration.apply(db, registrar)
        try:
            for change in db.execute(
                select(MigrationChange).where(MigrationChange.batch_id == result["batch_id"])
            ).scalars():
                assert json.loads(change.before_json) is not None
        finally:
            migration.rollback(db, result["batch_id"], registrar)


class TestMigrationApi:
    def test_a_steward_may_plan_but_not_apply(self, as_steward, migratable):
        assert as_steward.post("/api/migration/dryrun", json={}).status_code == 200
        assert as_steward.post("/api/migration/apply", json={}).status_code == 403

    def test_a_stewards_plan_withholds_other_cpses_valuations(self, as_steward, migratable):
        """A plan names every duplicate nationally -- §0.9b still applies to it."""
        body = as_steward.post("/api/migration/dryrun", json={}).json()
        assert body["visibility"]["sees_attributed_prices"] is False
        mine = [c for c in body["changes"] if c["cpse"] == body["visibility"]["cpse"]]
        theirs = [c for c in body["changes"] if c["cpse"] != body["visibility"]["cpse"]]
        assert theirs, "the fixture needs another CPSE in the plan"
        assert all(c["total_value"] is None and c["price_withheld"] for c in theirs)
        assert all(c["total_value"] is not None for c in mine)

    def test_a_registrar_sees_the_valuations(self, as_registrar, migratable):
        body = as_registrar.post("/api/migration/dryrun", json={}).json()
        assert body["visibility"]["sees_attributed_prices"] is True
        assert all("price_withheld" not in c for c in body["changes"])

    def test_a_registrar_can_apply_and_roll_back(self, as_registrar, migratable):
        applied = as_registrar.post("/api/migration/apply", json={}).json()
        assert applied["applied"] > 0
        rolled = as_registrar.post(f"/api/migration/rollback/{applied['batch_id']}")
        assert rolled.status_code == 200

    def test_the_api_windows_a_plan(self, as_registrar, migratable):
        body = as_registrar.post("/api/migration/dryrun", json={"limit": 2}).json()
        assert len(body["changes"]) == 2 and body["truncated"] is True
        assert body["total_changes"] > 2

    def test_applying_is_never_windowed(self, as_registrar, migratable):
        """An apply that acted on page one only would be a data-integrity bug."""
        applied = as_registrar.post("/api/migration/apply", json={"limit": 1}).json()
        try:
            assert applied["applied"] + applied["held"] > 1
        finally:
            as_registrar.post(f"/api/migration/rollback/{applied['batch_id']}")

    def test_an_unknown_batch_is_404(self, as_registrar, migratable):
        assert as_registrar.post("/api/migration/rollback/999999").status_code == 404

    def test_the_erp_state_is_readable(self, as_registrar, migratable):
        body = as_registrar.get("/api/migration/erp").json()
        assert body["counts"]["mara"] > 0 and body["fingerprint"]
        assert "never deleted" in body["note"]

    def test_the_journal_lists_batches(self, as_registrar, migratable):
        applied = as_registrar.post("/api/migration/apply", json={}).json()
        try:
            listing = as_registrar.get("/api/migration/batches").json()
            assert any(b["id"] == applied["batch_id"] for b in listing["batches"])
            detail = as_registrar.get(f"/api/migration/batches/{applied['batch_id']}").json()
            assert detail["changes"] and detail["verification"]["in_sync"]
        finally:
            as_registrar.post(f"/api/migration/rollback/{applied['batch_id']}")
