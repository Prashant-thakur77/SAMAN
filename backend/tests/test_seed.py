"""Seed generator and ground-truth invariants — spec §7, §0.6.

These are the tests that protect the M3 metric gate: if the generated ground
truth is inconsistent or unlearnable, no matcher can hit the targets and the
numbers would be meaningless.
"""

import collections
import itertools
import json

from sqlalchemy import func, select

from app.models import (
    Crossref,
    Item,
    PurchaseHistory,
    RawItem,
    SubstitutionRule,
    TruthEquivalence,
    TruthGroup,
    TruthTrap,
)
from app.seed import CLASS_SPACES, HOLDOUT_FRACTION, allocate, class_capacity
from app.taxonomy import get_schema


class TestSeedShape:
    def test_every_cpse_and_user_is_created(self, seeded):
        # Counted at seed time: the onboarding and admin tests add CPSEs and
        # users to the same database, so a later count would be order-dependent.
        assert seeded["cpses_at_seed"] == seeded["cpses"]
        assert seeded["users_at_seed"] == 8  # incl. the engineer

    def test_every_raw_row_produced_an_item(self, seeded):
        assert seeded["raw_items"] == seeded["items"]
        assert seeded["orphan_raw_items"] == 0

    def test_commercial_and_inventory_facts_exist(self, db, seeded):
        assert db.execute(select(func.count(PurchaseHistory.id))).scalar() > 0
        assert seeded["stock"] == seeded["raw_items"]

    def test_crossrefs_and_substitution_rules_are_seeded(self, db, seeded):
        assert db.execute(select(func.count(Crossref.id))).scalar() > 0
        assert db.execute(select(func.count(SubstitutionRule.id))).scalar() > 0

    def test_seeding_is_reproducible(self, db, seeded):
        """§2D determinism depends on the generator being deterministic."""
        descriptions = db.execute(
            select(RawItem.description).order_by(RawItem.id).limit(20)
        ).scalars().all()
        assert descriptions == db.execute(
            select(RawItem.description).order_by(RawItem.id).limit(20)
        ).scalars().all()


class TestCorruptionModel:
    """§7: the style profiles must actually corrupt the descriptions."""

    def test_descriptions_vary_between_cpses(self, db, seeded):
        groups = collections.defaultdict(list)
        for gid, desc in db.execute(
            select(TruthGroup.group_id, RawItem.description).join(
                RawItem, RawItem.id == TruthGroup.raw_item_id
            )
        ).all():
            groups[gid].append(desc)
        multi = [v for v in groups.values() if len(v) > 1]
        assert multi, "no product was rendered into more than one catalogue"
        varied = sum(1 for v in multi if len(set(v)) > 1)
        assert varied / len(multi) > 0.9

    def test_hindi_mix_is_present(self, db, seeded):
        total = db.execute(select(func.count(Item.id))).scalar()
        hindi = db.execute(select(func.count(Item.id)).where(Item.lang == "hi")).scalar()
        assert 0.03 < hindi / total < 0.20

    def test_mpn_coverage_is_around_sixty_percent(self, db, seeded):
        total = db.execute(select(func.count(Item.id))).scalar()
        with_mpn = db.execute(
            select(func.count(Item.id)).where(Item.mpn_norm.isnot(None))
        ).scalar()
        assert 0.45 < with_mpn / total < 0.75

    def test_pack_basis_variation_exists(self, db, seeded):
        assert db.execute(select(func.count(Item.id)).where(Item.pack_qty > 1)).scalar() > 0


class TestGroundTruth:
    def test_every_raw_row_has_a_truth_group(self, seeded):
        assert seeded["raw_without_truth"] == 0

    def test_duplicate_pairs_exist_to_be_found(self, db, seeded):
        sizes = collections.Counter(
            db.execute(select(TruthGroup.group_id)).scalars().all()
        )
        assert sum(1 for n in sizes.values() if n > 1) > 50

    def test_holdout_split_is_close_to_forty_percent(self, db, seeded):
        """§0.6: thresholds are tuned on 60%, every reported number is the 40%."""
        splits = collections.Counter(
            db.execute(select(TruthGroup.split)).scalars().all()
        )
        share = splits["holdout"] / sum(splits.values())
        assert abs(share - HOLDOUT_FRACTION) < 0.08

    def test_a_group_never_straddles_the_split(self, db, seeded):
        by_group = collections.defaultdict(set)
        for gid, split in db.execute(
            select(TruthGroup.group_id, TruthGroup.split)
        ).all():
            by_group[gid].add(split)
        assert all(len(s) == 1 for s in by_group.values())


class TestPlantedTraps:
    """§2A / §7: the traps veto precision is measured against."""

    def test_every_planted_trap_survives_seeding(self, seeded):
        """Traps are reserved before the general population takes the space.

        Planted afterwards they compete for the last free combinations and
        silently fail, leaving veto precision measured against almost nothing.
        """
        assert seeded["trap_products"] == 400

    def test_all_five_trap_kinds_are_planted(self, db, seeded):
        kinds = set(db.execute(select(TruthTrap.trap_kind)).scalars().all())
        assert kinds == {
            "identity_critical",
            "performance_out_of_band",
            "performance_in_band",
            "cross_brand_equivalent",
            "directed_substitute",
        }

    def test_traps_include_both_refusals_and_a_genuine_duplicate(self, db, seeded):
        expectations = set(db.execute(select(TruthTrap.expect_duplicate)).scalars().all())
        assert expectations == {True, False}

    def test_trap_sides_are_in_different_truth_groups(self, db, seeded):
        gid = dict(db.execute(select(TruthGroup.raw_item_id, TruthGroup.group_id)).all())
        for a, b, expect in db.execute(
            select(TruthTrap.raw_item_a, TruthTrap.raw_item_b, TruthTrap.expect_duplicate)
        ).all():
            if expect:
                assert gid[a] == gid[b], "an in-band trap must be one product"
            else:
                assert gid[a] != gid[b], "a refusal trap must be two products"

    def test_directed_equivalence_truth_records_a_direction(self, db, seeded):
        rows = db.execute(
            select(TruthEquivalence.direction, TruthEquivalence.rel_type)
        ).all()
        assert rows
        directions = {d for d, _ in rows}
        assert "a_to_b" in directions, "directed substitution must be represented"
        assert "bidirectional" in directions, "cross-brand equivalence is symmetric"


class TestLearnability:
    """A ground truth no system could satisfy would make the metrics fiction."""

    def test_distinct_products_are_not_textually_identical(self, db, seeded):
        gid = dict(db.execute(select(TruthGroup.raw_item_id, TruthGroup.group_id)).all())
        by_hash = collections.defaultdict(set)
        for raw_id, digest in db.execute(select(Item.raw_item_id, Item.norm_hash)).all():
            by_hash[digest].add(gid.get(raw_id))

        sizes = collections.Counter(gid.values())
        positive_pairs = sum(n * (n - 1) // 2 for n in sizes.values())
        unresolvable = sum(
            len(g) * (len(g) - 1) // 2 for g in by_hash.values() if len(g) > 1
        )
        # A handful is tolerable; a few percent would cap achievable precision.
        assert unresolvable / max(positive_pairs, 1) < 0.01

    def test_class_value_ladders_clear_their_tolerance_bands(self):
        """Two distinct products must never sit inside each other's band."""
        for class_code, space in CLASS_SPACES.items():
            schema = get_schema(class_code)
            for attr, values in space.items():
                spec = schema.attributes.get(attr)
                if spec is None or spec.role != "performance" or not spec.tolerance_pct:
                    continue
                numbers = sorted(float(v) for v in values)
                for lo, hi in itertools.pairwise(numbers):
                    gap = abs(hi - lo) / max(abs(hi), 1e-9) * 100
                    assert gap > spec.tolerance_pct, (
                        f"{class_code}.{attr}: {lo} and {hi} are {gap:.1f}% apart, "
                        f"inside the {spec.tolerance_pct}% tolerance band"
                    )

    def test_allocation_never_exceeds_class_capacity(self):
        alloc = allocate(7000)
        for class_code, want in alloc.items():
            assert want <= class_capacity(class_code)
        assert sum(alloc.values()) == 7000


class TestExtractionQuality:
    """Attribute recovery decides whether the veto layer has anything to act on."""

    def test_most_rows_are_classified(self, db, seeded):
        total = db.execute(select(func.count(Item.id))).scalar()
        unclassified = db.execute(
            select(func.count(Item.id)).where(Item.class_code == "unclassified")
        ).scalar()
        assert unclassified / total < 0.05

    def test_identity_critical_attributes_are_recovered(self, db, seeded):
        found = missing = 0
        for class_code, attrs_json in db.execute(
            select(Item.class_code, Item.attrs_json)
        ).all():
            if class_code == "unclassified":
                continue
            attrs = json.loads(attrs_json)
            for spec in get_schema(class_code).identity_critical:
                if attrs.get(spec.name) is None:
                    missing += 1
                else:
                    found += 1
        assert found / (found + missing) > 0.95
