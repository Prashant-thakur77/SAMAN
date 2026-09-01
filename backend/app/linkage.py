"""Tier-1 probabilistic record linkage via splink — spec §0.4.

    splink present  ->  Fellegi-Sunter match weights, learned from the data
    splink absent   ->  rapidfuzz token_set_ratio (see match.tier1_fuzzy)

What splink adds over a hand-weighted similarity score is that the weights are
**estimated** rather than chosen: expectation-maximisation learns, per
comparison, how much agreement and disagreement each field is worth given how
often values agree by chance. It also yields a per-comparison contribution for
each pair, which is what the evidence cards show instead of a bare number
(§9 names splink's match-weight waterfall as the model for this).

Everything here is defensive by construction. splink is an optional dependency
and it sits on a stack — DuckDB, pandas, sqlglot — whose versions have to line
up. Any failure at any stage returns None and the caller falls back to
rapidfuzz, because a broken accelerator must never take the pipeline with it.
"""

from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Item
from .taxonomy import get_schema

log = logging.getLogger(__name__)

#: Match probability below which a pair is not worth returning at all.
MIN_PROBABILITY = 0.01

#: Cap on the random sample used to estimate u-probabilities.
U_SAMPLE_PAIRS = 3e5

#: Above this many predicted pairs, splink is abandoned and Tier 1 degrades to
#: rapidfuzz. A mis-estimated model can emit tens of millions of pairs; on a
#: demo laptop that is an out-of-memory kill, and no accelerator is worth
#: taking the pipeline down for (§9).
MAX_PREDICTED_PAIRS = 6_000_000

#: The per-comparison waterfall is only kept for pairs a reviewer might
#: actually see. Retaining it for every scored pair costs gigabytes and buys
#: nothing: low-probability pairs are never shown as evidence.
WATERFALL_MIN_PROBABILITY = 0.5


@dataclass
class LinkageResult:
    """Per-pair Fellegi-Sunter output, keyed by ordered item id pair."""

    probability: dict[tuple[int, int], float] = field(default_factory=dict)
    weight: dict[tuple[int, int], float] = field(default_factory=dict)
    levels: dict[tuple[int, int], dict[str, int]] = field(default_factory=dict)
    trained: bool = False
    pairs: int = 0
    seconds: float = 0.0
    note: str = ""

    def score(self, a: int, b: int) -> float | None:
        return self.probability.get((a, b) if a < b else (b, a))

    def waterfall(self, a: int, b: int) -> dict | None:
        """Per-comparison contribution, for the evidence card."""
        key = (a, b) if a < b else (b, a)
        if key not in self.probability:
            return None
        return {
            "engine": "splink",
            "match_probability": round(self.probability[key], 4),
            "match_weight": round(self.weight.get(key, 0.0), 4),
            "comparison_levels": self.levels.get(key, {}),
        }

    def as_stats(self) -> dict:
        return {
            "engine": "splink" if self.trained else "unavailable",
            "scored_pairs": self.pairs,
            "waterfalls_kept": len(self.levels),
            "seconds": round(self.seconds, 1),
            "note": self.note,
        }


def _block_value(class_code: str, attrs: dict) -> str:
    """The class's coarse blocking attribute, as a string for SQL blocking."""
    block_on_attr = get_schema(class_code).block_on
    if not block_on_attr:
        return ""
    value = attrs.get(block_on_attr)
    return "" if value is None else str(value)


def _frame(db: Session):
    """Build the record frame splink trains on."""
    import pandas as pd

    rows = db.execute(
        select(
            Item.id,
            Item.class_code,
            Item.norm_text,
            Item.norm_hash,
            Item.mpn_norm,
            Item.gtin,
            Item.attrs_json,
        ).order_by(Item.id)
    ).all()

    records = []
    for item_id, class_code, norm_text, norm_hash, mpn, gtin, attrs_json in rows:
        attrs = json.loads(attrs_json or "{}")
        records.append(
            {
                "unique_id": item_id,
                "class_code": class_code or "",
                "norm_text": norm_text or "",
                "norm_hash": norm_hash or "",
                # splink compares in SQL, where NULL semantics differ from ours;
                # empty string keeps "absent" a comparable value.
                "mpn_norm": mpn or "",
                "gtin": gtin or "",
                "brand": str(attrs.get("brand") or ""),
                "block_value": _block_value(class_code or "", attrs),
            }
        )
    return pd.DataFrame.from_records(records)


def _row_count(prediction_table) -> int:
    """Count predicted pairs without materialising them into pandas.

    Best effort: if the backend cannot be counted cheaply we return 0 and let
    the run proceed, since a guard that itself costs the memory it is guarding
    against would be self-defeating.
    """
    try:
        relation = prediction_table.as_duckdbpyrelation()
        return int(relation.aggregate("count(*) AS n").fetchone()[0])
    except Exception:
        return 0


#: Rows pulled from DuckDB per batch when collecting predictions.
FETCH_BATCH = 100_000


def _collect(prediction_table, candidates, started: float) -> LinkageResult:
    """Stream predictions out of DuckDB, keeping only what will be read.

    Materialising the whole prediction set into pandas first peaked at 7.7 GB
    on the demo profile, for 2.6M pairs of which only 422k were ours. Fetching
    in batches keeps memory flat and bounded.
    """
    import time

    result = LinkageResult(trained=True)
    relation = prediction_table.as_duckdbpyrelation()
    columns = {name: i for i, name in enumerate(relation.columns)}
    gamma = {
        name.removeprefix("gamma_"): index
        for name, index in columns.items()
        if name.startswith("gamma_")
    }
    left, right = columns["unique_id_l"], columns["unique_id_r"]
    probability_column = columns["match_probability"]
    weight_column = columns["match_weight"]

    while batch := relation.fetchmany(FETCH_BATCH):
        for row in batch:
            a, b = int(row[left]), int(row[right])
            key = (a, b) if a < b else (b, a)
            if candidates is not None and key not in candidates:
                continue
            probability = float(row[probability_column])
            result.probability[key] = probability
            result.weight[key] = float(row[weight_column])
            if probability >= WATERFALL_MIN_PROBABILITY:
                result.levels[key] = {
                    name: int(row[index]) for name, index in gamma.items()
                }

    result.pairs = len(result.probability)
    result.seconds = time.time() - started
    return result


def run_linkage(
    db: Session, candidates: set[tuple[int, int]] | None = None
) -> LinkageResult | None:
    """Train and predict. Returns None whenever splink cannot be used.

    `candidates` scopes the result to the pairs the engine will actually
    consider. splink's own blocking is coarser than ours and emits several
    million pairs; keeping all of them costs gigabytes of memory for scores
    nothing will ever read.
    """
    import time

    started = time.time()

    from .capabilities import detect

    if detect().linkage_mode != "splink":
        return None

    try:
        import splink.comparison_library as cl
        from splink import DuckDBAPI, Linker, SettingsCreator, block_on
    except Exception as exc:
        log.info("splink unavailable, Tier 1 falls back to rapidfuzz: %s", exc)
        return None

    try:
        # splink is chatty and emits training banners; the pipeline reports
        # progress through its own status object.
        logging.getLogger("splink").setLevel(logging.ERROR)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            frame = _frame(db)
            if len(frame) < 50:
                return LinkageResult(note="too few records to estimate parameters")

            settings = SettingsCreator(
                link_type="dedupe_only",
                comparisons=[
                    # The anchor keys, as exact-match comparisons: EM learns how
                    # much a shared part number is actually worth on this data
                    # rather than us asserting it.
                    cl.ExactMatch("mpn_norm"),
                    cl.ExactMatch("gtin"),
                    cl.ExactMatch("class_code"),
                    cl.ExactMatch("brand"),
                    # String similarity computed in DuckDB, the in-database
                    # counterpart of the rapidfuzz ratio the fallback uses.
                    #
                    # A token-intersection comparison was tried here instead —
                    # closer in spirit to token_set_ratio, and a better fit for
                    # descriptions whose attribute order varies. It wrecked the
                    # prior (splink estimated 1 in 4.67 of 69M comparisons would
                    # match) and peaked at 11 GB before the OOM killer took it.
                    # Jaro-Winkler is what is actually safe to run on a laptop.
                    cl.JaroWinklerAtThresholds("norm_text", [0.92, 0.85, 0.70]),
                ],
                # Aligned with app/blocking.py so splink scores the same
                # population the rest of the engine reasons about.
                blocking_rules_to_generate_predictions=[
                    block_on("mpn_norm"),
                    block_on("norm_hash"),
                    block_on("class_code", "block_value"),
                ],
                retain_intermediate_calculation_columns=True,
            )

            linker = Linker(frame, settings, DuckDBAPI())
            linker.training.estimate_probability_two_random_records_match(
                [block_on("mpn_norm")], recall=0.7
            )
            linker.training.estimate_u_using_random_sampling(max_pairs=U_SAMPLE_PAIRS)
            # Two sessions on different rules: each fixes the parameters it
            # blocks on, so together they cover every comparison.
            linker.training.estimate_parameters_using_expectation_maximisation(
                block_on("mpn_norm")
            )
            linker.training.estimate_parameters_using_expectation_maximisation(
                block_on("class_code", "block_value")
            )

            prediction_table = linker.inference.predict(
                threshold_match_probability=MIN_PROBABILITY
            )
            emitted = _row_count(prediction_table)
            if emitted > MAX_PREDICTED_PAIRS:
                log.warning(
                    "splink emitted %s pairs (limit %s); degrading to rapidfuzz",
                    f"{emitted:,}",
                    f"{MAX_PREDICTED_PAIRS:,}",
                )
                return None

            result = _collect(prediction_table, candidates, started)

    except Exception as exc:
        # A broken accelerator must never take the pipeline with it (§9).
        log.warning("splink linkage failed, falling back to rapidfuzz: %s", exc)
        return None

    result.note = (
        f"{result.pairs:,} of our candidate pairs scored by Fellegi-Sunter "
        f"match weight (splink emitted {emitted:,})"
    )
    return result
