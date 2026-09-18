"""The executive dashboard's eight explanatory sections — spec §6.7, extended.

Every test here is a reconciliation: a section's numbers must add up to the
KPI row, to the donut, to the run record or to the function the tile already
uses, because a chart that does not reconcile with the number beside it is
worse than no chart. The not-recorded states are tested too: a database whose
latest run predates the run-time counters must still answer, honestly.
"""

import math
from datetime import timedelta
from itertools import pairwise

import pytest
from sqlalchemy import delete, func, select

from app import analytics, inventory, opportunity, quality
from app.match import T_HIGH, T_LOW
from app.metrics import TARGETS
from app.models import (
    Cluster,
    ClusterMember,
    Cnmc,
    Cpse,
    Decision,
    GoldenRecord,
    Item,
    MatchRun,
    Pair,
    RawItem,
    ReviewTask,
    Stock,
)
from app.pipeline import LOW_BAND_SAMPLE
from app.review import BAND_ROLES, CONFLICT_ROLES
from app.visibility import Scope

REGISTRAR = Scope("registrar", None)
CPCL_STEWARD = Scope("steward", "CPCL")

SECTIONS = (
    "by_class",
    "by_cpse_count",
    "pipeline",
    "veto_attributes",
    "held_for_review",
    "evaluation",
    "savings_ladder",
    "stock_age",
)


@pytest.fixture
def body(client, pipeline_run):
    return client.get("/api/dashboard/executive").json()


def _part(parts, key):
    return next(p for p in parts if p["key"] == key)


def _rung(rungs, key):
    return next(r for r in rungs if r["key"] == key)


class TestEndpoint:
    def test_the_eight_sections_are_present_for_every_role(
        self, as_registrar, as_steward, pipeline_run
    ):
        for client in (as_registrar, as_steward):
            body = client.get("/api/dashboard/executive").json()
            assert set(SECTIONS) <= set(body)

    def test_no_new_section_carries_an_attributed_price(self, as_steward, pipeline_run):
        """§0.9b: the sections carry totals, never one CPSE's rupees."""
        body = as_steward.get("/api/dashboard/executive").json()
        assert body["visibility"]["sees_attributed_prices"] is False

        def keys(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    yield k
                    yield from keys(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from keys(v)

        for section in SECTIONS:
            assert not {"unit_price", "unit_value", "price"} & set(keys(body[section]))

    def test_a_steward_and_a_registrar_read_the_same_totals(
        self, as_registrar, as_steward, pipeline_run
    ):
        registrar = as_registrar.get("/api/dashboard/executive").json()
        steward = as_steward.get("/api/dashboard/executive").json()
        for section in SECTIONS:
            assert registrar[section] == steward[section], section


class TestByClass:
    def test_each_row_is_partitioned_into_the_three_parts(self, pipeline_run, db):
        for row in analytics.by_class(db)["rows"]:
            assert row["coded"] + row["duplicate_pending"] + row["unique_pending"] == row["rows"]
            assert 0.0 <= row["coded_share"] <= 1.0

    def test_the_rows_sum_to_the_catalogue(self, body, db):
        rows = body["by_class"]["rows"]
        kpis = {k["key"]: k["value"] for k in body["kpis"]}
        assert sum(r["rows"] for r in rows) == kpis["items"]
        assert sum(r["rows"] for r in rows) == db.execute(select(func.count(Item.id))).scalar()

    def test_the_family_bars_sum_to_the_donut(self, body):
        """The donut and the family bars apply one rule per row, so they agree exactly."""
        rows = body["by_class"]["rows"]
        donut = body["harmonisation"]
        for key in ("coded", "duplicate_pending", "unique_pending"):
            assert sum(r[key] for r in rows) == _part(donut["parts"], key)["value"]
        assert sum(p["value"] for p in donut["parts"]) == donut["total"]
        assert [p["key"] for p in body["by_class"]["parts"]] == [p["key"] for p in donut["parts"]]
        assert [p["label"] for p in body["by_class"]["parts"]] == [
            p["label"] for p in donut["parts"]
        ]

    def test_every_class_appears_exactly_once(self, pipeline_run, db):
        rows = analytics.by_class(db)["rows"]
        classes = [r["class_code"] for r in rows]
        assert len(classes) == len(set(classes))
        assert set(classes) == set(db.execute(select(Item.class_code).distinct()).scalars())

    def test_rows_are_sorted_by_coded_share_then_size(self, pipeline_run, db):
        rows = analytics.by_class(db)["rows"]
        assert rows == sorted(rows, key=lambda r: (-r["coded_share"], -r["rows"], r["class_code"]))

    def test_issuing_a_code_moves_its_cluster_into_the_coded_part(
        self, as_registrar, pipeline_run, db
    ):
        golden_id, cluster_id = db.execute(
            select(GoldenRecord.id, GoldenRecord.cluster_id)
            .join(ClusterMember, ClusterMember.cluster_id == GoldenRecord.cluster_id)
            .outerjoin(Cnmc, Cnmc.golden_id == GoldenRecord.id)
            .where(GoldenRecord.status == "draft", Cnmc.id.is_(None))
            .group_by(GoldenRecord.id)
            .having(func.count(ClusterMember.id) >= 2)
            .limit(1)
        ).one()
        members = db.execute(
            select(func.count(ClusterMember.id)).where(ClusterMember.cluster_id == cluster_id)
        ).scalar()
        before = analytics.by_class(db)
        r = as_registrar.post(f"/api/cnmc/issue/{golden_id}")
        assert r.status_code == 200, r.text
        code = r.json()["code"]
        # The API committed on its own session; end this one's read
        # transaction so it sees the issued code rather than its snapshot.
        db.rollback()
        after = analytics.by_class(db)
        coded_before = sum(r["coded"] for r in before["rows"])
        coded_after = sum(r["coded"] for r in after["rows"])
        assert coded_after == coded_before + members
        class_code = db.execute(
            select(Item.class_code)
            .join(ClusterMember, ClusterMember.item_id == Item.id)
            .where(ClusterMember.cluster_id == cluster_id)
            .limit(1)
        ).scalar()
        row = next(r for r in after["rows"] if r["class_code"] == class_code)
        assert row["family"] == code[:4]

    def test_a_family_is_the_prefix_most_of_the_class_carries(self, as_registrar, pipeline_run, db):
        """A cluster can hold a stray row of another class; its code must not
        rename the family (MIN() once labelled valves MISC)."""
        for golden_id in db.execute(
            select(GoldenRecord.id)
            .outerjoin(Cnmc, Cnmc.golden_id == GoldenRecord.id)
            .where(GoldenRecord.status == "draft", Cnmc.id.is_(None))
            .limit(12)
        ).scalars():
            assert as_registrar.post(f"/api/cnmc/issue/{golden_id}").status_code == 200
        db.expire_all()
        rows = {r["class_code"]: r for r in analytics.by_class(db)["rows"]}
        prefixes = db.execute(
            select(Item.class_code, func.substr(Cnmc.code, 1, 4), func.count())
            .join(GoldenRecord, GoldenRecord.id == Cnmc.golden_id)
            .join(ClusterMember, ClusterMember.cluster_id == GoldenRecord.cluster_id)
            .join(Item, Item.id == ClusterMember.item_id)
            .group_by(Item.class_code, func.substr(Cnmc.code, 1, 4))
        ).all()
        by_class: dict[str, dict[str, int]] = {}
        for class_code, prefix, n in prefixes:
            by_class.setdefault(class_code, {})[prefix] = n
        assert by_class, "the fixture issues codes"
        for class_code, counts in by_class.items():
            assert rows[class_code]["family"] == max(counts, key=counts.get)

    def test_the_note_states_the_rule_and_the_conflicts(self, pipeline_run, db):
        note = analytics.by_class(db)["note"]
        assert "donut's rule applied per class" in note
        conflicts = db.execute(
            select(func.count(GoldenRecord.id)).where(GoldenRecord.status == "conflict")
        ).scalar()
        assert f"({conflicts:,})" in note


class TestByCpseCount:
    def test_materials_and_rows_sum_to_the_cluster_tables(self, pipeline_run, db):
        result = analytics.by_cpse_count(db)
        assert (
            sum(r["materials"] for r in result["rows"])
            == db.execute(select(func.count(Cluster.id))).scalar()
        )
        assert (
            sum(r["rows"] for r in result["rows"])
            == db.execute(select(func.count(ClusterMember.id))).scalar()
        )

    def test_multi_counts_are_the_clusters_two_or_more_cpses_describe(self, pipeline_run, db):
        result = analytics.by_cpse_count(db)
        per_cluster = db.execute(
            select(func.count(func.distinct(RawItem.cpse_id)))
            .select_from(ClusterMember)
            .join(Item, Item.id == ClusterMember.item_id)
            .join(RawItem, RawItem.id == Item.raw_item_id)
            .group_by(ClusterMember.cluster_id)
        ).scalars()
        assert result["multi_materials"] == sum(1 for k in per_cluster if k >= 2)
        singles = result["rows"][0]
        assert singles["cpses"] == 1
        assert result["multi_rows"] + singles["rows"] == sum(r["rows"] for r in result["rows"])

    def test_internal_duplicates_are_rows_beyond_one_per_cpse(self, pipeline_run, db):
        result = analytics.by_cpse_count(db)
        independent = sum(r["rows"] for r in result["rows"]) - sum(
            r["materials"] * r["cpses"] for r in result["rows"]
        )
        assert result["internal_duplicate_rows"] == independent >= 0

    def test_rows_are_contiguous_from_one_and_the_cpses_reconcile(self, pipeline_run, db):
        result = analytics.by_cpse_count(db)
        assert [r["cpses"] for r in result["rows"]] == list(range(1, result["cpses_with_rows"] + 1))
        assert (
            result["cpses_with_rows"] + len(result["cpses_empty"])
            == db.execute(select(func.count(Cpse.id))).scalar()
        )


class TestPipelineLadder:
    def test_the_ladder_reconciles_with_the_run_record(self, body, db):
        ladder = body["pipeline"]
        run = analytics.latest_run(db)
        bands = run.stats["bands"]
        kpis = {k["key"]: k["value"] for k in body["kpis"]}
        rungs = ladder["rungs"]
        assert _rung(rungs, "possible")["value"] == math.comb(kpis["items"], 2)
        candidates = _rung(rungs, "candidates")["value"]
        assert candidates == run.stats["blocking"]["candidate_pairs"]
        assert candidates == sum(p["added"] for p in ladder["blocking"]["passes"])
        assert candidates == bands["high"] + bands["grey"] + bands["low"]
        close = _rung(rungs, "close")
        assert close["value"] == bands["high"] + bands["grey"]
        assert close["aside"]["value"] == bands["low"]
        merged = _rung(rungs, "merged")
        assert merged["value"] == bands["high"]
        assert merged["aside"]["value"] == bands["grey"] == body["held_for_review"]["total"]
        multi = db.execute(
            select(func.count()).select_from(
                select(ClusterMember.cluster_id)
                .group_by(ClusterMember.cluster_id)
                .having(func.count() > 1)
                .subquery()
            )
        ).scalar()
        assert _rung(rungs, "materials")["value"] == multi
        assert _rung(rungs, "codes")["value"] == kpis["cnmcs"]

    def test_values_fall_and_factors_follow_the_units(self, body):
        rungs = body["pipeline"]["rungs"]
        values = [r["value"] for r in rungs]
        assert values == sorted(values, reverse=True)
        for i, rung in enumerate(rungs):
            if i == 0 or rungs[i - 1]["unit"] != rung["unit"]:
                assert rung["factor_from_previous"] is None
            else:
                assert rung["factor_from_previous"] == pytest.approx(
                    rungs[i - 1]["value"] / rung["value"], abs=0.05
                )

    def test_the_passes_keep_their_execution_order(self, body):
        from app.blocking import PASSES

        names = [p["pass"] for p in body["pipeline"]["blocking"]["passes"]]
        order = [name for name, _ in PASSES]
        assert names == [name for name in order if name in names]

    def test_without_a_run_the_section_is_null_and_the_page_still_answers(
        self, client, pipeline_run, monkeypatch
    ):
        monkeypatch.setattr(analytics, "latest_run", lambda db: None)
        response = client.get("/api/dashboard/executive")
        assert response.status_code == 200
        body = response.json()
        assert body["pipeline"] is None
        assert body["evaluation"] is None
        assert body["veto_attributes"]["source"] == "stored_pairs"


class TestVetoAttributes:
    def test_bars_are_distinct_pairs_and_the_strip_accounts_for_all_of_them(self, body):
        section = body["veto_attributes"]
        total = section["pairs_with_veto"]
        assert all(row["pairs"] <= total for row in section["by_attribute"])
        assert sum(s["pairs"] for s in section["attrs_per_pair"]) == total
        assert sum(s["n"] * s["pairs"] for s in section["attrs_per_pair"]) == (
            sum(row["pairs"] for row in section["by_attribute"]) + section["other"]["pairs"]
        )

    def test_cosmetic_attributes_never_appear(self, body):
        section = body["veto_attributes"]
        assert "brand" in section["cosmetic_never_vetoes"]
        for row in section["by_attribute"]:
            assert row["attr"] not in section["cosmetic_never_vetoes"]
            assert row["role"] in {"identity_critical", "performance"}
            assert row["label"]

    def test_the_top_ten_are_sorted_by_pairs(self, body):
        rows = body["veto_attributes"]["by_attribute"]
        assert len(rows) <= 10
        assert [r["pairs"] for r in rows] == sorted((r["pairs"] for r in rows), reverse=True)

    def test_a_full_run_records_the_counter_over_every_pair(self, body, db):
        section = body["veto_attributes"]
        assert section["source"] == "run"
        conflicts = db.execute(
            select(func.count(Pair.id)).where(Pair.verdict == "conflict")
        ).scalar()
        assert section["coverage"]["conflict"] == conflicts
        assert section["coverage"]["refused_total"] == analytics.latest_run(db).stats["bands"].get(
            "low", 0
        )
        assert section["coverage"]["refused"] <= section["coverage"]["refused_total"]

    def test_the_stored_pairs_fallback_agrees_with_the_run_where_both_can_see(
        self, pipeline_run, db
    ):
        """Conflicts always keep their evidence, so the fallback must count them
        exactly; refusals mostly do not, so the run can only count more."""
        run = analytics.latest_run(db)
        recorded = run.stats["veto_attributes"]
        stored = analytics._stored_tally(db).as_stats()
        assert stored["veto_attributes"]["conflict"] == recorded["conflict"]
        assert stored["held_for_review"]["conflict"] == run.stats["held_for_review"]["conflict"]
        assert stored["veto_attributes"]["refused"] <= recorded["refused"]
        for attr, entry in stored["veto_attributes"]["by_attribute"].items():
            assert entry["pairs"] <= recorded["by_attribute"][attr]["pairs"]
            assert entry["role"] == recorded["by_attribute"][attr]["role"]

    def test_the_fallback_conflict_split_matches_an_independent_parse(self, pipeline_run, db):
        import json

        stored = analytics._stored_tally(db).as_stats()
        identity = 0
        for veto_json in db.execute(
            select(Pair.veto_json).where(Pair.verdict == "conflict", Pair.veto_json.is_not(None))
        ).scalars():
            vetoed_by = json.loads(veto_json)["vetoed_by"]
            identity += any(v["role"] == "identity_critical" for v in vetoed_by)
        assert stored["held_for_review"]["conflict"]["identity_critical"] == identity
        fallback = analytics.veto_attributes(db, None)
        assert fallback["source"] == "stored_pairs"
        assert fallback["coverage"]["conflict"] == stored["veto_attributes"]["conflict"]


class TestHeldForReview:
    def test_the_two_reasons_sum_to_the_grey_band(self, body, db):
        section = body["held_for_review"]
        bands = analytics.latest_run(db).stats["bands"]
        conflict, review = section["reasons"]
        assert conflict["key"] == "conflict" and review["key"] == "review"
        assert conflict["pairs"] + review["pairs"] == section["total"] == bands.get("grey", 0)
        assert section["total"] == _rung(body["pipeline"]["rungs"], "merged")["aside"]["value"]

    def test_the_conflict_parts_are_disjoint(self, body):
        conflict = body["held_for_review"]["reasons"][0]
        identity, performance = conflict["parts"]
        assert identity["key"] == "identity_critical" and identity["equivalence_flagged"] is None
        assert performance["key"] == "performance_only"
        assert identity["pairs"] + performance["pairs"] == conflict["pairs"]
        assert performance["equivalence_flagged"] <= performance["pairs"]

    def test_confidence_ranges_sit_where_the_thresholds_say(self, body):
        section = body["held_for_review"]
        assert section["thresholds"] == {"t_low": T_LOW, "t_high": T_HIGH}
        conflict, review = section["reasons"]
        if conflict["pairs"]:
            # An anchor-key conflict is certain of the words: confidence is the anchor's.
            assert conflict["confidence"]["min"] == conflict["confidence"]["max"] == 1.0
        if review["pairs"]:
            assert T_LOW <= review["confidence"]["min"] <= review["confidence"]["max"] < T_HIGH

    def test_owner_roles_come_from_the_review_module(self, body):
        conflict, review = body["held_for_review"]["reasons"]
        assert conflict["owner_roles"] == list(CONFLICT_ROLES)
        assert review["owner_roles"] == list(BAND_ROLES["grey"])

    def test_the_other_queues_are_labelled_for_what_they_are(self, body, db):
        high, low = body["held_for_review"]["also_queued"]
        assert high["band"] == "high" and high["disposition"] == "policy"
        assert low["band"] == "low" and low["disposition"] == "audit_sample"
        assert low["sample_of"] == analytics.latest_run(db).stats["bands"].get("low", 0)
        assert low["pending"] <= LOW_BAND_SAMPLE
        high_tasks = db.execute(
            select(func.count(ReviewTask.id)).where(ReviewTask.band == "high")
        ).scalar()
        assert high["pending"] + high["done"] == high_tasks
        evaluation = body["evaluation"]
        assert high["evidence"]["split"] == "holdout"
        assert high["evidence"]["duplicate_precision"] == (
            _rung(evaluation["rows"], "precision")["value"] if evaluation else None
        )

    def test_decisions_reconcile_with_the_review_block(self, body, db):
        decisions = body["held_for_review"]["decisions"]
        assert decisions["total"] == sum(decisions["by_action"].values())
        assert decisions["total"] == body["review"]["decisions_made"]
        assert decisions["total"] == db.execute(select(func.count(Decision.id))).scalar()
        assert set(body["held_for_review"]["labels"]) == {"reviewer", "simulated"}


class TestEvaluation:
    def test_a_full_pipeline_run_writes_the_snapshot_on_its_run(self, pipeline_run, db):
        run = analytics.latest_run(db)
        snapshot = run.stats["evaluation"]
        assert snapshot["computed_at"] and snapshot["split"] == "holdout"

    def test_the_rows_are_read_from_the_snapshot_never_recomputed(self, body, db):
        section = body["evaluation"]
        snapshot = analytics.latest_run(db).stats["evaluation"]
        assert section["run_id"] == analytics.latest_run(db).id
        assert section["computed_at"] == snapshot["computed_at"]
        rows = {r["key"]: r for r in section["rows"]}
        assert rows["precision"]["value"] == snapshot["duplicate"]["pairwise"]["precision"]
        assert rows["recall"]["baseline"] == snapshot["baseline_exact_text"]["pairwise"]["recall"]
        assert rows["veto_precision"]["target"] == TARGETS["veto_precision"]
        assert rows["blocking_recall"]["target"] == TARGETS["blocking_recall"]
        for row in section["rows"]:
            assert 0.0 <= row["value"] <= 1.0
            if row["target"] is None:
                assert row["pass"] is None
            else:
                assert row["pass"] == (row["value"] >= row["target"])
        assert section["decisions_since"] >= 0
        assert section["items_holdout"] == snapshot["counts"]["items_holdout"]

    def test_the_weakest_class_is_named_and_first(self, body):
        section = body["evaluation"]
        f1s = [r["f1"] for r in section["per_class"]]
        assert f1s == sorted(f1s)
        if section["per_class"]:
            assert section["per_class"][0]["class_code"] == section["worst_class"]

    def test_without_a_snapshot_the_section_is_null_not_a_constant(
        self, client, pipeline_run, db, monkeypatch
    ):
        run = analytics.latest_run(db)
        older = analytics.Run(
            run.id, run.ts, {k: v for k, v in run.stats.items() if k != "evaluation"}
        )
        monkeypatch.setattr(analytics, "latest_run", lambda db: older)
        response = client.get("/api/dashboard/executive")
        assert response.status_code == 200
        body = response.json()
        assert body["evaluation"] is None
        assert body["held_for_review"]["also_queued"][0]["evidence"]["duplicate_precision"] is None
        assert body["pipeline"] is not None

    def test_a_run_over_data_with_no_planted_truth_has_no_scorecard(
        self, client, pipeline_run, db, monkeypatch
    ):
        """A CPSE's own upload carries no truth groups. The snapshot then scores
        nothing against nothing, and the honest section is none at all — never
        precision 0.0 and a failed gate for a matcher that was not measured."""
        run = analytics.latest_run(db)
        snapshot = dict(run.stats["evaluation"])
        snapshot["counts"] = {**snapshot["counts"], "truth_groups_holdout": 0, "items_holdout": 0}
        untested = analytics.Run(run.id, run.ts, {**run.stats, "evaluation": snapshot})
        monkeypatch.setattr(analytics, "latest_run", lambda db: untested)
        body = client.get("/api/dashboard/executive").json()
        assert body["evaluation"] is None

    def test_the_cli_records_a_fresh_snapshot_without_reseeding(self, pipeline_run, db):
        from app.cli import main

        before = analytics.latest_run(db).stats["evaluation"]["computed_at"]
        assert main(["evaluate"]) == 0
        db.expire_all()
        after = analytics.latest_run(db).stats["evaluation"]["computed_at"]
        assert after >= before
        assert db.execute(select(func.count(MatchRun.id))).scalar() >= 1


class TestSavingsLadder:
    def test_the_bottom_rung_is_the_savings_kpi(self, body):
        ladder = body["savings_ladder"]
        kpi = next(k for k in body["kpis"] if k["key"] == "savings")
        estimate = _rung(ladder["rungs"], "estimate")
        assert estimate["value_inr"] == kpi["value"]
        assert estimate["assumption"] == kpi["note"] == ladder["assumption_note"]
        assert "capturable" in ladder["assumption_note"]

    def test_the_estimate_is_the_ceiling_at_the_stated_capture(self, body):
        ladder = body["savings_ladder"]
        ceiling = _rung(ladder["rungs"], "ceiling")
        estimate = _rung(ladder["rungs"], "estimate")
        shared = _rung(ladder["rungs"], "shared")
        # Each candidate's estimate is rounded to the paisa before summing.
        assert estimate["value_inr"] == pytest.approx(
            ceiling["value_inr"] * ladder["capture"], abs=0.01 * max(shared["materials"], 1)
        )
        sensitivity = estimate["sensitivity"]
        assert sensitivity["capture_low"] == 0.4 and sensitivity["capture_high"] == 0.8
        assert sensitivity["value_low_inr"] == pytest.approx(ceiling["value_inr"] * 0.4, rel=1e-6)
        assert sensitivity["value_high_inr"] == pytest.approx(ceiling["value_inr"] * 0.8, rel=1e-6)

    def test_rungs_fall_and_shares_are_ratios(self, body, db):
        rungs = body["savings_ladder"]["rungs"]
        values = [r["value_inr"] for r in rungs]
        assert values == sorted(values, reverse=True) and all(v >= 0 for v in values)
        assert rungs[0]["share_of_previous"] is None
        for previous, rung in pairwise(rungs):
            assert rung["share_of_previous"] == pytest.approx(
                rung["value_inr"] / previous["value_inr"], abs=1e-3
            )
        assert (
            _rung(rungs, "shared")["materials"]
            == opportunity.joint_tender_candidates(db, REGISTRAR)["candidates_found"]
        )

    def test_modelled_rungs_carry_their_assumption(self, body):
        rungs = body["savings_ladder"]["rungs"]
        for key in ("ceiling", "estimate"):
            assert _rung(rungs, key)["assumption"]
        for key in ("spend", "shared"):
            assert _rung(rungs, key)["assumption"] is None

    def test_an_empty_window_gives_zero_rungs_that_still_validate(self, pipeline_run, db):
        ladder = analytics.savings_ladder(db, REGISTRAR, purchases=[])
        assert [r["key"] for r in ladder["rungs"]] == ["spend", "shared", "ceiling", "estimate"]
        assert all(r["value_inr"] == 0 for r in ladder["rungs"])
        assert all(r["share_of_previous"] is None for r in ladder["rungs"])

    def test_the_ladder_carries_no_cpse_attribution_so_a_steward_sees_the_same(
        self, pipeline_run, db
    ):
        purchases = opportunity.load_purchases(db)
        assert analytics.savings_ladder(db, REGISTRAR, purchases) == analytics.savings_ladder(
            db, CPCL_STEWARD, purchases
        )


class TestStockAge:
    def test_the_rules_are_read_from_the_modules_that_apply_them(self, body):
        section = body["stock_age"]
        assert section["rule_months"] == inventory.DEAD_STOCK_MONTHS
        assert section["quality_stale_months"] == quality.STALE_MONTHS
        assert section["demand_window_months"] == opportunity.WINDOW_MONTHS

    def test_the_idle_bins_are_the_dead_stock_tile(self, body, db):
        section = body["stock_age"]
        dead = inventory.dead_stock(db, REGISTRAR, limit=1)
        idle_bins = [b for b in section["bins"] if b["idle"]]
        assert sum(b["value_inr"] for b in idle_bins) == pytest.approx(
            dead["total_value"], abs=0.05
        )
        assert section["idle"]["value_inr"] == pytest.approx(
            body["inventory"]["dead_stock_value"], abs=0.05
        )
        assert section["idle"]["materials"] == dead["materials_found"]
        stale_before = inventory._cutoff(inventory.DEAD_STOCK_MONTHS)
        idle_positions = db.execute(
            select(func.count(Stock.id))
            .join(ClusterMember, ClusterMember.item_id == Stock.item_id)
            .where(Stock.qty_on_hand > 0, Stock.last_movement_date < stale_before)
        ).scalar()
        assert section["idle"]["positions"] == sum(b["positions"] for b in idle_bins)
        assert section["idle"]["positions"] == idle_positions

    def test_every_bin_splits_into_demand_elsewhere_and_none(self, body, db):
        section = body["stock_age"]
        for entry in section["bins"]:
            assert entry["demand_elsewhere_value_inr"] + entry[
                "no_demand_value_inr"
            ] == pytest.approx(entry["value_inr"], abs=0.01)
            assert entry["materials"] <= entry["positions"]
        assert section["idle"]["demand_elsewhere_materials"] <= section["idle"]["materials"]
        assert (
            sum(b["positions"] for b in section["bins"]) + section["excluded_positions"]
            == inventory.stock_totals(db)["positions"]
        )

    def test_six_contiguous_bins_with_the_rule_edge_among_them(self, body):
        bins = body["stock_age"]["bins"]
        assert len(bins) == 6
        assert bins[0]["from_months"] == 0 and bins[-1]["to_months"] is None
        for previous, entry in pairwise(bins):
            assert previous["to_months"] == entry["from_months"]
        assert [b["idle"] for b in bins] == [
            b["from_months"] >= body["stock_age"]["rule_months"] for b in bins
        ]
        assert bins[-1]["label"].endswith("+")

    def test_a_position_at_the_cutoff_lands_where_dead_stock_puts_it(self, pipeline_run, db):
        item_id, cpse_id = db.execute(
            select(Item.id, RawItem.cpse_id)
            .join(RawItem, RawItem.id == Item.raw_item_id)
            .join(ClusterMember, ClusterMember.item_id == Item.id)
            .limit(1)
        ).one()
        cutoff = inventory._cutoff(inventory.DEAD_STOCK_MONTHS)
        purchases = opportunity.load_purchases(db)
        before = analytics.stock_age(db, purchases)
        rows = [
            Stock(
                item_id=item_id,
                cpse_id=cpse_id,
                plant="EDGE",
                qty_on_hand=1.0,
                reserved_qty=0.0,
                last_movement_date=cutoff,
                unit_value=1.0,
            ),
            Stock(
                item_id=item_id,
                cpse_id=cpse_id,
                plant="EDGE-1",
                qty_on_hand=1.0,
                reserved_qty=0.0,
                last_movement_date=cutoff - timedelta(days=1),
                unit_value=1.0,
            ),
        ]
        db.add_all(rows)
        db.commit()
        try:
            after = analytics.stock_age(db, purchases)
            # dead_stock keeps a row moved *on* the cutoff day; only the day
            # before is idle. The bins draw the same line.
            assert after["idle"]["positions"] == before["idle"]["positions"] + 1
            just_inside = next(
                b for b in after["bins"] if b["to_months"] == inventory.DEAD_STOCK_MONTHS
            )
            was = next(b for b in before["bins"] if b["to_months"] == inventory.DEAD_STOCK_MONTHS)
            assert just_inside["positions"] == was["positions"] + 1
        finally:
            db.execute(delete(Stock).where(Stock.plant.in_(["EDGE", "EDGE-1"])))
            db.commit()
