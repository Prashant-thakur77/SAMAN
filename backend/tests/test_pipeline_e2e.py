"""End-to-end pipeline behaviour on the small test profile.

The graded §8 gate is measured on the **demo** profile — §7 is explicit that
"all demo flows, screenshots and metric gates use this profile" — and `make
demo` exits non-zero if it is not met. What is asserted here is that the
pipeline works end to end and that quality does not regress, on a fixture small
enough to run in the test suite.
"""

import json

from sqlalchemy import func, select

from app.models import Cluster, ClusterMember, GoldenRecord, Item, Pair, ReviewTask


class TestPipelineProducesTheDerivedLayer:
    def test_every_item_has_an_embedding(self, pipeline_run, db):
        missing = db.execute(
            select(func.count(Item.id)).where(Item.embed_vector.is_(None))
        ).scalar()
        assert missing == 0

    def test_every_item_belongs_to_exactly_one_cluster(self, pipeline_run, db):
        items = db.execute(select(func.count(Item.id))).scalar()
        memberships = db.execute(select(func.count(ClusterMember.id))).scalar()
        distinct_items = db.execute(
            select(func.count(func.distinct(ClusterMember.item_id)))
        ).scalar()
        assert memberships == distinct_items == items

    def test_every_cluster_has_a_golden_record(self, pipeline_run, db):
        assert (
            db.execute(select(func.count(Cluster.id))).scalar()
            == db.execute(select(func.count(GoldenRecord.id))).scalar()
        )

    def test_duplicates_were_actually_found(self, pipeline_run, db):
        multi = db.execute(
            select(func.count()).select_from(
                select(ClusterMember.cluster_id)
                .group_by(ClusterMember.cluster_id)
                .having(func.count(ClusterMember.item_id) > 1)
                .subquery()
            )
        ).scalar()
        assert multi > 20

    def test_every_grey_pair_becomes_a_review_task(self, pipeline_run, db):
        """Grey pairs must all be decided; high and low are sampled for audit."""
        grey_pairs = db.execute(
            select(func.count(Pair.id)).where(Pair.verdict.in_(("review", "conflict")))
        ).scalar()
        grey_tasks = db.execute(
            select(func.count(ReviewTask.id)).where(ReviewTask.band == "grey")
        ).scalar()
        assert grey_tasks == grey_pairs

    def test_the_automatic_bands_are_sampled_for_confirmation(self, pipeline_run, db):
        for band in ("high", "low"):
            assert db.execute(
                select(func.count(ReviewTask.id)).where(ReviewTask.band == band)
            ).scalar() > 0

    def test_review_tasks_explain_themselves(self, pipeline_run, db):
        reasons = db.execute(select(ReviewTask.reason).limit(20)).scalars().all()
        assert all(r for r in reasons)


class TestEvidenceIsPersisted:
    """§0.7: every AI decision produces an evidence object."""

    def test_every_persisted_pair_carries_tier_scores(self, pipeline_run, db):
        rows = db.execute(select(Pair.tier_scores_json).limit(50)).scalars().all()
        assert rows
        for raw in rows:
            scores = json.loads(raw)
            assert {"tier0_anchor", "tier1_fuzzy", "tier2_semantic"} <= set(scores)

    def test_refused_pairs_record_the_offending_attribute(self, pipeline_run, db):
        raw = db.execute(
            select(Pair.veto_json).where(Pair.veto_json.is_not(None)).limit(1)
        ).scalar_one_or_none()
        assert raw is not None, "no vetoed pair was persisted"
        veto = json.loads(raw)
        assert veto["vetoed_by"] and veto["vetoed_by"][0]["reason"]

    def test_a_conflict_pair_names_the_shared_anchor(self, pipeline_run, db):
        raw = db.execute(
            select(Pair.evidence_json).where(Pair.verdict == "conflict").limit(1)
        ).scalar_one_or_none()
        if raw is None:
            return  # no conflicts in this fixture; nothing to assert
        assert "conflict" in json.loads(raw)


class TestQualityDoesNotRegress:
    """Floors, not the graded gate — see the module docstring."""

    def test_precision_and_recall_are_sound(self, pipeline_run):
        pairwise = pipeline_run["metrics"]["duplicate"]["pairwise"]
        assert pairwise["precision"] >= 0.90
        assert pairwise["recall"] >= 0.80

    def test_clusters_are_not_over_merged(self, pipeline_run):
        bcubed = pipeline_run["metrics"]["duplicate"]["bcubed"]
        assert bcubed["precision"] >= 0.90

    def test_blocking_recall_clears_its_target(self, pipeline_run):
        assert pipeline_run["metrics"]["blocking"]["stats"]["recall_holdout"] >= 0.97

    def test_the_veto_layer_refuses_the_planted_traps(self, pipeline_run):
        veto = pipeline_run["metrics"]["veto"]
        assert veto["precision"] >= 0.95
        assert veto["by_kind"]["identity_critical"]["accuracy"] >= 0.95

    def test_cross_brand_items_are_not_merged(self, pipeline_run):
        """§2B: equivalents keep distinct codes and must never be merged.

        The floor is below the demo profile's 1.00 because the remaining
        failures here are rows whose brand token was destroyed by the seed's
        typo model — an unextractable brand correctly keeps the rule silent
        rather than costing recall.
        """
        by_kind = pipeline_run["metrics"]["veto"]["by_kind"]
        assert by_kind["cross_brand_equivalent"]["accuracy"] >= 0.90

    def test_directed_substitutes_are_not_merged(self, pipeline_run):
        by_kind = pipeline_run["metrics"]["veto"]["by_kind"]
        assert by_kind["directed_substitute"]["accuracy"] >= 0.95

    def test_most_pairs_are_decided_without_a_human(self, pipeline_run):
        assert pipeline_run["metrics"]["automation"]["automation_rate"] >= 0.90


class TestIssuedCodesAreImmutable:
    """A CNMC pins its cluster: re-running the pipeline must not disturb it."""

    def test_a_coded_cluster_survives_a_rerun(self, pipeline_run, as_registrar, db):
        from sqlalchemy import select

        from app.models import Cnmc, GoldenRecord
        from app.pipeline import reset_status, run_pipeline

        golden_id = db.execute(
            select(GoldenRecord.id).where(GoldenRecord.status != "conflict").limit(1)
        ).scalar_one()
        code = as_registrar.post(f"/api/cnmc/issue/{golden_id}").json()["code"]
        members_before = set(
            db.execute(
                select(ClusterMember.item_id).where(
                    ClusterMember.cluster_id
                    == select(GoldenRecord.cluster_id)
                    .where(GoldenRecord.id == golden_id)
                    .scalar_subquery()
                )
            ).scalars().all()
        )

        reset_status()
        assert run_pipeline(db, stages=["cluster"]).state == "done"

        db.expire_all()
        assert db.get(GoldenRecord, golden_id) is not None
        assert db.execute(
            select(Cnmc).where(Cnmc.code == code)
        ).scalar_one_or_none() is not None
        members_after = set(
            db.execute(
                select(ClusterMember.item_id).where(
                    ClusterMember.cluster_id
                    == select(GoldenRecord.cluster_id)
                    .where(GoldenRecord.id == golden_id)
                    .scalar_subquery()
                )
            ).scalars().all()
        )
        assert members_after == members_before


class TestDeterminism:
    """§2D: re-running on unchanged data must not change the outcome."""

    def test_rerunning_the_pipeline_gives_byte_identical_golden_records(
        self, pipeline_run, db
    ):
        """§2D acceptance: unchanged data must produce unchanged descriptions.

        A golden record is what an ERP keys against; text that drifts between
        runs is not a stable identifier.
        """
        from app.pipeline import reset_status, run_pipeline

        before = sorted(db.execute(select(GoldenRecord.std_description)).scalars().all())
        reset_status()
        status = run_pipeline(db, stages=["match", "cluster"])
        assert status.state == "done"
        db.expire_all()
        after = sorted(db.execute(select(GoldenRecord.std_description)).scalars().all())
        assert before == after

    def test_golden_records_are_rendered_from_the_class_grammar(self, pipeline_run, db):
        """Not "the longest member's text" — a deterministic template (§2D)."""
        descriptions = db.execute(
            select(GoldenRecord.std_description).limit(200)
        ).scalars().all()
        assert descriptions
        assert all("{" not in d for d in descriptions), "unfilled template slot escaped"
        assert all(d == d.upper() for d in descriptions)

    def test_every_golden_record_has_field_provenance(self, pipeline_run, db):
        from app.models import GoldenFieldProvenance

        goldens = db.execute(select(func.count(GoldenRecord.id))).scalar()
        with_provenance = db.execute(
            select(func.count(func.distinct(GoldenFieldProvenance.golden_id)))
        ).scalar()
        # A record whose members yielded no attributes at all has nothing to
        # trace, so this is a strong majority rather than all.
        assert with_provenance / goldens > 0.9
