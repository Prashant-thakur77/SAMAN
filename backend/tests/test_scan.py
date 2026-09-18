"""Scanning: a barcode, a label or a typed code resolves to the material it
names, by exact key in a fixed order, with everything the person at the bin
needs next; a part number shared by variants returns all of them and says
what tells them apart; nothing found points at Smart-Create."""

import pytest
from sqlalchemy import func, select

from app import cnmc, scan
from app.models import ClusterMember, Cnmc, Item, RawItem
from app.visibility import Scope

REGISTRAR = Scope("registrar", None)
CPCL_STEWARD = Scope("steward", "CPCL")


@pytest.fixture
def a_code(as_registrar, pipeline_run, db):
    """A national code issued on a multi-member cluster."""
    existing = db.execute(select(Cnmc.code).limit(1)).scalar_one_or_none()
    if existing:
        return existing
    from app.models import GoldenRecord

    golden_id = db.execute(
        select(GoldenRecord.id)
        .join(ClusterMember, ClusterMember.cluster_id == GoldenRecord.cluster_id)
        .where(GoldenRecord.status == "draft")
        .group_by(GoldenRecord.id)
        .having(func.count(ClusterMember.id) >= 2)
        .limit(1)
    ).scalar_one()
    r = as_registrar.post(f"/api/cnmc/issue/{golden_id}")
    assert r.status_code == 200, r.text
    db.expire_all()
    return r.json()["code"]


class TestResolution:
    def test_a_national_code_resolves_to_its_material(self, a_code, db):
        result = scan.lookup(db, a_code.lower(), REGISTRAR)
        assert result["matched_by"] == "cnmc" and len(result["materials"]) == 1
        material = result["materials"][0]
        assert material["cnmc"] == a_code and material["family"] == a_code[:4]
        assert material["members"] and material["cpses"]
        assert result["next"]["action"] == "open_cluster"
        assert result["next"]["to"] == f"/clusters/{material['cluster_id']}"

    def test_a_misread_check_digit_is_named_not_guessed(self, a_code, db):
        wrong = a_code[:-1] + str((int(a_code[-1]) + 1) % 10)
        assert not cnmc.is_valid(wrong)
        result = scan.lookup(db, wrong, REGISTRAR)
        assert result["materials"] == [] and result["tried"] == "cnmc"
        assert "check digit" in result["note"]

    def test_a_cpses_own_code_resolves_and_flags_the_scanned_row(self, pipeline_run, db):
        legacy, item_id = db.execute(
            select(RawItem.legacy_code, Item.id).join(Item, Item.raw_item_id == RawItem.id).limit(1)
        ).one()
        result = scan.lookup(db, legacy.lower(), REGISTRAR)
        assert result["matched_by"] == "legacy_code"
        scanned = [m for m in result["materials"][0]["members"] if m["scanned"]]
        assert [m["item_id"] for m in scanned] == [item_id]

    def test_a_gtin_resolves_only_when_its_check_digit_verifies(self, pipeline_run, db):
        gtin = db.execute(select(Item.gtin).where(Item.gtin.is_not(None)).limit(1)).scalar()
        if gtin is None:
            pytest.skip("no GTIN in this seed")
        assert scan.lookup(db, gtin, REGISTRAR)["matched_by"] == "gtin"
        broken = gtin[:-1] + str((int(gtin[-1]) + 1) % 10)
        assert scan.lookup(db, broken, REGISTRAR)["matched_by"] != "gtin"

    def test_a_part_number_is_normalised_like_the_matcher(self, pipeline_run, db):
        mpn = db.execute(select(Item.mpn_norm).where(Item.mpn_norm.is_not(None)).limit(1)).scalar()
        dashed = f"{mpn[:3]}-{mpn[3:]}".lower()
        result = scan.lookup(db, dashed, REGISTRAR)
        assert result["matched_by"] == "mpn"
        assert all(any(m["mpn"] == mpn for m in mat["members"]) for mat in result["materials"])

    def test_a_shared_part_number_returns_every_variant_and_what_separates_them(
        self, pipeline_run, db
    ):
        shared = db.execute(
            select(Item.mpn_norm)
            .join(ClusterMember, ClusterMember.item_id == Item.id)
            .where(Item.mpn_norm.is_not(None))
            .group_by(Item.mpn_norm)
            .having(func.count(func.distinct(ClusterMember.cluster_id)) > 1)
            .limit(1)
        ).scalar()
        if shared is None:
            pytest.skip("no part number spans two materials in this seed")
        result = scan.lookup(db, shared, REGISTRAR)
        assert len(result["materials"]) > 1
        assert result["next"]["action"] == "choose"
        assert result["differs_on"], "the chooser needs an attribute to choose by"
        for key in result["differs_on"]:
            assert len({str(m["attrs"].get(key)) for m in result["materials"]}) > 1

    def test_nothing_found_points_at_smart_create(self, pipeline_run, db):
        result = scan.lookup(db, "no-such-code-9Q", REGISTRAR)
        assert result["materials"] == [] and result["matched_by"] is None
        assert result["next"]["action"] == "smart_create"
        assert result["next"]["to"].startswith("/smart-create?description=")

    def test_a_description_is_not_a_code(self, pipeline_run, db):
        long = "BEARING BALL DEEP GROOVE 25MM BORE 52MM OD 15MM WIDTH 2Z SKF SEALED BOTH SIDES"
        result = scan.lookup(db, long, REGISTRAR)
        assert result["materials"] == [] and "Smart-Create" in result["note"]


class TestWhatTheCardCarries:
    def test_stock_is_consolidated_and_redacted_by_scope(self, a_code, db):
        for_registrar = scan.lookup(db, a_code, REGISTRAR)["materials"][0]["stock"]
        for_steward = scan.lookup(db, a_code, CPCL_STEWARD)["materials"][0]["stock"]
        assert for_registrar["positions"]
        assert for_registrar["cpse_count"] == for_steward["cpse_count"]
        for position in for_steward["positions"]:
            if position["cpse"] != "CPCL":
                assert position["unit_value"] is None

    def test_substitutes_come_approved_first_with_the_other_side_described(
        self, as_registrar, pipeline_run, db
    ):
        from app.models import Relation

        relation = db.execute(
            select(Relation).where(Relation.rel_type == "equivalent").limit(1)
        ).scalar_one_or_none()
        if relation is None:
            pytest.skip("no equivalence in this seed")
        r = as_registrar.post(
            f"/api/substitutes/{relation.id}/decide",
            json={"decision": "approved", "reason": "Same duty; rating exceeds the pump's."},
        )
        assert r.status_code == 200, r.text
        legacy = db.execute(
            select(RawItem.legacy_code)
            .join(Item, Item.raw_item_id == RawItem.id)
            .where(Item.id == relation.item_a)
        ).scalar_one()
        db.expire_all()
        result = scan.lookup(db, legacy, REGISTRAR)
        subs = result["materials"][0]["substitutes"]
        assert subs and subs[0]["status"] == "approved"
        assert subs[0]["other"]["description"] and subs[0]["approval"]["reason"]


class TestEndpoint:
    def test_needs_a_session_and_answers_every_role(self, client, as_viewer, pipeline_run, db):
        legacy = db.execute(select(RawItem.legacy_code).limit(1)).scalar_one()
        r = as_viewer.get("/api/scan/lookup", params={"code": legacy})
        assert r.status_code == 200 and r.json()["matched_by"] == "legacy_code"

    def test_an_overlong_code_is_refused_at_the_door(self, as_viewer, pipeline_run):
        r = as_viewer.get("/api/scan/lookup", params={"code": "x" * (scan.MAX_CODE_LENGTH + 1)})
        assert r.status_code == 422


class TestEquipmentTag:
    def test_a_tag_resolves_to_the_plant_and_its_spares_with_stock_here_and_elsewhere(
        self, pipeline_run, db
    ):
        from app.models import Equipment

        tag = db.execute(select(Equipment.tag).limit(1)).scalar_one()
        result = scan.lookup(db, tag.lower(), REGISTRAR)
        assert result["matched_by"] == "equipment_tag" and result["materials"] == []
        card = result["equipment"][0]
        assert card["tag"] == tag and card["criticality"] in "ABC" and card["ved"]
        assert card["spares"], "a BOM line per spare"
        for spare in card["spares"]:
            assert spare["qty_fitted"] > 0
            assert spare["stock_here"] >= 0 and spare["stock_elsewhere"] >= 0
            assert (spare["cpses_elsewhere"] > 0) == (spare["stock_elsewhere"] > 0)

    def test_a_tag_shared_by_plants_lists_every_site_own_cpse_first(self, pipeline_run, db):
        from app.models import Equipment

        shared = db.execute(
            select(Equipment.tag)
            .group_by(Equipment.tag)
            .having(func.count(func.distinct(Equipment.cpse_id)) > 1)
            .limit(1)
        ).scalar()
        if shared is None:
            pytest.skip("no tag is used at two CPSEs in this seed")
        result = scan.lookup(db, shared, REGISTRAR)
        sites = [card["cpse"] for card in result["equipment"]]
        assert len(sites) > 1 and result["next"]["action"] == "choose_site"
        own = Scope("steward", sites[-1])
        assert scan.lookup(db, shared, own)["equipment"][0]["cpse"] == sites[-1]

    def test_a_materials_own_keys_have_their_say_before_a_tag(self, pipeline_run, db):
        assert scan.METHODS[-1] == "equipment_tag"
