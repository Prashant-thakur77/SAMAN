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
    """Skipping a bucket outright cost 0.09 of blocking recall at 150k rows."""

    def _stats(self, buckets, cap, **kwargs):
        out: set[tuple[int, int]] = set()
        stats = blocking.BlockingStats()
        blocking._pairs_from_buckets(buckets, out, stats, "test", cap=cap, **kwargs)
        return out, stats

    def test_a_bucket_within_its_cap_is_compared_fully(self):
        out, stats = self._stats({"k": [1, 2, 3]}, cap=10)
        assert out == {(1, 2), (1, 3), (2, 3)}
        assert stats.oversized_buckets == 0

    def test_an_oversized_bucket_is_windowed_rather_than_dropped(self):
        members = list(range(1, 41))
        out, stats = self._stats({"k": members}, cap=10)
        assert stats.oversized_buckets == 1
        assert out, "a skipped bucket contributes nothing at all"
        # Bounded: every member paired with at most `window` neighbours.
        assert len(out) <= len(members) * blocking.OVERSIZED_WINDOW

    def test_the_window_is_bounded_not_quadratic(self):
        """The whole point: a 46,000-member bucket must not cost 1.1 billion
        comparisons."""
        members = list(range(2_000))
        out, _ = self._stats({"k": members}, cap=10)
        assert len(out) < len(members) * (blocking.OVERSIZED_WINDOW + 1)
        assert len(out) < len(members) * (len(members) - 1) // 2

    def test_the_bucket_is_sorted_before_windowing(self):
        """Item order is load order, which groups a CPSE's own rows together —
        the least useful ordering, since duplicates live across CPSEs."""
        members = [1, 2, 3, 4]
        sort_key = {1: "ZZZ", 2: "AAA", 3: "ZZY", 4: "AAB"}
        out, _ = self._stats({"k": members}, cap=2, sort_key=sort_key)
        # Sorted order is 2, 4, 3, 1 — so the AAA/AAB pair must be present.
        assert (2, 4) in out

    def test_a_pass_can_opt_out_of_windowing(self):
        """A token bucket overflows because the token is "BEARING"."""
        out, stats = self._stats({"k": list(range(50))}, cap=5, window_oversized=False)
        assert stats.oversized_buckets == 1
        assert out == set()
