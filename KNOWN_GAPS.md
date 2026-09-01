# Known gaps

Per spec §10, anything scoped in the build spec but not yet built is recorded
here with a one-line reason. An honest gaps list is worth more than a hidden
hole. This file is updated at the end of every milestone.

## Status: end of M4

M1 the scaffold, M2 the data model and synthetic estate, M3 the matching
engine: embeddings, multi-pass blocking, the §2A veto layer, clustering, CNMC
issuance and the §0.6 evaluation. All four M3 gates pass on held-out data.

### Not built yet

| Gap | Reason | Closes in |
|---|---|---|
| The LLM may not yet polish an unfilled template slot | §2D allows it, validated back against the template. Rendering drops unfilled segments cleanly instead, which is deterministic; the polish step needs the Ollama client | M6 |
| Equivalence recall is 0.61 | 20% of true pairs never reach the engine (blocking is tuned for duplicates) and some that do lack the attributes to decide. Reported with its ceiling — `candidate_coverage` and `recall_of_reachable` — rather than as a bare number | future tuning |
| An LLM may not yet propose equivalences | §2B source 4, the lowest-trust one. It can only ever add review-queue suggestions, never auto-approve | M6 |
| Tier 3 grey-band adjudication is not wired | The deterministic adjudicator and the optional Ollama path attach to the review queue | M4/M6 |
| Home, Search, dashboards, Copilot, Onboard, Migration and Admin still render empty states | Nothing may be faked (§10); screens fill as their engines land | M5–M7.5 |
| No frontend test runner | The API is covered by 472 pytest cases and the UI is type-checked and built in CI, but component behaviour is unverified | polish pass |
| `make demo-restore` / `make licenses` exit non-zero | Placeholders fail loudly rather than pretending to succeed | M8, M8B |
| Tables are not virtualized; search is not paginated | Needed only once the UI renders large result sets | M8B |
| No screenshots or README demo script | Requires working screens | M9 |

### Deliberate deviations from the spec

Recorded rather than silently substituted, per the "how to use this spec" note.

| Item | What the spec says | What was built, and why |
|---|---|---|
| Seed volume | §7 asks for "~2,200 ground-truth products" rendered into "1–4 CPSE-specific descriptions" **and** "~3,000 raw items per CPSE" | Both cannot hold at once: 2,200 x up to 4 caps at 8,800, short of 12,000. Both numbers are honoured by reading the 2,200 as the cross-CPSE *shared* products and filling the remainder with singletons unique to one CPSE — which is also how a real material master looks. |
| Benchmark profile multiplicity | §7 implies the same 1–4 renderings for `seed-large` | Eight equipment classes cannot express 150k *distinct* products (capacity ~14,200). The benchmark profile raises multiplicity instead. It is only ever used for the §8A performance run, never for metrics. |
| Optional dependencies | §0.4 names `splink` and `sentence-transformers` | Both sit in `requirements-optional.txt`, so the §0.4 degraded paths are what CI and the demo exercise by default. `make deps-optional` installs them and `/api/health` reports the change. |
| Tier-2 model download | §0.4 says use `sentence-transformers` "if importable" | Importable is not sufficient: the library downloads weights from Hugging Face on first use, which would break the no-network guarantee (§9). The model is loaded in offline mode only and falls back to TF-IDF if the weights are not already cached. |
| First-three-token blocking key | §2A.1 lists "first-3-token sort key" as a blocking pass | Implemented and measured at **0.11** recall for 419k candidate pairs — CPSE style profiles reorder attributes, so leading tokens rarely survive. Replaced with an inverted token index (rare tokens make strong keys, common ones overflow their cap), which reaches 0.56 for 170k pairs. The original is kept in `blocking.py` with its measurement recorded. |

### Judgement calls worth knowing about

- **Brand is cosmetic for vetoing, but two manufacturers are two records.**
  §2A defines `brand` as cosmetic, so it never vetoes on specification. But
  SKF 6205-2Z and FAG 6205-2ZR are two catalogue entries that are
  *interchangeable*, not identical — merging them into one CNMC would erase a
  distinction CPSE masters genuinely carry. The matcher refuses such pairs and
  records an equivalence instead (§2B). 360 such pairs are planted as truth and
  all 168 held-out ones are handled correctly.
- **Refusals must hold transitively.** Connected components merge A–B–C even
  when A and C are a hard mismatch. Clusters are therefore refined until no two
  members inside one would be refused by any rule. Before this, pairwise
  precision was 0.73 against a B-cubed precision of 0.96 — the signature of one
  giant over-merged cluster.
- **An issued CNMC pins its cluster.** Re-running the pipeline rebuilds the
  derived layer from the pair graph, but never touches a cluster whose golden
  record already carries a code.
- **A missing attribute never vetoes.** Refusing on absent evidence would turn
  every extraction gap into a false negative. The residual trap failures are
  rows whose value was destroyed by the seed's typo model — the intended
  behaviour, not a defect.

### Audit, after M3

A full pass over M1–M3 against the spec. Verified working: `docker compose up`
serves both services (§0.1) including the API proxy; the design tokens, motion
durations and easing curve match §1.1/§1.5 exactly; fonts are self-hosted with
no `fonts.googleapis` reference anywhere; no non-localhost network call exists
in either app (§9); a fresh empty database answers `/api/metrics` and runs the
pipeline without crashing (§8A); every table and column in §4 exists; the repo
carries no secrets and no build artefacts.

Four defects found and fixed:

| Defect | Why it mattered | Fix |
|---|---|---|
| **Fit classes all compared equal.** `parse_number("H7")` returns magnitude 0, so `H7`, `H6` and `JS9` were mutually identical — and identical to the number 0 | §2A names "tolerance-string parsing (±0.05, H7)" as a comparator. On an identity_critical attribute this is a silent failure to veto, the exact failure the layer exists to prevent | Fit classes now compare as symbols; a grade against a magnitude is `unknown`, not a match |
| **The Tier-0 GTIN anchor was dead code.** 0 of 11,802 items carried a GTIN, so the branch could never fire | §0.4 names GTIN alongside MPN as a Tier-0 anchor. An unexercised branch in the highest-precision tier is untested code in the most load-bearing place | GTINs are extracted from the description (§4 puts `gtin` on `item`, not `raw_item`) with the GS1 check digit verified, and the generator prints them on ~19% of rows. Duplicate recall rose 0.929 → 0.938 |
| **`review_task.cluster_id` was never populated** | §4 declares the column and §6.5's merge-into-cluster view needs it | Populated from the pair's anchor item; 3,606 of 3,606 tasks now carry it |
| **`ruff` was configured in `pyproject.toml` since M1 but never installed** | The lint config was decorative | Installed and run; 55 findings fixed, `B008` suppressed with a reason (`Depends()` in a default is the FastAPI idiom, not a mutable-default bug). Zero findings now |

One earlier claim corrected: the M3 report said in-band trap accuracy was 0.82
on 17 samples. After the GTIN change it is 0.89 on 19. Both are honest small
samples; the figure moves with the seed.

### Tier-1 engine: measured, then chosen

The M3 report flagged splink as "unexercised code — a liability on stage".
It is now implemented, wired and gated. Measured on the demo profile:

| Tier-1 engine | F1 | Wall clock | Peak memory |
|---|---|---|---|
| splink (Fellegi–Sunter) | 0.952 | 68 s | 5.0 GB |
| rapidfuzz (default) | **0.957** | **45 s** | **1.6 GB** |

Both pass all four gates on the same frozen threshold. The fallback is the
default because it is better here on every axis; splink remains a real path,
one flag away, with its match weights and per-comparison waterfall persisted
into the evidence object.

Three things were found by actually running it, none of which would have
surfaced from a dependency list:

- **splink declares `sqlglot>=13` with no upper bound.** Resolution pulls
  sqlglot 30, whose AST splink 4.0.7 cannot parse; EM training dies with
  "Expected sql condition to refer to one column but got []". Pinned to
  `>=25,<26` in `requirements-optional.txt`, because splink's own metadata
  does not constrain it. Anyone following the README would have hit this.
- **pandas 3 ships a native `str` dtype that duckdb 1.1 cannot register.**
  The core `duckdb` pin moved to `>=1.3`.
- **A token-intersection comparison — closer in spirit to `token_set_ratio`
  and the obvious way to close the gap — destroyed the model.** splink
  estimated that 1 in 4.67 of 69M comparisons would match, and the run peaked
  at 11 GB before the OOM killer took it. Reverted, with the reason recorded in
  the code. `run_linkage` now refuses to materialise more than 6M predicted
  pairs and degrades instead, and streams results out of DuckDB in batches
  rather than building one large frame (7.7 GB -> 5.0 GB).

A related defect this exposed: capability detection used `find_spec`, which
succeeds for a package installed without its own dependencies. `/api/health`
was therefore willing to advertise `sentence-transformers` when importing it
raised `ModuleNotFoundError: huggingface_hub`. Detection now performs a real
import, so the health endpoint cannot claim an engine that will not run.

### M3.5 findings

Building the equivalence engine surfaced three things worth recording:

- **A regression I introduced during the audit.** Removing `GR -> GRADE` from
  the abbreviation dictionary (to stop it destroying the chemical grade `GR`)
  silently broke fastener grades written as `GR 4.6`. Grade then extracted as
  `None`, no veto fired, and a grade-4.6 bolt was called equivalent to a
  grade-12.9 one. The pattern now accepts both spellings; the value
  disambiguates, since a fastener grade is always numeric and a chemical grade
  always alphabetic.
- **A shared designation is not interchangeability.** Two 6205 bearings rated
  200 kg and 500 kg agree on every field the designation encodes, and the first
  implementation called them `equivalent bidirectional`. Direction is now
  settled from the performance ratings whatever source produced the verdict —
  getting this backwards is an unsafe substitution, not a near miss.
- **A designation is not evidence about what it does not encode.** A metric
  thread says nothing about a bolt's grade or material, so designation-based
  equivalence now requires the remaining identity-critical attributes to be
  comparable and to agree.

Equivalence ground truth was also recomputed. The seed originally recorded only
the planted traps, while the generator naturally produces thousands of genuinely
equivalent pairs — two valves alike but for their temperature rating, say.
Measured against that incomplete truth, precision read 0.07 for an engine that
was largely right. Truth is now computed exhaustively over the product
population and expanded across renderings at measurement time, which moved
precision to 0.90.

### M4 findings

- **Two of the three workbench tabs were permanently empty.** Review tasks were
  created only for grey pairs, so Auto-high and Auto-low showed nothing. An
  automation rate is only meaningful if a human can sample what was automated,
  so tasks are now created for every auto-accepted pair and for the 500 closest
  auto-refused ones — the refusals most worth spot-checking.
- **Rejecting an automatic merge changed nothing but a flag.** Overturning a
  decision now splits the cluster back apart, which is what the reviewer's "no"
  is asking for.
- **Merging a cluster orphaned its review tasks** (`review_task.cluster_id`
  referenced the deleted source, raising a foreign-key error). Tasks now follow
  the items into the surviving cluster.
- **`rebuild_golden` flushed a golden record before setting its NOT NULL
  description.** Every column is now set before the insert.

### Measurement honesty

- Thresholds come from `make tune`, which sweeps on the **60% tuning split**
  and prints the table. The chosen value is frozen in `match.T_HIGH`.
- Every number in `GET /api/metrics` and in `make demo` is from the **40%
  held-out split**. A pair counts only when both its items are held out.
- Blocking configuration was selected on tuning recall (0.9853) and reports
  held-out separately (0.9836).
