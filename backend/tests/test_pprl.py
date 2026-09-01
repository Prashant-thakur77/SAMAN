"""Restricted mode — privacy-preserving record linkage (spec §5, M10)."""

import base64
import json

import pytest

from app import pprl
from app.pprl_eval import evaluate

KEY = "0123456789abcdef0123456789abcdef"


class TestEncoding:
    def test_the_same_text_under_the_same_key_encodes_identically(self):
        assert pprl.encode_text("BEARING BALL 6205 ZZ SKF", KEY) == pprl.encode_text(
            "BEARING BALL 6205 ZZ SKF", KEY
        )

    def test_a_different_key_produces_a_different_encoding(self):
        """The key is the only thing protecting these from being inverted."""
        a = pprl.encode_text("BEARING BALL 6205 ZZ SKF", KEY)
        b = pprl.encode_text("BEARING BALL 6205 ZZ SKF", "f" * 32)
        assert a != b
        assert pprl.dice(a, b) < 0.3

    def test_similar_text_encodes_similarly(self):
        a = pprl.encode_text("BEARING BALL 6205 ZZ SKF", KEY)
        b = pprl.encode_text("BEARING BALL 6205 ZZ SKF 100 C", KEY)
        assert pprl.dice(a, b) > 0.7

    def test_unrelated_text_does_not(self):
        a = pprl.encode_text("BEARING BALL 6205 ZZ SKF", KEY)
        b = pprl.encode_text("SAFETY HELMET CLASS A HDPE", KEY)
        assert pprl.dice(a, b) < 0.5

    def test_dice_is_symmetric_and_bounded(self):
        a = pprl.encode_text("VALVE GATE 80NB", KEY)
        b = pprl.encode_text("VALVE GATE 100NB", KEY)
        assert pprl.dice(a, b) == pprl.dice(b, a)
        assert 0.0 <= pprl.dice(a, b) <= 1.0
        assert pprl.dice(a, a) == 1.0

    def test_encodings_of_different_lengths_are_refused(self):
        short = pprl.encode_features(["x"], KEY, "ngram")
        long = pprl.encode_features(["x"], KEY, "attribute")
        with pytest.raises(ValueError, match="different filter lengths"):
            pprl.dice(short, long)

    def test_short_strings_still_produce_features(self):
        assert pprl.grams("A")
        assert pprl.encode_text("A", KEY) != bytes(pprl.MODES["ngram"]["bits"] // 8)

    def test_an_unknown_mode_is_refused(self):
        with pytest.raises(ValueError, match="unknown mode"):
            pprl.params("telepathy")


class TestAttributeFeatures:
    def test_internal_keys_are_excluded(self):
        """`_sources` describes how a value was read, not what the item is."""
        features = pprl.attribute_features(
            "bearing.ball.deep_groove",
            {"bore_mm": 25, "_sources": {"bore_mm": "designation"}, "brand": None},
            "SKF62052Z",
        )
        assert "bore_mm=25" in features
        assert "mpn=SKF62052Z" in features
        assert not any(f.startswith("_") for f in features)
        assert not any("None" in f for f in features)

    def test_a_bore_difference_is_a_whole_feature(self):
        """The reason attribute mode beats n-grams: 25 and 30 differ by a
        feature here, and by two characters out of seventy there."""
        a = pprl.encode_features(
            pprl.attribute_features("bearing.ball.deep_groove", {"bore_mm": 25}, None), KEY
        )
        b = pprl.encode_features(
            pprl.attribute_features("bearing.ball.deep_groove", {"bore_mm": 30}, None), KEY
        )
        assert pprl.dice(a, b) < pprl.MODES["attribute"]["threshold"]


class TestNoPlaintextLeaves:
    def test_the_payload_carries_no_description(self, db, pipeline_run):
        """The whole premise: a CPSE exchanges this and reveals nothing."""
        from sqlalchemy import select

        from app.models import Cpse, RawItem

        payload = pprl.encode_catalogue(db, "CPCL", KEY, limit=25)
        serialized = json.dumps(payload)

        cpse_id = db.execute(select(Cpse.id).where(Cpse.code == "CPCL")).scalar()
        rows = db.execute(
            select(RawItem.description, RawItem.legacy_code)
            .where(RawItem.cpse_id == cpse_id)
            .order_by(RawItem.id)
            .limit(25)
        ).all()
        for description, legacy_code in rows:
            assert legacy_code not in serialized
            for token in (description or "").split():
                if len(token) >= 5:
                    assert token not in serialized

    def test_an_encoding_carries_two_fields_and_no_others(self, db, pipeline_run):
        """Anything else on the record is something the other side learns."""
        payload = pprl.encode_catalogue(db, "CPCL", KEY, limit=25)
        assert payload["encodings"]
        for record in payload["encodings"]:
            assert set(record) == {"ref", "bloom"}
        wire = json.dumps(payload["encodings"])
        assert "price" not in wire and "qty" not in wire

    def test_a_reference_is_a_pseudonym_the_other_side_cannot_resolve(self):
        """Same row, different exchange key, different reference."""
        assert pprl.resolve(KEY, "CPCL", 42) != pprl.resolve("f" * 32, "CPCL", 42)
        assert pprl.resolve(KEY, "CPCL", 42) == pprl.resolve(KEY, "CPCL", 42)
        assert pprl.resolve(KEY, "CPCL", 42) != pprl.resolve(KEY, "IOCL", 42)

    def test_the_encoding_is_a_fixed_size_regardless_of_description_length(
        self, db, pipeline_run
    ):
        """A variable-length payload would leak description length."""
        payload = pprl.encode_catalogue(db, "CPCL", KEY, limit=50)
        sizes = {len(base64.b64decode(e["bloom"])) for e in payload["encodings"]}
        assert sizes == {payload["filter_bits"] // 8}


class TestCompare:
    def test_two_catalogues_report_their_overlap(self, db, pipeline_run):
        left = pprl.encode_catalogue(db, "CPCL", KEY, limit=120)
        right = pprl.encode_catalogue(db, "IOCL", KEY, limit=120)
        report = pprl.compare(left["encodings"], right["encodings"])
        assert report["comparisons"] == 120 * 120
        assert report["overlap_records_left"] > 0
        assert 0 <= report["overlap_pct_left"] <= 100

    def test_encodings_under_different_keys_find_nothing(self, db, pipeline_run):
        """Both sides must agree on the key, and the failure must be silent
        rather than a plausible-looking wrong answer."""
        left = pprl.encode_catalogue(db, "CPCL", KEY, limit=60)
        right = pprl.encode_catalogue(db, "IOCL", "f" * 32, limit=60)
        assert pprl.compare(left["encodings"], right["encodings"])["overlap_records_left"] == 0

    def test_a_catalogue_compared_with_itself_is_a_total_overlap(self, db, pipeline_run):
        one = pprl.encode_catalogue(db, "CPCL", KEY, limit=40)
        report = pprl.compare(one["encodings"], one["encodings"])
        assert report["overlap_pct_left"] == 100.0

    def test_weak_similarities_are_never_reported(self, db, pipeline_run):
        """A wire full of 0.3 scores is a frequency-analysis gift."""
        left = pprl.encode_catalogue(db, "CPCL", KEY, limit=60)
        right = pprl.encode_catalogue(db, "IOCL", KEY, limit=60)
        report = pprl.compare(left["encodings"], right["encodings"], limit=10_000)
        assert all(m["dice"] >= report["report_threshold"] for m in report["matches"])

    def test_an_empty_side_is_not_an_error(self, db, pipeline_run):
        left = pprl.encode_catalogue(db, "CPCL", KEY, limit=10)
        report = pprl.compare(left["encodings"], [])
        assert report["overlap_records_left"] == 0 and report["comparisons"] == 0

    def test_matches_come_back_strongest_first(self, db, pipeline_run):
        left = pprl.encode_catalogue(db, "CPCL", KEY, limit=80)
        right = pprl.encode_catalogue(db, "IOCL", KEY, limit=80)
        scores = [m["dice"] for m in pprl.compare(left["encodings"], right["encodings"])["matches"]]
        assert scores == sorted(scores, reverse=True)


class TestMeasuredCost:
    """§0.6: a privacy-preserving matcher nobody measured is a claim."""

    def test_attribute_mode_meets_the_quality_it_claims(self, db, pipeline_run):
        result = evaluate(db, "CPCL", "IOCL", mode="attribute", limit=200)
        assert result["precision"] >= 0.85
        assert result["recall"] >= 0.80

    def test_attribute_mode_beats_character_ngrams_on_this_data(self, db, pipeline_run):
        """The finding that justifies the default. If it ever stops being
        true, this test says so rather than the README quietly being wrong."""
        attribute = evaluate(db, "CPCL", "IOCL", mode="attribute", limit=200)
        ngram = evaluate(db, "CPCL", "IOCL", mode="ngram", limit=200)
        assert attribute["f1"] > ngram["f1"]

    def test_restricted_mode_costs_recall_against_the_full_matcher(
        self, db, pipeline_run
    ):
        """Honesty, not modesty: the full matcher sees attributes, units and a
        veto layer. Restricted mode sees hashes, and it shows."""
        result = evaluate(db, "CPCL", "IOCL", mode="attribute", limit=200)
        assert result["f1"] < 0.99


class TestPprlApi:
    def test_a_key_can_be_minted(self, as_steward):
        body = as_steward.get("/api/pprl/key").json()
        assert len(body["key"]) >= 32

    def test_a_steward_may_encode_their_own_catalogue(self, as_steward):
        response = as_steward.post(
            "/api/pprl/encode", json={"cpse": "CPCL", "key": KEY, "limit": 20}
        )
        assert response.status_code == 200
        assert response.json()["records"] > 0

    def test_a_steward_may_not_encode_another_cpses_catalogue(self, as_steward):
        """Restricted mode exists because CPSEs will not hand over catalogues."""
        response = as_steward.post(
            "/api/pprl/encode", json={"cpse": "IOCL", "key": KEY, "limit": 20}
        )
        assert response.status_code == 403
        assert "your own catalogue" in response.json()["detail"]

    def test_a_registrar_may_encode_any_catalogue(self, as_registrar):
        assert (
            as_registrar.post(
                "/api/pprl/encode", json={"cpse": "IOCL", "key": KEY, "limit": 20}
            ).status_code
            == 200
        )

    def test_an_unknown_cpse_is_a_400(self, as_registrar):
        assert (
            as_registrar.post(
                "/api/pprl/encode", json={"cpse": "NOPE", "key": KEY, "limit": 5}
            ).status_code
            == 400
        )

    def test_a_short_key_is_refused(self, as_steward):
        assert (
            as_steward.post(
                "/api/pprl/encode", json={"cpse": "CPCL", "key": "tooshort"}
            ).status_code
            == 422
        )

    def test_compare_touches_no_database(self, as_steward):
        left = as_steward.post(
            "/api/pprl/encode", json={"cpse": "CPCL", "key": KEY, "limit": 30}
        ).json()
        response = as_steward.post(
            "/api/pprl/compare",
            json={"left": left["encodings"], "right": left["encodings"]},
        )
        assert response.status_code == 200
        assert response.json()["overlap_pct_left"] == 100.0

    def test_the_modes_are_documented_over_the_api(self, as_steward):
        body = as_steward.get("/api/pprl/modes").json()
        assert body["default"] == "attribute"
        assert set(body["modes"]) == {"attribute", "ngram"}
        assert all(m["description"] for m in body["modes"].values())

    def test_only_a_national_role_may_read_the_measured_cost(self, as_steward):
        """The evaluation reads the ground truth, which no CPSE has.

        Identity is switched in-test rather than by taking both fixtures: they
        share one TestClient, so the second login would silently win.
        """
        assert as_steward.get("/api/pprl/evaluate?left=CPCL&right=IOCL").status_code == 403

        as_steward.post(
            "/api/auth/login",
            json={"email": "registrar@min.gov.in", "password": "demo"},
        )
        assert (
            as_steward.get("/api/pprl/evaluate?left=CPCL&right=IOCL&limit=120").status_code
            == 200
        )
