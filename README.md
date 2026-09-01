# SAMAN

**Standardised Asset & Material Analysis Network**
*One Nation, One Material Code*

SIH 2026 · Problem Statement **SIH26099** · Ministry of Petroleum & Natural Gas (CPCL)

SAMAN harmonizes material codes across Indian public-sector companies. The same
physical item is catalogued differently in every CPSE — `BALL BEARING SKF
6205-2Z` in one master, `BRG,BALL,6205ZZ,SKF` in another. SAMAN ingests those
catalogues, finds duplicates and functional equivalents, drafts one golden
record per real item, routes uncertain matches through human review, and issues
a **Common National Material Code (CNMC)** for each.

SAMAN is the platform. The CNMC is the code it issues.

Everything runs **offline on a laptop**. No cloud calls, no API keys, and every
optional dependency degrades to a working fallback rather than failing.

---

## Run it

```bash
make setup     # creates backend/.venv on Python 3.12, installs both apps
make demo      # seeds, runs the pipeline, prints the held-out metrics table
make dev       # API on :8000, UI on :5173
```

`make demo` exits non-zero if the §8 M3 gate is not met, so it doubles as the
quality check.

Sign in with any seeded account — `steward@cpcl.in`, `registrar@min.gov.in`,
`approver@min.gov.in` and others are listed on the login screen. Every one uses
the password `demo`.

Or with Docker:

```bash
docker compose up
```

| URL | What |
|---|---|
| http://localhost:5173 | SAMAN UI |
| http://localhost:8000/api/docs | API reference |
| http://localhost:8000/api/health | Active engine modes per tier |

`make help` lists every target.

### Optional accelerators

SAMAN runs at full function without these. Installing them upgrades two tiers:

```bash
make deps-optional   # splink (Tier 1) + sentence-transformers (Tier 2)
```

Without them SAMAN uses rapidfuzz linkage and TF-IDF character 3–5gram
embeddings, and says so at `/api/health` and in the top bar. A local
[Ollama](https://ollama.com) instance is picked up only if `OLLAMA_URL` is set;
otherwise Tier 3 uses a deterministic rule-based adjudicator.

The defaults are not a compromise: on this dataset rapidfuzz scores slightly
*higher* than splink at a third of the memory (see "Tier-1 engine" below), and
the gate is met either way. To force the fallbacks even with the accelerators
installed — useful for demonstrating degradation live:

```bash
SAMAN_DISABLE_OPTIONAL=true make demo
```

---

## Build status

Built milestone by milestone against `SAMAN_CLAUDE_CODE_SPEC.md`. Gaps are
tracked honestly in [`KNOWN_GAPS.md`](KNOWN_GAPS.md).

| Milestone | Scope | Status |
|---|---|---|
| M1 | Scaffold, design tokens, theme, shell, routing + transitions | **Done** |
| M2 | Models, auth, seed data, ingest, normalize, extract | **Done** |
| M3 | Embeddings, blocking, tiered match, veto layer, clustering, CNMC, metrics | **Done** |
| M3.4 | Golden-record standardization + provenance | **Done** |
| M3.5 | Functional-equivalence engine | **Done** |
| M4 | Workbench, decisions, role gates, audit chain | Not started |
| M5 | Executive + Opportunity dashboards | Not started |
| M6 | Copilot | Not started |
| M7 | Onboarding wizard, admin, audit explorer | Not started |
| M7.5 | Two-way ERP migration | Not started |
| M8 | Smart-Create, licensing artefacts | Not started |
| M8B | Demo survivability + performance | Not started |
| M9 | Motion polish, a11y pass, screenshots | Not started |
| M10 | PPRL restricted mode (stretch) | Not started |

---

## Data

`make seed` builds a synthetic estate with full ground truth, reproducibly from
a fixed seed. Nothing in the application ever reads the truth tables — only the
metrics do.

| | Demo profile (`make seed`) | Benchmark profile (`make seed-large`) |
|---|---|---|
| CPSEs | 4 — CPCL, IOCL, GAIL, ONGC | 6 — adds HPCL, SAIL |
| Raw catalogue rows | ~11,800 | ~156,400 |
| Items carrying a validated GTIN | ~2,300 | — |
| Ground-truth products | 7,000 | 14,161 |
| Planted near-miss traps | 400 products / 1,020 pairs | same |
| Purchase-history rows | ~21,300 | ~279,500 |
| Seed + normalize + extract | **2.4 s** | **29.5 s** (~5,300 rows/s) |
| Full pipeline (`make demo`) | **84 s** | not run — benchmark profile is for load testing only |

Measured on a laptop CPU, single process, no GPU. The demo profile is what every
screenshot, demo flow and metric gate uses; the benchmark profile exists only
for the §8A performance run.

Each of ~7,000 real products is rendered into 1–4 CPSE-specific descriptions
through per-CPSE style profiles: different abbreviation sets, attribute
orderings and unit spellings, an 8% typo rate, a 10% Hindi token mix, and an 8%
pack-basis quirk (`BOX OF 100` against `EA`). Ground truth records which rows
are the same product, which planted pairs the veto layer must refuse, and which
are directed substitutes.

Thresholds are tuned on a 60% split; every reported number comes from the
held-out 40% (§0.6).

---

## Results

Measured on the **held-out 40%** of ground truth. Thresholds are chosen by
`make tune`, which reads the 60% tuning split only — nothing below was tuned
against these numbers.

| M3 gate (spec §8) | Result | Target |
|---|---|---|
| Duplicate precision | **0.975** | ≥ 0.92 |
| Duplicate recall | **0.938** | ≥ 0.80 |
| Blocking recall | **0.984** | ≥ 0.97 |
| Veto precision on planted traps | **1.000** | ≥ 0.98 |

A single averaged number would hide more than it shows, so the full report at
`GET /api/metrics` also carries:

| | Precision | Recall | F1 |
|---|---|---|---|
| Pairwise | 0.975 | 0.938 | 0.957 |
| **B-cubed (cluster level)** | 0.992 | 0.974 | 0.983 |
| Naive baseline: exact text match | 1.000 | 0.032 | 0.061 |

Pairwise scores can look excellent while clusters are catastrophically
over-merged, so B-cubed is reported beside them. The baseline is what a plain
exact-match de-duplication achieves on the same data: it is perfectly precise
and finds 3% of the duplicates.

### Tier-1 engine: splink or rapidfuzz

§0.4 specifies splink for Tier-1 probabilistic linkage with a rapidfuzz
fallback. Both are implemented, and **both meet the gate on the same frozen
threshold**. Measured on the demo profile, same machine:

| Tier-1 engine | Precision | Recall | F1 | Wall clock | Peak memory |
|---|---|---|---|---|---|
| splink (Fellegi–Sunter) | 0.970 | 0.935 | 0.952 | 68 s | 5.0 GB |
| **rapidfuzz (default)** | **0.975** | **0.938** | **0.957** | **45 s** | **1.6 GB** |

The fallback wins on every axis here, so it is what `make demo` runs and what
the demo uses. That is not a criticism of splink — it is what this dataset
looks like. The veto layer and attribute agreement do most of the
discriminating work, which leaves Tier 1 supplying a similarity signal, and
splink compares descriptions with Jaro-Winkler (order-sensitive) where
rapidfuzz uses `token_set_ratio` (order-insensitive) — and the CPSE style
profiles reorder attributes deliberately.

splink is a real code path, not a credit in a table: `make deps-optional`
installs it, `/api/health` reports which engine is live, and its
Fellegi–Sunter match weights and per-comparison waterfall are persisted into
the evidence object. `SAMAN_DISABLE_OPTIONAL=true` forces the fallbacks even
when the accelerators are installed, so graceful degradation can be shown live.

### Standardization

Duplicate detection is half the job; the platform also has to produce the clean
record that replaces them. Three CPSE renderings of one valve — different
abbreviations, two typos, a barcode — become one canonical description:

```
GATE 150NB CL 150 CI THRD 19.6 BAR 200 C VLV FLOWSERVE ... BARCODE 8908440682867
VALVE GATE 150NB CLASS 150 CI TTHREADED 19.6 BAR 200 C FLOWSERVE FLO-GV01634
VLV,GATE,150NB,CL 150,CI,THRD,19.6 ABR,200 C,FLOWSERVE
  ->  VALVE, GATE, 150NB, CLASS 150, CI, THREADED, FLOWSERVE FLO-GV01634
```

Rendering is a deterministic function of the class template and the fused
attributes, so the same cluster always yields byte-identical text — a golden
record an ERP keys against cannot drift between runs. Conflicting values are
resolved by the §2D rules in order (highest-confidence extraction, then
majority vote, then most recent purchase, then most precise value), and every
fused field records which member it came from and which rule chose it.

An unresolved disagreement on an identity-critical attribute does **not**
auto-approve: the cluster is flagged and routed to a steward, and `POST
/api/cnmc/issue` refuses it with 409. On the demo profile 870 of 7,107 clusters
are held back this way, every one of them a same-part-number-different-
specification data-quality error rather than a matching failure.

### Equivalence is not duplication

A duplicate is symmetric and gets merged into one CNMC. An equivalent is
**directed** and keeps its own: a 500 bar valve can stand in for a 300 bar
requirement, and the reverse is unsafe. Collapsing the two would erase a
distinction CPSE material masters genuinely carry, so they are separate
relations with separate metrics.

Four evidence sources, in precision order — a published OEM interchange, a
parsed standard designation, a per-class substitution rule, and (from M6) an
LLM that may only *propose*:

| | Held-out |
|---|---|
| Precision | 0.902 |
| Recall | 0.607 |
| **Direction accuracy** | **0.987** |
| Candidate coverage | 0.796 |
| Recall of reachable pairs | 0.762 |

Recall is reported with its ceiling rather than on its own: 20% of true
equivalence pairs never reach the engine because blocking is tuned for
duplicates, and of those that do, some lack the extracted attributes to decide.
Direction accuracy is the number that matters most — a substitution proposed the
wrong way round is unsafe, not merely wrong.

Rules are data, not code. A steward reads and edits them through `GET/POST
/api/rules`:

```yaml
- class: bearing.ball.deep_groove
  equivalent_if: [bore_mm ==, outer_dia_mm ==, width_mm ==, seal_type ==]
  substitutable_if: [load_rating_kg >=, temp_max_c >=]   # directed: B substitutes A
  never_if: [material !=]
```

**Veto layer**, on the planted near-miss traps: 380 of 380 correctly refused.

| Trap | Accuracy |
|---|---|
| Identity-critical mismatch (bore 25 mm vs 30 mm) | 1.00 |
| Performance outside the band (200 kg vs 500 kg) | 1.00 |
| Cross-brand equivalent (SKF / FAG / NSK) | 1.00 |
| Directed substitute (class 300 vs 600) | 1.00 |
| Performance inside the band — must still merge | 0.89 |

Per class, the weakest is named rather than averaged away:
`bearing.ball.deep_groove` at F1 0.937, with every class above 0.93. Automation
rate is 0.995, leaving 3,606 pairs for human review.

---

## Problem-statement traceability

Every capability named in SIH26099, and where it lives in this build. Statuses
are kept honest — partial is marked partial.

| PS-stated capability | Where it lives | Status |
|---|---|---|
| AI-based matching of descriptions & specifications across CPSEs | tiered engine in `app/match.py` | **Done** — Tier 0 anchors, Tier 1 fuzzy, Tier 2 semantic, all veto-gated |
| Identification of duplicate, near-duplicate and equivalent materials | veto layer (`app/compare.py`) + relation engine (`app/equivalence.py`) | **Done** — duplicates P 0.98 / R 0.94; directed equivalence P 0.90 / R 0.61, direction accuracy 0.99 |
| Automated standardization of descriptions and technical attributes | class templates + attribute fusion + provenance | **Done** — deterministic rendering, 4-rule fusion, per-field provenance |
| Intelligent classification and categorization | taxonomy + class assignment with confidence gate | **Done** — 8 classes, confidence gate routes low-confidence rows to an anchor-key-only pool |
| Generation/recommendation of a Common National Material Code | `app/cnmc.py`, Damm check digit | **Done** — `CCCC-SSS-NNNNNN-K`, registrar-only, immutable once issued |
| Mapping of existing CPSE codes to the common national code | mapping block on the item page | Partial — every CPSE's legacy code is returned by `GET /api/clusters/{id}`; the item page lands in M4 |
| Legacy code rationalization and migration support | plan → dry-run → apply → rollback | Not started (M7.5) |
| User validation and approval workflow for AI recommendations | `/workbench` + separation of duties | Partial — separation of duties enforced (§0.9); workbench lands in M4 |
| Dashboard for material master analytics and duplicate detection | `/dashboard/executive`, `/dashboard/opportunity` | Not started (M5) |
| Audit trail and governance mechanism | hash-chained `audit_event` + `/audit` | Not started (M4) |
| Integration capability with SAP/ERP | `ErpAdapter` + mock ERP write-back | Not started (M7.5) |
| Analysis of historical procurement data | `purchase_history` → aggregation, variance, vendor overlap | Partial — data seeded and authoritative; analytics land in M5 |
| Units of measurement harmonization | base UoM + `pack_qty` in `app/normalize.py` | **Done** — pack size extracted, UoM canonicalized, unit-aware comparison via `pint` |
| Inventory optimization & visibility | consolidated stock, transfer suggestions, dead stock | Not started (M5) |
| Inter-CPSE collaboration | sharing engine + joint tenders | Not started (M5) |
| Faster procurement/specification finalization | Smart-Create + standardized specs | Not started (M8) |
| Foundation for strategic sourcing | vendor overlap + combined-volume analysis | Not started (M5) |

---

## Built with

Third-party dependencies and their licenses. All permissive — no GPL or AGPL.
`make licenses` regenerates [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)
from `pip-licenses` and `license-checker` (wired in M8).

| Library | License | Used for |
|---|---|---|
| [splink](https://github.com/moj-analytical-services/splink) | MIT | Tier-1 probabilistic record linkage (Fellegi–Sunter) and match-weight waterfall — **optional**, see "Tier-1 engine" above |
| [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz) | MIT | Tier-1 string/token similarity — the default engine |
| [sentence-transformers](https://www.sbert.net/) | Apache-2.0 | Tier-2 semantic embeddings (all-MiniLM-L6-v2) — **optional**; TF-IDF is the default |
| [scikit-learn](https://scikit-learn.org/) | BSD-3-Clause | TF-IDF fallback path, metrics |
| [duckdb](https://duckdb.org/) | MIT | analytics views backing the Copilot |
| [pint](https://pint.readthedocs.io/) | BSD-3-Clause | unit-aware numeric comparators |
| [FastAPI](https://fastapi.tiangolo.com/) · [SQLAlchemy](https://www.sqlalchemy.org/) · [Pydantic](https://docs.pydantic.dev/) | MIT / MIT / MIT | backend |
| [React](https://react.dev/) · [Vite](https://vite.dev/) · [Tailwind CSS](https://tailwindcss.com/) · [framer-motion](https://www.framer.com/motion/) | MIT | frontend |
| [IBM Plex](https://github.com/IBM/plex) via @fontsource | OFL-1.1 | self-hosted typography |
| [Ollama](https://ollama.com) + Qwen 2.5 | Apache-2.0 | optional local LLM tier |

**Deliberately excluded:** `zingg` (AGPL-3.0) — capable entity resolution, but
copyleft would encumber a government handover.

### What is original to SAMAN

The CNMC registry and its check-digit scheme; the tiered routing logic and its
hard-constraint veto layer; the directed functional-equivalence model (kept
deliberately separate from duplicate detection); the evidence cards; the review
workbench and its separation-of-duties model; the guarded Copilot; Smart-Create
duplicate prevention at source; the opportunity and inventory-sharing engines;
the two-way ERP migration with rollback; and the PPRL restricted mode. The
libraries above are engines used inside that architecture — no existing
application was forked or adapted as a base.

---

## Design

Monochrome, typography-first, built to read as a government instrument rather
than a SaaS product. IBM Plex Sans and Plex Mono, self-hosted. Two semantic
colours only — one for confirmation, one for refusal — used as text and dots,
never as fills. Dark and light modes. No component library: every primitive in
`frontend/src/components/primitives/` is hand-built. Motion follows a single
easing curve and collapses to opacity-only under `prefers-reduced-motion`.

## License

MIT.
