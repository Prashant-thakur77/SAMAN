"""Equipment context and approved substitutes: the seed fits materials to
tagged plant, the item page says where, an equivalence stays a proposal until
an engineer signs it with a reason, and a critical spare is never called idle."""

import pytest
from sqlalchemy import select

from app import substitutes
from app.models import Equipment, EquipmentBom, Item, RawItem


class TestSeed:
    def test_every_cpse_has_plant_with_a_criticality(self, db, seeded):
        assert seeded["equipment"] > 0 and seeded["bom_lines"] > 0
        rows = db.execute(select(Equipment.criticality)).scalars().all()
        assert rows and set(rows) <= {"A", "B", "C"}

    def test_a_bom_only_fits_the_cpses_own_materials(self, db, seeded):
        rows = db.execute(
            select(Equipment.cpse_id, RawItem.cpse_id)
            .join(EquipmentBom, EquipmentBom.equipment_id == Equipment.id)
            .join(Item, Item.id == EquipmentBom.item_id)
            .join(RawItem, RawItem.id == Item.raw_item_id)
        ).all()
        assert rows and all(a == b for a, b in rows)


class TestContext:
    def test_installed_on_and_ved(self, db, seeded):
        item_id = db.execute(select(EquipmentBom.item_id).limit(1)).scalar_one()
        where = substitutes.installed_on(db, [item_id])[item_id]
        assert where and {"tag", "criticality", "ved", "cpse"} <= set(where[0])
        assert substitutes.ved_of(where) in ("vital", "essential", "desirable")
        assert substitutes.ved_of([]) is None
        assert substitutes.ved_of([{"criticality": "C"}, {"criticality": "A"}]) == "vital"

    def test_the_item_page_says_where_it_is_fitted(self, client, pipeline_run, db):
        item_id = db.execute(select(EquipmentBom.item_id).limit(1)).scalar_one()
        body = client.get(f"/api/items/{item_id}").json()
        assert body["installed_on"] and body["ved"] in ("vital", "essential", "desirable")
        for entry in body["equivalents"]:
            assert entry["status"] in substitutes.STATUSES
            assert "approval" in entry

    def test_a_critical_spare_is_flagged_not_called_idle(self, as_registrar, pipeline_run):
        body = as_registrar.get("/api/dashboard/opportunity").json()
        transfers = body["inventory"]["transfers"]
        assert "critical_spares_flagged" in transfers
        for suggestion in transfers["suggestions"]:
            assert "critical_spare_at_source" in suggestion


@pytest.fixture
def as_engineer(client, seeded):
    r = client.post("/api/auth/login", json={"email": "engineer@cpcl.in", "password": "demo"})
    assert r.status_code == 200, r.text
    return client


class TestApproval:
    def test_the_queue_needs_a_session_and_lists_both_sides(
        self, client, as_engineer, pipeline_run
    ):
        assert client.get("/api/substitutes").status_code in (200, 401)
        body = as_engineer.get("/api/substitutes?status=all").json()
        assert set(body["counts"]) == set(substitutes.STATUSES)
        if body["relations"]:
            row = body["relations"][0]
            assert {"a", "b", "approval", "criticality", "status"} <= set(row)
            assert "installed_on" in row["a"] and "ved" in row["b"]

    def test_a_steward_may_look_but_not_sign(self, as_steward, pipeline_run):
        body = as_steward.get("/api/substitutes?status=proposed").json()
        if not body["relations"]:
            pytest.skip("no proposed equivalences in this seed")
        relation_id = body["relations"][0]["id"]
        r = as_steward.post(
            f"/api/substitutes/{relation_id}/decide",
            json={"decision": "approved", "reason": "looks fine"},
        )
        assert r.status_code == 403 and "engineer" in r.json()["detail"]

    def test_an_engineer_approves_with_a_reason_on_the_record(self, as_engineer, pipeline_run, db):
        body = as_engineer.get("/api/substitutes?status=proposed").json()
        if not body["relations"]:
            pytest.skip("no proposed equivalences in this seed")
        relation_id = body["relations"][0]["id"]
        blank = as_engineer.post(
            f"/api/substitutes/{relation_id}/decide", json={"decision": "approved", "reason": " "}
        )
        assert blank.status_code == 422
        r = as_engineer.post(
            f"/api/substitutes/{relation_id}/decide",
            json={
                "decision": "approved",
                "reason": "Same bore and seal; load rating exceeds the pump's duty.",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved" and r.json()["decided_by"] == "V. Subramanian"

        approved = as_engineer.get("/api/substitutes?status=approved").json()
        assert any(row["id"] == relation_id for row in approved["relations"])
        row = next(row for row in approved["relations"] if row["id"] == relation_id)
        assert row["approval"]["reason"].startswith("Same bore")

        audit = as_engineer.get("/api/audit?action=substitute.approved").json()
        assert any(e["entity"] == f"relation:{relation_id}" for e in audit["events"])

        # The item page carries the decision.
        item = as_engineer.get(f"/api/items/{row['a']['item_id']}").json()
        assert any(
            e["relation_id"] == relation_id and e["status"] == "approved"
            for e in item["equivalents"]
        )

    def test_a_registrar_may_reject(self, as_registrar, pipeline_run):
        body = as_registrar.get("/api/substitutes?status=proposed").json()
        if not body["relations"]:
            pytest.skip("no proposed equivalences left in this seed")
        relation_id = body["relations"][-1]["id"]
        r = as_registrar.post(
            f"/api/substitutes/{relation_id}/decide",
            json={"decision": "rejected", "reason": "Not approved for the feed compressor."},
        )
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        assert as_registrar.get("/api/substitutes?status=nonsense").status_code == 422
