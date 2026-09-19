"""Smart-Create — duplicate prevention at source (spec §5)."""

import pytest
from sqlalchemy import select

from app import smart_create
from app.models import AuditEvent, RawItem, SmartCreateCheck, User


@pytest.fixture
def steward(db):
    return db.execute(select(User).where(User.email == "steward@cpcl.in")).scalar_one()


@pytest.fixture
def catalogue_row(db, pipeline_run):
    return db.execute(select(RawItem.description, RawItem.uom).limit(1)).one()


class TestTheProbe:
    def test_a_description_is_normalized_and_classified_like_a_catalogue_row(
        self, db, pipeline_run
    ):
        probe = smart_create.build_probe(
            db, "BRG,BALL,25MM BORE,52MM OD,15MM W,ZZ,SKF", None, "NOS"
        )
        assert probe.class_code == "bearing.ball.deep_groove"
        assert probe.attrs["bore_mm"] == 25.0
        assert probe.uom_base == "EA"

    def test_a_typed_part_number_beats_one_guessed_from_the_text(self, db, pipeline_run):
        probe = smart_create.build_probe(db, "BEARING BALL 6205 ZZ SKF", "SKF-6205-2Z", None)
        assert probe.mpn_norm == "SKF62052Z"

    def test_the_probe_is_embedded_with_the_corpus_model(self, db, pipeline_run):
        probe = smart_create.build_probe(db, "BEARING BALL 6205 ZZ SKF", None, None)
        assert probe.vector is not None and probe.vector.size > 0

    def test_an_empty_description_is_refused(self, db, pipeline_run):
        with pytest.raises(ValueError, match="description is required"):
            smart_create.check(db, "   ")


class TestTheCheck:
    def test_an_existing_material_is_found(self, db, catalogue_row):
        description, uom = catalogue_row
        result = smart_create.check(db, description, uom=uom)
        assert result["recommendation"]["action"] == "reuse"
        assert result["suggestions"][0]["confidence"] >= smart_create.STRONG_MATCH
        assert result["suggestions"][0]["verdict"] == "duplicate"

    def test_it_finds_the_same_item_written_in_another_cpses_style(self, db, catalogue_row):
        """The point of the feature: the buyer is not typing our exact string."""
        description, uom = catalogue_row
        reworded = description.replace(",", " ").replace("BRG", "BEARING").lower()
        result = smart_create.check(db, reworded, uom=uom)
        assert result["suggestions"], "a reworded description must still match"

    def test_a_genuinely_new_item_is_cleared_to_create(self, db, pipeline_run):
        result = smart_create.check(db, "QUANTUM FLUX CAPACITOR 1.21GW MODEL DLRN-88")
        assert result["recommendation"]["action"] == "create"
        assert result["suggestions"] == []

    def test_a_near_miss_is_ruled_out_by_name(self, db, pipeline_run):
        """§2A: the veto layer must be visible here, not just in the pipeline."""
        result = smart_create.check(db, "BRG,BALL,25MM BORE,52MM OD,15MM W,ZZ,SKF")
        assert result["ruled_out"], "a bearing probe must have close non-matches"
        why = result["ruled_out"][0]["why"]
        assert "not" in why and any(ch.isdigit() for ch in why), why

    def test_another_manufacturers_part_is_an_equivalent_not_a_duplicate(self, db, pipeline_run):
        """§2B: interchangeable is not identical, and merging them would lose that.

        Driven off the seeded equivalence truth rather than a hand-typed
        description, so it tests the engine and not my luck with the catalogue.
        """
        from app.models import Item, TruthEquivalence

        pair = db.execute(
            select(TruthEquivalence.raw_item_a, TruthEquivalence.raw_item_b)
            .where(
                TruthEquivalence.basis == "designation",
                TruthEquivalence.rel_type == "equivalent",
            )
            .limit(1)
        ).first()
        assert pair, "the seed must plant cross-brand equivalents"
        description, uom = db.execute(
            select(RawItem.description, RawItem.uom).where(RawItem.id == pair[0])
        ).one()
        partner = db.execute(select(Item.id).where(Item.raw_item_id == pair[1])).scalar()

        result = smart_create.check(db, description, uom=uom)
        assert partner in [s["item_id"] for s in result["equivalents"]]
        assert partner not in [s["item_id"] for s in result["suggestions"]]

    def test_a_designation_style_record_is_retrieved_for_an_attribute_style_probe(
        self, db, pipeline_run
    ):
        """Retrieval must survive a house-style change, not just a typo.

        "BRG,BALL,6005,ZZ,FAG" and "BEARING BALL 25MM BORE 47MM OD 12MM W" are
        the same bearing written two ways; they share almost no tokens and their
        vectors are only loosely alike. What connects them is the bore, so the
        block-attribute boost has to fire -- and it only fires if 25 and 25.0
        are compared as numbers.
        """
        result = smart_create.check(db, "BEARING BALL 25MM BORE 47MM OD 12MM W ZZ SKF")
        found = result["suggestions"] + result["equivalents"] + result["ruled_out"]
        assert any("6005" in (row["description"] or "") for row in found)

    def test_a_defining_attribute_is_compared_as_a_number(self, db):
        assert smart_create._same_value(25, 25.0)
        assert smart_create._same_value("25.0", "25")
        assert smart_create._same_value("H7", "h7 ")
        assert not smart_create._same_value(25, 30)
        assert not smart_create._same_value(None, 25)

    def test_every_check_is_counted_even_when_nothing_matches(self, db, pipeline_run):
        before = db.execute(select(SmartCreateCheck.id)).all()
        smart_create.check(db, "QUANTUM FLUX CAPACITOR 1.21GW MODEL DLRN-88")
        after = db.execute(select(SmartCreateCheck.id)).all()
        assert len(after) == len(before) + 1

    def test_the_probes_own_reading_comes_back(self, db, pipeline_run):
        """A buyer must be able to see what the platform understood."""
        probe = smart_create.check(db, "BRG,BALL,25MM BORE,52MM OD,15MM W,ZZ,SKF")["probe"]
        assert probe["class_code"] == "bearing.ball.deep_groove"
        assert probe["attrs"]["bore_mm"] == 25.0
        assert not any(key.startswith("_") for key in probe["attrs"])


class TestTheToken:
    def test_a_token_round_trips(self, db, pipeline_run):
        result = smart_create.check(db, "SOMETHING NEW ENTIRELY 12345")
        probe = smart_create.build_probe(db, "SOMETHING NEW ENTIRELY 12345", None, None)
        assert (
            smart_create.verify_token(result["create_token"], probe.norm_hash) == result["check_id"]
        )

    def test_a_tampered_token_is_refused(self, db, pipeline_run):
        result = smart_create.check(db, "SOMETHING NEW ENTIRELY 12345")
        token = result["create_token"]
        tampered = token[:-1] + ("1" if token[-1] == "0" else "0")
        with pytest.raises(ValueError, match="signature"):
            smart_create.verify_token(tampered)

    def test_a_token_is_bound_to_the_description_it_was_issued_for(self, db, pipeline_run):
        result = smart_create.check(db, "SOMETHING NEW ENTIRELY 12345")
        with pytest.raises(ValueError, match="description changed"):
            smart_create.verify_token(result["create_token"], "a-different-hash")

    def test_an_expired_token_is_refused(self, db, pipeline_run, monkeypatch):
        result = smart_create.check(db, "SOMETHING NEW ENTIRELY 12345")
        later = smart_create.time.time() + smart_create.TOKEN_TTL_SECONDS + 1
        monkeypatch.setattr(smart_create.time, "time", lambda: later)
        with pytest.raises(ValueError, match="expired"):
            smart_create.verify_token(result["create_token"])


class TestOutcomes:
    def test_reusing_an_existing_material_counts_as_prevented(self, db, catalogue_row, steward):
        description, uom = catalogue_row
        result = smart_create.check(db, description, uom=uom, user=steward)
        item_id = result["suggestions"][0]["item_id"]
        outcome = smart_create.reuse(db, result["check_id"], item_id, steward)
        assert outcome["outcome"] == "prevented"
        assert db.get(SmartCreateCheck, result["check_id"]).reused_item_id == item_id

    def test_a_check_is_resolved_once(self, db, catalogue_row, steward):
        description, uom = catalogue_row
        result = smart_create.check(db, description, uom=uom, user=steward)
        item_id = result["suggestions"][0]["item_id"]
        smart_create.reuse(db, result["check_id"], item_id, steward)
        with pytest.raises(ValueError, match="already resolved"):
            smart_create.reuse(db, result["check_id"], item_id, steward)

    def test_overriding_a_strong_match_requires_a_reason(self, db, catalogue_row, steward):
        description, uom = catalogue_row
        result = smart_create.check(db, description, uom=uom, user=steward)
        with pytest.raises(ValueError, match="reason is required"):
            smart_create.create_anyway(
                db, result["create_token"], "SC-1", description, uom, None, steward
            )

    def test_an_override_with_a_reason_creates_the_material(self, db, catalogue_row, steward):
        description, uom = catalogue_row
        result = smart_create.check(db, description, uom=uom, user=steward)
        created = smart_create.create_anyway(
            db,
            result["create_token"],
            "SC-OVERRIDE-1",
            description,
            uom,
            "Separate valuation class at a different plant.",
            steward,
        )
        raw = db.get(RawItem, created["raw_item_id"])
        assert raw.legacy_code == "SC-OVERRIDE-1" and raw.cpse_id == steward.cpse_id
        record = db.get(SmartCreateCheck, result["check_id"])
        assert record.outcome == "created_anyway" and record.override_reason

    def test_a_new_item_needs_no_reason(self, db, pipeline_run, steward):
        result = smart_create.check(db, "ENTIRELY NOVEL WIDGET XR-9000", user=steward)
        created = smart_create.create_anyway(
            db,
            result["create_token"],
            "SC-NOVEL-1",
            "ENTIRELY NOVEL WIDGET XR-9000",
            None,
            None,
            steward,
        )
        assert created["outcome"] == "created_anyway"

    def test_a_duplicate_legacy_code_is_refused(self, db, pipeline_run, steward):
        existing = db.execute(
            select(RawItem.legacy_code).where(RawItem.cpse_id == steward.cpse_id).limit(1)
        ).scalar()
        result = smart_create.check(db, "ENTIRELY NOVEL WIDGET XR-9001", user=steward)
        with pytest.raises(ValueError, match="already exists"):
            smart_create.create_anyway(
                db,
                result["create_token"],
                existing,
                "ENTIRELY NOVEL WIDGET XR-9001",
                None,
                None,
                steward,
            )

    def test_both_outcomes_are_audited(self, db, catalogue_row, steward):
        description, uom = catalogue_row
        before = len(db.execute(select(AuditEvent.id)).all())
        first = smart_create.check(db, description, uom=uom, user=steward)
        smart_create.reuse(db, first["check_id"], first["suggestions"][0]["item_id"], steward)
        second = smart_create.check(db, "ENTIRELY NOVEL WIDGET XR-9002", user=steward)
        smart_create.create_anyway(
            db,
            second["create_token"],
            "SC-AUDIT-1",
            "ENTIRELY NOVEL WIDGET XR-9002",
            None,
            None,
            steward,
        )
        assert len(db.execute(select(AuditEvent.id)).all()) == before + 2

    def test_the_override_row_enters_the_catalogue_like_any_other(self, db, pipeline_run, steward):
        """An override is a business decision, not an exemption from matching."""
        result = smart_create.check(db, "ENTIRELY NOVEL WIDGET XR-9003", user=steward)
        created = smart_create.create_anyway(
            db,
            result["create_token"],
            "SC-PIPELINE-1",
            "ENTIRELY NOVEL WIDGET XR-9003",
            None,
            None,
            steward,
        )
        from app.pipeline import build_items

        assert build_items(db, [created["raw_item_id"]]) == 1


class TestStats:
    def test_the_prevention_rate_uses_decided_checks_as_its_denominator(
        self, db, catalogue_row, steward
    ):
        """An open check is not evidence either way, so it must not dilute the rate."""
        description, uom = catalogue_row
        smart_create.check(db, description, uom=uom, user=steward)  # left open
        prevented = smart_create.check(db, description, uom=uom, user=steward)
        smart_create.reuse(db, prevented["check_id"], prevented["suggestions"][0]["item_id"])

        stats = smart_create.stats(db)
        assert stats["prevented"] >= 1
        assert stats["open"] >= 1
        assert stats["prevention_rate"] == round(
            stats["prevented"] / (stats["prevented"] + stats["created_anyway"]), 4
        )

    def test_the_rate_is_none_rather_than_zero_when_nothing_was_decided(self, db):
        from sqlalchemy import delete

        db.execute(delete(SmartCreateCheck))
        db.commit()
        assert smart_create.stats(db)["prevention_rate"] is None


class TestSmartCreateApi:
    def test_a_steward_can_check(self, as_steward, catalogue_row):
        description, uom = catalogue_row
        response = as_steward.post(
            "/api/smart-create/check", json={"description": description, "uom": uom}
        )
        assert response.status_code == 200
        assert response.json()["suggestions"]

    def test_a_viewer_cannot_probe_the_catalogue_by_description(self, as_viewer):
        assert (
            as_viewer.post(
                "/api/smart-create/check", json={"description": "BEARING 6205"}
            ).status_code
            == 403
        )

    def test_a_viewer_can_still_read_the_counter(self, as_viewer):
        assert as_viewer.get("/api/smart-create/stats").status_code == 200

    def test_a_blank_description_is_a_422(self, as_steward):
        assert (
            as_steward.post("/api/smart-create/check", json={"description": ""}).status_code == 422
        )

    def test_the_counter_reaches_the_health_panel(self, as_registrar, catalogue_row):
        """§5: the prevented-duplicate counter belongs on the health dashboard."""
        description, uom = catalogue_row
        checked = as_registrar.post(
            "/api/smart-create/check", json={"description": description, "uom": uom}
        ).json()
        as_registrar.post(
            "/api/smart-create/reuse",
            json={
                "check_id": checked["check_id"],
                "item_id": checked["suggestions"][0]["item_id"],
            },
        )
        panel = as_registrar.get("/api/settings/health").json()
        assert panel["counts"]["duplicates_prevented"] >= 1
        assert panel["smart_create"]["prevention_rate"] is not None

    def test_the_full_flow_over_http(self, as_steward, catalogue_row):
        description, uom = catalogue_row
        checked = as_steward.post(
            "/api/smart-create/check", json={"description": description, "uom": uom}
        ).json()
        reused = as_steward.post(
            "/api/smart-create/reuse",
            json={
                "check_id": checked["check_id"],
                "item_id": checked["suggestions"][0]["item_id"],
            },
        )
        assert reused.status_code == 200 and reused.json()["outcome"] == "prevented"
        assert as_steward.get("/api/smart-create/stats").json()["prevented"] >= 1


class TestInterchangeablePartsCarryTheirApproval:
    """A probe is not an item, so no relation carries it; the decision shown
    is the one on the equivalence between the record the check found and the
    interchangeable part. Nothing on record is said as such."""

    def test_every_equivalent_says_where_its_approval_stands(self, as_steward, pipeline_run):
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import Relation

        with SessionLocal() as db:
            relation = db.execute(
                select(Relation).where(Relation.rel_type == "equivalent").limit(1)
            ).scalar_one_or_none()
            if relation is None:
                pytest.skip("no equivalence in this seed")
            from app.models import Item, RawItem

            description = db.execute(
                select(RawItem.description)
                .join(Item, Item.raw_item_id == RawItem.id)
                .where(Item.id == relation.item_a)
            ).scalar_one()
        body = as_steward.post("/api/smart-create/check", json={"description": description}).json()
        assert body["equivalents"], "the other side of the relation is interchangeable"
        for part in body["equivalents"]:
            assert part["approval"] is not None
            assert part["approval"]["status"] in ("approved", "proposed", "rejected", "none")
        on_record = [p for p in body["equivalents"] if p["approval"]["status"] != "none"]
        assert on_record, "the relation the seed planted is on record"
        assert on_record[0]["approval"]["relation_id"]


class TestTheProbeSharesThePipelinesFit:
    """A probe must be projected into the space the stored vectors live in.
    The pipeline keeps its fit; Smart-Create loads it rather than refitting,
    which is the difference between a tenth of a second and minutes on a
    small host — and, more to the point, the same space by construction."""

    def test_the_pipeline_keeps_its_fit_and_the_probe_reuses_it(self, pipeline_run, db, tmp_path):
        import time

        from sqlalchemy import select

        from app import smart_create
        from app.embed import cosine, embedder_path, unpack
        from app.models import Item

        path = embedder_path()
        assert path.exists(), "the embed stage saves its fit beside the other models"

        # Earlier tests may have added rows since the pipeline ran; the
        # pipeline's fit is still the one the stored vectors were made with.
        smart_create.reset_embedder_cache()
        started = time.time()
        embedder = smart_create.probe_embedder(db)
        assert time.time() - started < 2.0, "loaded, not refitted"

        # The same space: an item's own text projects onto its stored vector.
        item = db.execute(select(Item).where(Item.embed_vector.is_not(None)).limit(1)).scalar_one()
        probe = embedder.transform([item.norm_text])[0]
        assert cosine(probe, unpack(item.embed_vector)) > 0.999

    def test_no_saved_fit_means_a_fit(self, tmp_path):
        from app.embed import Embedder

        assert Embedder.load(tmp_path / "missing.joblib") is None
        (tmp_path / "broken.joblib").write_bytes(b"not a model")
        assert Embedder.load(tmp_path / "broken.joblib") is None


class TestABarcodeInItsOwnField:
    def test_a_scanned_gtin_anchors_the_check(self, db, pipeline_run):
        from app.models import Item

        row = db.execute(select(Item.gtin, Item.id).where(Item.gtin.isnot(None)).limit(1)).first()
        if row is None:
            pytest.skip("no item carries a GTIN")
        gtin, item_id = row
        # A description that says nothing useful; the barcode alone finds it.
        result = smart_create.check(db, "box from the store, label unreadable", gtin=gtin)
        assert result["probe"]["gtin"] == gtin
        assert any(s["item_id"] == item_id for s in result["suggestions"])

    def test_a_gtin_with_a_bad_check_digit_is_ignored(self, db, pipeline_run):
        result = smart_create.check(db, "GATE VALVE 150NB", gtin="8908440682860")
        assert result["probe"]["gtin"] is None


class TestDrafts:
    def test_a_steward_saves_a_draft_and_sees_only_their_own(
        self, as_steward, client, pipeline_run
    ):
        checked = as_steward.post(
            "/api/smart-create/check", json={"description": "BRG BALL 6205 ZZ SKF", "mpn": "6205ZZ"}
        ).json()
        saved = as_steward.post(
            "/api/smart-create/drafts",
            json={
                "description": "BRG BALL 6205 ZZ SKF",
                "mpn": "6205ZZ",
                "uom": "NOS",
                "note": "two boxes in bay 4",
                "check_id": checked["check_id"],
            },
        )
        assert saved.status_code == 200, saved.text
        draft = saved.json()
        assert draft["status"] == "draft" and draft["last_check_id"] == checked["check_id"]
        assert draft["candidates"] is not None
        mine = as_steward.get("/api/smart-create/drafts").json()["drafts"]
        assert any(d["id"] == draft["id"] for d in mine)

        # An approver sees every open draft: it is their desk.
        client.post("/api/auth/login", json={"email": "approver@min.gov.in", "password": "demo"})
        theirs = client.get("/api/smart-create/drafts").json()["drafts"]
        assert any(d["id"] == draft["id"] for d in theirs)

        # Closing it takes it off both lists.
        closed = client.patch(
            f"/api/smart-create/drafts/{draft['id']}", json={"status": "submitted"}
        )
        assert closed.status_code == 200 and closed.json()["status"] == "submitted"
        assert all(
            d["id"] != draft["id"] for d in client.get("/api/smart-create/drafts").json()["drafts"]
        )

    def test_a_viewer_has_no_drafts(self, as_viewer, pipeline_run):
        assert as_viewer.get("/api/smart-create/drafts").status_code == 403

    def test_a_bad_status_is_refused(self, as_steward, pipeline_run):
        saved = as_steward.post("/api/smart-create/drafts", json={"description": "GASKET"}).json()
        assert (
            as_steward.patch(
                f"/api/smart-create/drafts/{saved['id']}", json={"status": "lost"}
            ).status_code
            == 422
        )
        as_steward.patch(f"/api/smart-create/drafts/{saved['id']}", json={"status": "discarded"})
