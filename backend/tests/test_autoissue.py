"""Codes that issue themselves, under a registrar's policy: every gate stated,
off by default, and the registrar who set it is the issuer of record."""

import json

import pytest
from sqlalchemy import select

from app import autoissue
from app.models import AuditEvent, Cnmc, GoldenRecord, User


class TestPolicy:
    def test_off_by_default_and_nothing_issues(self, as_registrar, pipeline_run):
        body = as_registrar.get("/api/autoissue/status").json()
        assert all(row["enabled"] is False for row in body["families"])
        assert body["eligible"] == 0
        assert body["not_eligible"].get("policy off", 0) > 0

    def test_only_a_registrar_sets_it_and_the_change_is_audited(self, client, db, pipeline_run):
        client.post("/api/auth/login", json={"email": "steward@cpcl.in", "password": "demo"})
        assert client.put("/api/autoissue/policy/BRNG", json={"enabled": True}).status_code == 403
        client.post("/api/auth/login", json={"email": "registrar@min.gov.in", "password": "demo"})
        as_registrar = client
        set_ = as_registrar.put(
            "/api/autoissue/policy/BRNG", json={"enabled": True, "min_precision": 0.98}
        )
        assert set_.status_code == 200, set_.text
        assert set_.json()["enabled"] is True and set_.json()["min_precision"] == 0.98
        event = (
            db.execute(
                select(AuditEvent)
                .where(AuditEvent.action == "policy.autoissue")
                .order_by(AuditEvent.seq.desc())
            )
            .scalars()
            .first()
        )
        assert event is not None and event.user == "registrar@min.gov.in"
        assert json.loads(event.payload_json)["after"] == {"enabled": True, "min_precision": 0.98}
        assert (
            as_registrar.put("/api/autoissue/policy/ZZZZ", json={"enabled": True}).status_code
            == 422
        )
        as_registrar.put("/api/autoissue/policy/BRNG", json={"enabled": False})


class TestGates:
    def test_a_dry_run_names_every_reason_a_cluster_is_held_back(
        self, as_registrar, db, pipeline_run
    ):
        as_registrar.put(
            "/api/autoissue/policy/GSKT", json={"enabled": True, "min_precision": 0.99}
        )
        try:
            body = as_registrar.post("/api/autoissue/run", json={"dry_run": True}).json()
            assert body["dry_run"] is True
            reasons = body["not_eligible"]
            # Families without a policy are held back as such; whatever else is
            # held back is held back for a stated reason.
            assert "policy off" in reasons
            for row in body["issued"]:
                assert row["family"] == "GSKT" and row["members"] >= 2 and row["code"] is None
        finally:
            as_registrar.put("/api/autoissue/policy/GSKT", json={"enabled": False})

    def test_a_class_below_its_target_never_issues(self, as_registrar, db, pipeline_run):
        precision = autoissue.class_precision(db)
        if not precision:
            pytest.skip("no held-out snapshot")
        as_registrar.put("/api/autoissue/policy/BRNG", json={"enabled": True, "min_precision": 1.0})
        try:
            candidates, reasons = autoissue.eligible(db, "BRNG")
            bearing = precision.get("bearing.ball.deep_groove", 1.0)
            if bearing < 1.0:
                assert candidates == []
                assert any(k.startswith("precision") for k in reasons)
        finally:
            as_registrar.put("/api/autoissue/policy/BRNG", json={"enabled": False})

    def test_the_cluster_gate_reads_anchor_agreement_and_veto(self, db, pipeline_run):
        from app.models import ClusterMember, Pair

        # A vetoed pair inside a cluster would fail the gate; find any pair
        # with a veto and confirm the gate says so for its two items.
        vetoed = (
            db.execute(
                select(Pair).where(Pair.veto_json.isnot(None), Pair.veto_json != "null").limit(1)
            )
            .scalars()
            .first()
        )
        if vetoed is None:
            pytest.skip("no vetoed pair")
        passes, n, why = autoissue._cluster_gate(db, 0, [vetoed.item_a, vetoed.item_b])
        assert passes is False and n == 1 and why in ("a pair was vetoed", "a pair is distinct")
        # A single row has nothing to compare.
        one = db.execute(select(ClusterMember.item_id).limit(1)).scalar()
        assert autoissue._cluster_gate(db, 0, [one]) == (False, 0, "single row: nothing to compare")


class TestIssuing:
    def test_codes_issue_in_the_name_of_the_registrar_who_set_the_policy(
        self, as_registrar, db, pipeline_run
    ):
        # Find a family with at least one eligible cluster under a lenient target.
        chosen = None
        for family in autoissue.FAMILIES:
            as_registrar.put(
                "/api/autoissue/policy/" + family, json={"enabled": True, "min_precision": 0.9}
            )
            candidates, _ = autoissue.eligible(db, family)
            if candidates:
                chosen = family
                break
            as_registrar.put("/api/autoissue/policy/" + family, json={"enabled": False})
        if chosen is None:
            pytest.skip("no cluster passes the gates in this estate")
        try:
            body = as_registrar.post(
                "/api/autoissue/run", json={"dry_run": False, "family": chosen, "limit": 3}
            ).json()
            assert body["issued"] and all(row["code"] for row in body["issued"])
            registrar = db.execute(
                select(User).where(User.email == "registrar@min.gov.in")
            ).scalar_one()
            for row in body["issued"]:
                cnmc = db.execute(select(Cnmc).where(Cnmc.code == row["code"])).scalar_one()
                assert cnmc.issued_by == registrar.id
                golden = db.get(GoldenRecord, row["golden_id"])
                assert golden.status == "approved"
                event = (
                    db.execute(select(AuditEvent).where(AuditEvent.entity == f"cnmc:{row['code']}"))
                    .scalars()
                    .first()
                )
                assert json.loads(event.payload_json)["policy"] == "auto"
            summary = (
                db.execute(
                    select(AuditEvent)
                    .where(AuditEvent.action == "cnmc.autoissue")
                    .order_by(AuditEvent.seq.desc())
                )
                .scalars()
                .first()
            )
            assert summary is not None and json.loads(summary.payload_json)["issued"] == len(
                body["issued"]
            )
            status = as_registrar.get("/api/autoissue/status").json()
            assert status["issued_under_policy"] >= len(body["issued"])
        finally:
            as_registrar.put("/api/autoissue/policy/" + chosen, json={"enabled": False})
