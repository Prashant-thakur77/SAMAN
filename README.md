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
make seed      # generates the synthetic catalogue estate (~12k items, 4 CPSEs)
make dev       # API on :8000, UI on :5173
```

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

Without them SAMAN degrades to rapidfuzz-only linkage and TF-IDF character
3–5gram embeddings, and says so at `/api/health` and in the top bar. A local
[Ollama](https://ollama.com) instance is picked up only if `OLLAMA_URL` is set;
otherwise Tier 3 uses a deterministic rule-based adjudicator.

---

## Build status

Built milestone by milestone against `SAMAN_CLAUDE_CODE_SPEC.md`. Gaps are
tracked honestly in [`KNOWN_GAPS.md`](KNOWN_GAPS.md).

| Milestone | Scope | Status |
|---|---|---|
| M1 | Scaffold, design tokens, theme, shell, routing + transitions | **Done** |
| M2 | Models, auth, seed data, ingest, normalize, extract | **Done** |
| M3 | Embeddings, blocking, tiered match, veto layer, clustering, CNMC, metrics | Not started |
| M3.4 | Golden-record standardization + provenance | Not started |
| M3.5 | Functional-equivalence engine | Not started |
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
| Ground-truth products | 7,000 | 14,161 |
| Planted near-miss traps | 400 products / 1,020 pairs | same |
| Purchase-history rows | ~21,400 | ~279,500 |
| Seed + normalize + extract | **2.4 s** | **29.5 s** (~5,300 rows/s) |

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

## Problem-statement traceability

Every capability named in SIH26099, and where it lives in this build. Statuses
are kept honest — partial is marked partial.

| PS-stated capability | Where it lives | Status |
|---|---|---|
| AI-based matching of descriptions & specifications across CPSEs | tiered engine in `app/match.py` | Not started (M3) |
| Identification of duplicate, near-duplicate and equivalent materials | veto layer (`app/compare.py`) + relation engine | Not started (M3, M3.5) |
| Automated standardization of descriptions and technical attributes | class templates + attribute fusion + provenance | Not started (M3.4) |
| Intelligent classification and categorization | taxonomy + class assignment with confidence gate | **Done** — 8 classes, confidence gate routes low-confidence rows to an anchor-key-only pool |
| Generation/recommendation of a Common National Material Code | `app/cnmc.py`, Damm check digit | Not started (M3) |
| Mapping of existing CPSE codes to the common national code | mapping block on the item page | Not started (M3.4) |
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
| [splink](https://github.com/moj-analytical-services/splink) | MIT | Tier-1 probabilistic record linkage (Fellegi–Sunter), blocking, match weights |
| [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz) | MIT | fast string/token similarity features |
| [sentence-transformers](https://www.sbert.net/) | Apache-2.0 | Tier-2 semantic embeddings (all-MiniLM-L6-v2) |
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
