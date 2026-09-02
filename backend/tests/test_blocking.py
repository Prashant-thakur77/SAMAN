"""Multi-pass candidate generation — spec §2A.1.

Blocking failures are invisible in precision and matcher recall alike: a pair
the blocker never emits is a pair the matcher is never asked about.
"""

import numpy as np

from app import blocking
from app.blocking import (
    ANN_K,
    BAND_MAX_BUCKET,
    TOKEN_MAX_BUCKET,
    ItemKey,
    content_tokens,
    generate_candidates,
)


def key(item_id, text, cls="bearing.ball.deep_groove", mpn=None, band=None, gtin=None):
    import hashlib

    return ItemKey(
        id=item_id,
        class_code=cls,
        norm_text=text,
        norm_hash=hashlib.sha256(text.encode()).hexdigest(),
        mpn_norm=mpn,
        gtin=gtin,
        block_value=band,
    )


class TestPasses:
    def test_shared_mpn_produces_a_candidate(self):
        pairs, _ = generate_candidates([key(1, "A", mpn="62052Z"), key(2, "B", mpn="62052Z")])
        assert (1, 2) in pairs

    def test_shared_gtin_produces_a_candidate(self):
        pairs, _ = generate_candidates(
            [key(1, "A", gtin="12345678"), key(2, "B", gtin="12345678")]
        )
        assert (1, 2) in pairs

    def test_identical_text_produces_a_candidate(self):
        pairs, _ = generate_candidates([key(1, "BEARING 6205"), key(2, "BEARING 6205")])
        assert (1, 2) in pairs

    def test_shared_band_produces_a_candidate(self):
        pairs, _ = generate_candidates([key(1, "X ALPHA", band="25"), key(2, "Y BETA", band="25")])
        assert (1, 2) in pairs

    def test_shared_rare_token_produces_a_candidate(self):
        """A rare token is a strong key even when everything else differs."""
        pairs, _ = generate_candidates(
            [key(1, "BEARING SPECIALTOKEN9 ALPHA"), key(2, "GASKET SPECIALTOKEN9 BETA")]
        )
        assert (1, 2) in pairs

    def test_unrelated_items_are_not_paired(self):
        pairs, _ = generate_candidates([key(1, "ALPHA ONE"), key(2, "BETA TWO", cls="valve.gate")])
        assert pairs == set()

    def test_pairs_are_order_independent(self):
        pairs, _ = generate_candidates([key(9, "A", mpn="X1234"), key(2, "B", mpn="X1234")])
        assert (2, 9) in pairs and (9, 2) not in pairs


class TestBucketCaps:
    def test_an_oversized_bucket_is_skipped_and_reported(self):
        """An undiscriminating key must not cost quadratic time silently."""
        items = [key(i, "SAME TEXT EVERYWHERE", band="25") for i in range(BAND_MAX_BUCKET + 50)]
        _, stats = generate_candidates(items)
        assert stats.oversized_buckets > 0
        assert stats.largest_bucket >= BAND_MAX_BUCKET

    def test_caps_are_reported_in_the_stats(self):
        _, stats = generate_candidates([key(1, "A"), key(2, "B")])
        caps = stats.as_dict()["bucket_caps"]
        assert caps["class_band"] == BAND_MAX_BUCKET and caps["token"] == TOKEN_MAX_BUCKET


class TestTokens:
    def test_short_tokens_are_not_blocking_keys(self):
        assert "AB" not in content_tokens("AB BEARING")

    def test_content_tokens_are_deduplicated(self):
        assert content_tokens("BEARING BEARING 6205") == {"BEARING", "6205"}


class TestAnnPass:
    def test_near_neighbours_become_candidates(self):
        vectors = np.array([[1.0, 0.0], [0.99, 0.14], [0.0, 1.0]], dtype=np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        items = [key(1, "ALPHA"), key(2, "BETA"), key(3, "GAMMA")]
        pairs, stats = generate_candidates(items, vectors, {1: 0, 2: 1, 3: 2})
        assert (1, 2) in pairs
        assert stats.per_pass["ann"] > 0

    def test_ann_is_wide_enough_to_matter(self):
        """Measured as the highest recall per candidate pair of any pass."""
        assert ANN_K >= 20


class TestOversizedBuckets:
    """An undiscriminating key is skipped, not compared pairwise."""

    def _stats(self, buckets, cap):
        out: set[tuple[int, int]] = set()
        stats = blocking.BlockingStats()
        blocking._pairs_from_buckets(buckets, out, stats, "test", cap=cap)
        return out, stats

    def test_a_bucket_within_its_cap_is_compared_fully(self):
        out, stats = self._stats({"k": [1, 2, 3]}, cap=10)
        assert out == {(1, 2), (1, 3), (2, 3)}
        assert stats.oversized_buckets == 0

    def test_an_oversized_bucket_is_skipped_and_counted(self):
        """Comparing a 46,000-member bucket pairwise is 1.1 billion
        comparisons; the ANN and anchor passes still cover those items."""
        out, stats = self._stats({"k": list(range(500))}, cap=10)
        assert stats.oversized_buckets == 1
        assert out == set()

    def test_the_largest_bucket_is_reported_even_when_skipped(self):
        """The number a tuning decision is made from must not be hidden by the
        cap that skipped it."""
        _, stats = self._stats({"k": list(range(500))}, cap=10)
        assert stats.largest_bucket == 500


class TestIdentitySignature:
    """The substitutes pass (§2B).

    Two items agreeing on every identity-critical attribute and differing on a
    rated one are exactly a directed substitute — and exactly what the other
    passes lose. They share a class-band bucket, so when that bucket overflows
    they go with it; the ANN pass rescues the duplicates in a skipped bucket
    because their text is nearly identical, but a substitute's text differs on
    the rating that makes it one. It was 602 of 2,393 held-out equivalence
    pairs never reaching the engine.
    """

    def test_agreeing_identities_share_a_signature(self):
        from app.pipeline import _identity_signature

        a = _identity_signature(
            "chemical.reagent",
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 20.0},
        )
        b = _identity_signature(
            "chemical.reagent",
            {"substance": "XYLENE", "grade": "TECH", "concentration_pct": 90.0},
        )
        assert a is not None and a == b, "the rating must not enter the key"

    def test_a_differing_identity_does_not(self):
        from app.pipeline import _identity_signature

        a = _identity_signature("chemical.reagent", {"substance": "XYLENE", "grade": "TECH"})
        b = _identity_signature("chemical.reagent", {"substance": "TOLUENE", "grade": "TECH"})
        assert a != b

    def test_a_missing_attribute_produces_no_signature(self):
        """A signature built from three attributes out of four would collide
        two items that differ on the fourth — the opposite of the point."""
        from app.pipeline import _identity_signature

        assert _identity_signature("chemical.reagent", {"substance": "XYLENE"}) is None

    def test_an_unclassified_item_has_no_signature(self):
        from app.pipeline import _identity_signature

        assert _identity_signature("unclassified", {"anything": 1}) is None

    def test_a_number_renders_the_same_however_it_was_read(self):
        """A bore read from "65MM BORE" is the float 65.0; the same bore from
        designation 6313 is the int 65. Rendered naively those are two
        different keys, so the same bearing never met itself — 172 of the pairs
        this pass exists to catch."""
        from app.pipeline import _canonical, _identity_signature

        assert _canonical(65.0) == _canonical(65) == "65"
        assert _canonical("65.0") == _canonical(" 65 ") == "65"
        assert _canonical(4.6) == _canonical("4.60") == "4.6"
        assert _canonical("H7") == "H7"
        assert _canonical("ss316") == "SS316"

        explicit = _identity_signature(
            "bearing.ball.deep_groove",
            {"bore_mm": 65.0, "outer_dia_mm": 140.0, "width_mm": 33.0, "seal_type": "OPEN"},
        )
        derived = _identity_signature(
            "bearing.ball.deep_groove",
            {"bore_mm": 65, "outer_dia_mm": 140, "width_mm": 33, "seal_type": "OPEN"},
        )
        assert explicit == derived

    def test_the_signature_is_case_and_whitespace_insensitive(self):
        from app.pipeline import _identity_signature

        a = _identity_signature("chemical.reagent", {"substance": "xylene ", "grade": "tech"})
        b = _identity_signature("chemical.reagent", {"substance": "XYLENE", "grade": "TECH"})
        assert a == b

    def test_the_pass_emits_pairs_for_a_shared_signature(self):
        keys = [
            blocking.ItemKey(1, "c", "a", "h1", None, None, "5", identity_signature="sig"),
            blocking.ItemKey(2, "c", "b", "h2", None, None, "9", identity_signature="sig"),
            blocking.ItemKey(3, "c", "c", "h3", None, None, "5", identity_signature="other"),
        ]
        pairs, stats = blocking.generate_candidates(keys)
        assert (1, 2) in pairs
        assert stats.per_pass.get("identity", 0) >= 1


class TestSchemaInvariants:
    def test_every_block_on_is_an_identity_attribute(self):
        """`block_on` is the class's most discriminating *identity* field.

        `chemical.reagent` blocked on `concentration_pct` — a performance
        rating with a declared direction — so a 20% xylene and a 50% xylene
        landed in different buckets, which is precisely the pair that
        substitutes for the other.
        """
        from app.taxonomy import real_classes

        for schema in real_classes():
            if schema.block_on is None:
                continue
            identity = {spec.name for spec in schema.identity_critical}
            assert schema.block_on in identity, (
                f"{schema.code} blocks on {schema.block_on}, which is not "
                "identity-critical"
            )
