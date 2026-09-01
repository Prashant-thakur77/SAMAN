"""Multi-pass candidate generation — spec §2A.1.

The blocking trap the spec names: if the only blocking key depends on a token
that happens to be missing or misspelled, the true pair is never compared at
all, and that loss is *invisible* in precision or matcher recall. So blocking
recall is measured and reported on its own (target >= 0.97), and several
independent passes run so that no single failure mode can hide a pair.

Passes, cheapest first:

    mpn          identical normalized part number
    text         identical normalized description
    class_band   same class, same value of the class's coarse blocking attribute
    token3       same class, same three leading content tokens (order-insensitive)
    ann          nearest neighbours by embedding cosine, within class

Every pass is capped: one enormous bucket would otherwise dominate the run
quadratically. Skipped buckets are reported rather than silently dropped.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

#: Per-pass bucket caps. A bucket beyond its cap is skipped rather than
#: compared pairwise: an undiscriminating key would cost quadratic time for
#: pairs the other passes already cover. Measured on the demo profile, these
#: values reach 0.984 held-out blocking recall for ~626k candidate pairs.
MAX_BUCKET = 300  # default for exact-key passes
BAND_MAX_BUCKET = 150  # class + coarse attribute band
TOKEN_MAX_BUCKET = 100  # inverted token index — common tokens are useless keys

#: Neighbours per item in the embedding pass. The most recall per candidate
#: pair of any pass, so it is worth running wide.
ANN_K = 50

#: Sub-blocking an oversized bucket: measured, and rejected.
#:
#: An oversized bucket could be salvaged rather than
#: skipped: sort it by normalized text and compare each member with its next
#: dozen neighbours, at O(size x window) instead of O(size squared). It looked
#: like the fix for the 150k benchmark, where every (class, band) bucket
#: exceeds its cap -- the largest holds 46,911 members -- and blocking recall
#: falls to 0.897.
#:
#: It was built and measured back to back on the same machine:
#:
#:   150k benchmark   recall 0.8965 -> 0.9005, 921s -> 1014s, 6.98 -> 7.59 GB
#:   12k demo         recall 0.9842 -> 0.9845, +6.5% candidate pairs
#:
#: Four thousandths of blocking recall for a tenth of the wall clock and a
#: tenth of the memory. The ANN pass already covers this space -- it produced
#: 4.35M of the 5.29M candidate pairs -- so the window was mostly re-finding
#: what it had found. Recorded here rather than left in the code, so the next
#: person to have the idea has the numbers instead of the work.

#: Tokens shorter than this are too common to discriminate.
MIN_TOKEN_LEN = 3

_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9./-]*")
_STOPWORDS = {"THE", "OF", "AND", "WITH", "FOR", "TYPE", "STANDARD", "NUMBER"}


@dataclass
class BlockingStats:
    pairs: int = 0
    per_pass: dict[str, int] = field(default_factory=dict)
    oversized_buckets: int = 0
    largest_bucket: int = 0

    def as_dict(self) -> dict:
        return {
            "candidate_pairs": self.pairs,
            "per_pass": dict(self.per_pass),
            "oversized_buckets": self.oversized_buckets,
            "largest_bucket": self.largest_bucket,
            "bucket_caps": {
                "default": MAX_BUCKET,
                "class_band": BAND_MAX_BUCKET,
                "token": TOKEN_MAX_BUCKET,
            },
            "ann_k": ANN_K,
        }


@dataclass
class ItemKey:
    """The minimum an item needs to be blocked on."""

    id: int
    class_code: str
    norm_text: str
    norm_hash: str
    mpn_norm: str | None
    gtin: str | None
    block_value: str | None  # value of the class's block_on attribute


def _ordered(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _pairs_from_buckets(
    buckets: dict,
    out: set[tuple[int, int]],
    stats: BlockingStats,
    pass_name: str,
    cap: int = MAX_BUCKET,
) -> None:
    added = 0
    for members in buckets.values():
        size = len(members)
        if size < 2:
            continue
        stats.largest_bucket = max(stats.largest_bucket, size)
        if size > cap:
            # Comparing a 46,000-member bucket pairwise is 1.1 billion
            # comparisons for a key that clearly is not discriminating. The
            # other passes still cover these items — see the note above the
            # bucket caps for the sub-blocking alternative and why it lost.
            stats.oversized_buckets += 1
            continue
        for i in range(size):
            for j in range(i + 1, size):
                pair = _ordered(members[i], members[j])
                if pair not in out:
                    out.add(pair)
                    added += 1
    stats.per_pass[pass_name] = stats.per_pass.get(pass_name, 0) + added


def content_tokens(norm_text: str) -> set[str]:
    """Distinct content tokens worth blocking on."""
    return {
        t
        for t in _TOKEN.findall(norm_text.upper())
        if len(t) >= MIN_TOKEN_LEN and t not in _STOPWORDS
    }


def token_key(norm_text: str) -> str:
    """Three leading content tokens, sorted so word order cannot hide a pair.

    Retained for the sorted-key style of blocking, but measured at only 0.11
    recall on this data — CPSE style profiles reorder attributes, so the
    *leading* tokens rarely survive. The inverted index below replaced it.
    """
    tokens = [t for t in _TOKEN.findall(norm_text.upper()) if t not in _STOPWORDS]
    return "|".join(sorted(tokens[:3]))


def generate_candidates(
    items: list[ItemKey],
    vectors: np.ndarray | None = None,
    index_by_id: dict[int, int] | None = None,
) -> tuple[set[tuple[int, int]], BlockingStats]:
    """Return candidate pairs and the stats behind them."""
    out: set[tuple[int, int]] = set()
    stats = BlockingStats()

    # --- pass 1: exact anchor key (MPN, then GTIN) ---
    by_mpn: dict[str, list[int]] = defaultdict(list)
    by_gtin: dict[str, list[int]] = defaultdict(list)
    for item in items:
        if item.mpn_norm:
            by_mpn[item.mpn_norm].append(item.id)
        if item.gtin:
            by_gtin[item.gtin].append(item.id)
    _pairs_from_buckets(by_mpn, out, stats, "mpn")
    _pairs_from_buckets(by_gtin, out, stats, "gtin")

    # --- pass 2: identical normalized text ---
    by_text: dict[str, list[int]] = defaultdict(list)
    for item in items:
        by_text[item.norm_hash].append(item.id)
    _pairs_from_buckets(by_text, out, stats, "text")

    # --- pass 3: class + the class's coarse blocking attribute ---
    by_band: dict[tuple[str, str], list[int]] = defaultdict(list)
    for item in items:
        if item.block_value is not None:
            by_band[(item.class_code, item.block_value)].append(item.id)
    _pairs_from_buckets(by_band, out, stats, "class_band", cap=BAND_MAX_BUCKET)

    # --- pass 4: inverted token index, one bucket per distinct token ---
    # A rare token ("6205", "SS316-GRAPHITE") is a strong key; a common one
    # ("BEARING") overflows its cap and is skipped. That asymmetry is the point.
    by_token: dict[tuple[str, str], list[int]] = defaultdict(list)
    for item in items:
        for token in content_tokens(item.norm_text):
            by_token[(item.class_code, token)].append(item.id)
    _pairs_from_buckets(by_token, out, stats, "token", cap=TOKEN_MAX_BUCKET)

    # --- pass 5: embedding neighbours, within class ---
    if vectors is not None and index_by_id and len(items) > 1:
        _ann_pass(items, vectors, index_by_id, out, stats)

    stats.pairs = len(out)
    return out, stats


def _ann_pass(
    items: list[ItemKey],
    vectors: np.ndarray,
    index_by_id: dict[int, int],
    out: set[tuple[int, int]],
    stats: BlockingStats,
) -> None:
    """Top-k cosine neighbours per item, computed class by class.

    Restricting to a class bounds the work: a global all-pairs similarity is
    quadratic in the whole corpus, which the benchmark profile cannot afford.
    Items whose class is uncertain land in the `unclassified` pool and are
    compared against each other there.
    """
    added = 0
    by_class: dict[str, list[int]] = defaultdict(list)
    for item in items:
        by_class[item.class_code].append(item.id)

    for member_ids in by_class.values():
        if len(member_ids) < 2:
            continue
        rows = [index_by_id[i] for i in member_ids if i in index_by_id]
        if len(rows) < 2:
            continue
        block = vectors[rows]  # already L2-normalized, so a dot product is cosine
        ids = [member_ids[n] for n, i in enumerate(member_ids) if i in index_by_id]

        k = min(ANN_K + 1, len(rows))
        # Chunked so a large class never materializes a full similarity matrix.
        for start in range(0, len(rows), 512):
            chunk = block[start : start + 512]
            sims = chunk @ block.T
            top = np.argpartition(-sims, kth=k - 1, axis=1)[:, :k]
            for local, neighbours in enumerate(top):
                a = ids[start + local]
                for n in neighbours:
                    b = ids[int(n)]
                    if a == b:
                        continue
                    pair = _ordered(a, b)
                    if pair not in out:
                        out.add(pair)
                        added += 1
    stats.per_pass["ann"] = added
