"""Tier 3 — grey-band adjudication (spec §0.4).

A recommendation, never a decision. The tests that matter here are the ones
that stop it disagreeing with the veto layer, because a tier that overrules
§2A would quietly undo the precision the rest of the engine buys.
"""

import pytest

from app import adjudicate as adj
from app.adjudicate import FLAG_CONFLICT, LEAN_MERGE, LEAN_REVIEW, LEAN_SPLIT, adjudicate


def evidence(**overrides):
    base = {
        "attributes": {
            "per_attr": [
                {"attr": "bore_mm", "role": "identity_critical", "result": "match",
                 "a": 25, "b": 25, "detail": "identical"},
                {"attr": "seal_type", "role": "identity_critical", "result": "match",
                 "a": "ZZ", "b": "ZZ", "detail": "identical"},
            ],
            "agreement": 1.0,
        },
        "identity_coverage": 1.0,
        "identity_attributes_total": 2,
        "identity_attributes_compared": 2,
        "defining_attribute": "bore_mm",
        "defining_attribute_compared": True,
    }
    base.update(overrides)
    return base


class TestItNeverContradictsTheVeto:
    def test_a_vetoed_pair_leans_split(self):
        veto = {
            "vetoed_by": [
                {"attr": "bore_mm", "role": "identity_critical", "a": 25, "b": 30,
                 "reason": "25 mm vs 30 mm"}
            ]
        }
        result = adjudicate(evidence(), {}, 0.7, "review", veto)
        assert result.recommendation == LEAN_SPLIT
        assert "bore mm" in result.summary and "25 mm vs 30 mm" in result.summary

    def test_a_veto_beats_agreeing_attributes(self):
        """The per-attribute list can look entirely agreeable while §2A has
        already refused the pair on an attribute that is not in it."""
        veto = {"vetoed_by": [{"attr": "temp_max_c", "role": "performance",
                               "reason": "outside the 10% band"}]}
        assert adjudicate(evidence(), {}, 0.9, "review", veto).recommendation == LEAN_SPLIT

    def test_further_vetoed_attributes_are_named(self):
        veto = {"vetoed_by": [
            {"attr": "bore_mm", "role": "identity_critical", "reason": "differs"},
            {"attr": "width_mm", "role": "identity_critical", "reason": "differs"},
        ]}
        result = adjudicate(evidence(), {}, 0.7, "review", veto)
        assert any("width mm" in reason for reason in result.reasons)


class TestConflict:
    def test_one_part_number_two_specifications_is_its_own_verdict(self):
        """Not a match and not something to discard — a data-quality defect."""
        result = adjudicate(
            evidence(conflict="Both rows carry MPN 6301ZZ, but their specifications disagree."),
            {"tier0_key": "mpn"},
            1.0,
            "conflict",
            {"vetoed_by": [{"attr": "temp_max_c", "reason": "100 degC vs 120 degC"}]},
        )
        assert result.recommendation == FLAG_CONFLICT
        assert "6301ZZ" in result.summary
        assert any("100 degC" in reason for reason in result.reasons)

    def test_a_conflict_outranks_agreement(self):
        result = adjudicate(evidence(), {}, 1.0, "conflict", None)
        assert result.recommendation == FLAG_CONFLICT


class TestThinEvidence:
    def test_an_unreadable_defining_attribute_holds_the_pair_back(self):
        result = adjudicate(
            evidence(defining_attribute_compared=False, defining_attribute="size_nb_mm"),
            {},
            0.85,
        )
        assert result.recommendation == LEAN_REVIEW
        assert "size nb mm" in result.summary

    def test_it_says_what_did_agree_as_well_as_what_did_not(self):
        """A reviewer needs the positive half too, or the card only argues one
        way."""
        result = adjudicate(
            evidence(defining_attribute_compared=False), {}, 0.85
        )
        assert any("agrees" in reason for reason in result.reasons)

    def test_partial_coverage_names_the_missing_attribute(self):
        thin = evidence(identity_coverage=0.5, identity_attributes_compared=1)
        thin["attributes"]["per_attr"][1]["result"] = "unknown"
        result = adjudicate(thin, {}, 0.8)
        assert result.recommendation == LEAN_REVIEW
        assert "seal type" in result.reasons[0]

    def test_confidence_rises_with_coverage(self):
        low = adjudicate(evidence(identity_coverage=0.4), {}, 0.8).confidence
        high = adjudicate(evidence(identity_coverage=0.9), {}, 0.8).confidence
        assert high > low


class TestMerge:
    def test_full_agreement_leans_merge(self):
        result = adjudicate(evidence(), {}, 0.84)
        assert result.recommendation == LEAN_MERGE
        assert "identity-critical attributes agree" in result.reasons[0]

    def test_an_anchor_key_is_worth_saying(self):
        result = adjudicate(evidence(), {"tier0_key": "mpn"}, 0.84)
        assert any("same MPN" in reason for reason in result.reasons)

    def test_cosmetic_differences_are_named_as_cosmetic(self):
        with_brand = evidence()
        with_brand["attributes"]["per_attr"].append(
            {"attr": "brand", "role": "cosmetic", "result": "mismatch",
             "a": "SKF", "b": "FAG", "detail": "differs"}
        )
        result = adjudicate(with_brand, {}, 0.84)
        assert any("cosmetic" in reason for reason in result.reasons)

    def test_it_always_says_something(self):
        result = adjudicate({"attributes": {"per_attr": []}}, {}, 0.8)
        assert result.reasons and result.summary


class TestItNeverDecides:
    def test_the_payload_says_so_explicitly(self):
        payload = adjudicate(evidence(), {}, 0.84).as_dict()
        assert payload["decides"] is False
        assert "not a decision" in payload["note"]

    def test_the_recommendation_is_deterministic_without_a_model(self):
        payload = adjudicate(evidence(), {}, 0.84).as_dict()
        assert payload["prose_by"] == "deterministic"
        assert payload["prose_note"] == "no local model configured"

    def test_the_same_evidence_always_adjudicates_the_same_way(self):
        first = adjudicate(evidence(), {"tier0_key": "mpn"}, 0.84).as_dict()
        second = adjudicate(evidence(), {"tier0_key": "mpn"}, 0.84).as_dict()
        assert first == second


class TestOllamaGuard:
    """The model rephrases; it never decides, and it never adds a fact."""

    @pytest.fixture
    def with_model(self, monkeypatch):
        from app.config import Settings, get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
        yield Settings
        get_settings.cache_clear()

    def _reply(self, monkeypatch, text):
        class Response:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"response": text}

        import httpx

        monkeypatch.setattr(httpx, "post", lambda *a, **k: Response())

    def test_a_clean_rephrasing_is_used(self, with_model, monkeypatch):
        self._reply(monkeypatch, "These look like the same bearing.")
        result = adjudicate(evidence(), {}, 0.84)
        assert result.prose_by == "ollama"
        assert result.summary == "These look like the same bearing."

    def test_an_invented_figure_is_rejected(self, with_model, monkeypatch):
        self._reply(monkeypatch, "The bore differs by 47 mm, so these differ.")
        result = adjudicate(evidence(), {}, 0.84)
        assert result.prose_by == "deterministic"
        assert "introduced figures" in result.prose_note

    def test_an_essay_is_rejected(self, with_model, monkeypatch):
        self._reply(monkeypatch, "word " * 200)
        assert adjudicate(evidence(), {}, 0.84).prose_by == "deterministic"

    def test_a_dead_model_costs_nothing(self, with_model, monkeypatch):
        import httpx

        def explode(*_a, **_k):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "post", explode)
        result = adjudicate(evidence(), {}, 0.84)
        assert result.prose_by == "deterministic"
        assert "unavailable" in result.prose_note
        assert result.summary, "the deterministic sentence must survive"

    def test_the_recommendation_is_unchanged_by_the_model(self, with_model, monkeypatch):
        self._reply(monkeypatch, "Actually these are completely different items.")
        result = adjudicate(evidence(), {}, 0.84)
        assert result.recommendation == LEAN_MERGE, "prose only, never the verdict"


class TestOnTheWorkbench:
    def test_grey_cards_carry_an_adjudication(self, as_steward, pipeline_run):
        body = as_steward.get("/api/queues?band=grey&limit=5").json()
        cards = next(v for v in body.values() if isinstance(v, list))
        assert cards, "the grey queue must not be empty"
        for card in cards:
            assert card["adjudication"]["recommendation"] in {
                LEAN_MERGE,
                LEAN_REVIEW,
                LEAN_SPLIT,
                FLAG_CONFLICT,
            }
            assert card["adjudication"]["summary"]

    def test_a_conflict_card_is_flagged_as_one(self, as_steward, pipeline_run):
        body = as_steward.get("/api/queues?band=grey&limit=40").json()
        cards = next(v for v in body.values() if isinstance(v, list))
        conflicts = [c for c in cards if c["verdict"] == "conflict"]
        for card in conflicts:
            assert card["adjudication"]["recommendation"] == FLAG_CONFLICT

    def test_the_other_bands_are_not_adjudicated(self, as_steward, pipeline_run):
        """Tier 3 exists for the band a human is about to look at."""
        body = as_steward.get("/api/queues?band=high&limit=3").json()
        cards = next(v for v in body.values() if isinstance(v, list))
        assert all(card["adjudication"] is None for card in cards)

    def test_the_module_names_its_own_recommendations(self):
        assert set(adj.HEADLINE) == {LEAN_MERGE, LEAN_REVIEW, LEAN_SPLIT, FLAG_CONFLICT}
