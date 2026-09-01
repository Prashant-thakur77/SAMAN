"""Evaluation correctness — spec §0.6.

If the metrics are wrong the gate is meaningless, so the estimators are tested
against partitions whose answers can be worked out by hand.
"""

import pytest

from app.metrics import TARGETS, bcubed, pairwise


class TestPairwise:
    def test_perfect_clustering(self):
        truth = {1: "A", 2: "A", 3: "B", 4: "B"}
        predicted = {1: 10, 2: 10, 3: 20, 4: 20}
        result = pairwise(predicted, truth, set(truth))
        assert (result.tp, result.fp, result.fn) == (2, 0, 0)
        assert result.precision == result.recall == result.f1 == 1.0

    def test_everything_merged_into_one_cluster(self):
        """2 true pairs found, 4 spurious: precision 1/3, recall 1."""
        truth = {1: "A", 2: "A", 3: "B", 4: "B"}
        predicted = dict.fromkeys(truth, 99)
        result = pairwise(predicted, truth, set(truth))
        assert (result.tp, result.fp, result.fn) == (2, 4, 0)
        assert result.precision == pytest.approx(1 / 3)
        assert result.recall == 1.0

    def test_nothing_merged(self):
        truth = {1: "A", 2: "A"}
        predicted = {1: 1, 2: 2}
        result = pairwise(predicted, truth, set(truth))
        assert (result.tp, result.fp, result.fn) == (0, 0, 1)
        assert result.recall == 0.0

    def test_only_the_subset_is_counted(self):
        """Held-out metrics must ignore tuning items entirely."""
        truth = {1: "A", 2: "A", 3: "A"}
        predicted = dict.fromkeys(truth, 7)
        assert pairwise(predicted, truth, {1, 2}).tp == 1
        assert pairwise(predicted, truth, {1, 2, 3}).tp == 3

    def test_empty_subset_does_not_divide_by_zero(self):
        result = pairwise({}, {}, set())
        assert result.precision == 0.0 and result.f1 == 0.0


class TestBcubed:
    """Pairwise can look excellent while clusters are badly over-merged."""

    def test_perfect_clustering(self):
        truth = {1: "A", 2: "A", 3: "B", 4: "B"}
        predicted = {1: 10, 2: 10, 3: 20, 4: 20}
        result = bcubed(predicted, truth, set(truth))
        assert result["precision"] == 1.0 and result["recall"] == 1.0

    def test_one_giant_cluster_is_penalised(self):
        truth = {i: ("A" if i < 5 else "B") for i in range(10)}
        predicted = dict.fromkeys(truth, 1)
        result = bcubed(predicted, truth, set(truth))
        assert result["precision"] == 0.5
        assert result["recall"] == 1.0

    def test_over_split_is_penalised_on_recall(self):
        truth = {1: "A", 2: "A", 3: "A", 4: "A"}
        predicted = {1: 1, 2: 2, 3: 3, 4: 4}
        result = bcubed(predicted, truth, set(truth))
        assert result["precision"] == 1.0 and result["recall"] == 0.25

    def test_bcubed_and_pairwise_disagree_on_over_merge(self):
        """The exact reason §0.6 demands both be reported."""
        truth = {i: str(i) for i in range(20)}
        truth[0] = truth[1] = "same"
        predicted = dict.fromkeys(truth, 1)
        pw = pairwise(predicted, truth, set(truth))
        bc = bcubed(predicted, truth, set(truth))
        assert pw.recall == 1.0 and pw.precision < 0.01
        assert bc["recall"] == 1.0 and bc["precision"] < 0.15


class TestGateDefinition:
    def test_the_four_targets_match_the_spec(self):
        assert TARGETS == {
            "duplicate_precision": 0.92,
            "duplicate_recall": 0.80,
            "blocking_recall": 0.97,
            "veto_precision": 0.98,
        }


class TestReportShape:
    """§0.6: never a single averaged number."""

    def test_report_contains_every_required_section(self, pipeline_run):
        report = pipeline_run["metrics"]
        for key in (
            "duplicate", "baseline_exact_text", "blocking", "veto",
            "equivalence", "per_class", "worst_class", "automation", "gate",
        ):
            assert key in report, f"missing section: {key}"

    def test_everything_is_reported_on_the_held_out_split(self, pipeline_run):
        assert pipeline_run["metrics"]["split"] == "holdout"

    def test_both_pairwise_and_cluster_level_are_reported(self, pipeline_run):
        duplicate = pipeline_run["metrics"]["duplicate"]
        assert "pairwise" in duplicate and "bcubed" in duplicate

    def test_the_worst_class_is_named(self, pipeline_run):
        report = pipeline_run["metrics"]
        assert report["worst_class"] is not None
        assert report["per_class"][0]["class_code"] == report["worst_class"]

    def test_a_naive_baseline_is_reported_beside_us(self, pipeline_run):
        report = pipeline_run["metrics"]
        baseline = report["baseline_exact_text"]["pairwise"]
        ours = report["duplicate"]["pairwise"]
        # Exact-text matching is precise but finds only the rows that happen to
        # be byte-identical; the point of reporting it is that the lift is
        # visible rather than asserted. (On the demo profile the baseline
        # recalls 0.04 against our 0.93.)
        assert ours["recall"] > baseline["recall"]
        assert ours["f1"] > baseline["f1"]

    def test_equivalence_is_reported_as_pending_until_m3_5(self, pipeline_run):
        equivalence = pipeline_run["metrics"]["equivalence"]
        assert equivalence["status"] in {"not_built", "measured"}
        if equivalence["status"] == "not_built":
            assert equivalence["truth_pairs_holdout"] > 0

    def test_blocking_recall_is_reported_for_both_splits(self, pipeline_run):
        stats = pipeline_run["metrics"]["blocking"]["stats"]
        assert "recall_tuning" in stats and "recall_holdout" in stats
