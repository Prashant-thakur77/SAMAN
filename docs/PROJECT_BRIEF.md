# SAMAN — project brief for a collaborator

*Read this first if you are joining the project (a person or an AI assistant).
It is the whole thing in one document: the problem, what we built, how it is
built, the rules we work by, and where it stands today. Details live in the
files it points to; nothing here contradicts them, and where they differ the
code and its tests are the truth.*

Repository: `https://github.com/Prashant-thakur77/SAMAN` (branch `main`).
Live demo: `https://saman-wymm.onrender.com` (Render free tier, auto-deploys
from `main`; cold start ~40 s after idle). Owner: Prashant Thakur, SIH 2026 team.

---

## 1. The problem (SIH 2026 · SIH26099)

**Ministry of Petroleum & Natural Gas, problem posted through CPCL (Chennai
Petroleum Corporation Limited).** Title, in the ministry's words: an *AI-based
platform for standardisation of material codes across CPSEs*.

**Background.** Every Central Public Sector Enterprise (CPSE) — IOCL, CPCL,
GAIL, ONGC, BPCL, HPCL, SAIL … — keeps its own material master in its own ERP
(mostly SAP). The same physical item is catalogued differently in each: `BALL
BEARING SKF 6205-2Z` in one, `BRG,BALL,6205ZZ,SKF` in another, `बेयरिंग 6205 ZZ
SKF` in a third, and often more than once inside a single company. Because
nobody can tell that these are one material, CPSEs cannot see each other's
stock, cannot buy together, pay different prices for the same part, hold dead
stock of what a sister company is short of, and raise new codes for materials
that already exist. Master data is noisy: abbreviations, house styles, Hindi
tokens, missing part numbers, unit-of-measure and pack-size confusion.

**What the problem statement asks for** (each row is also a row of the
traceability table in `README.md`):

1. AI-based matching of descriptions and specifications across CPSEs
2. Identification of duplicate, near-duplicate and functionally equivalent materials
3. Automated standardisation of descriptions and technical attributes
4. Intelligent classification and categorisation
5. Generation / recommendation of a **Common National Material Code**
6. Mapping of existing CPSE codes to the common code
7. Legacy code rationalisation and migration support
8. User validation and approval workflow for AI recommendations
9. Dashboards for material-master analytics and duplicate detection
10. Audit trail and governance
11. Integration capability with the CPSEs' SAP/ERP systems
12. Analysis of historical procurement data
13. Units-of-measurement harmonisation

**Expected impact named by the ministry:** inventory optimisation and
visibility, inter-CPSE collaboration (joint tenders, stock sharing), faster
procurement and specification finalisation, a foundation for strategic
sourcing.

**Constraints we set ourselves from the start (and the judges reward):**
government data cannot leave the premises, so everything must run **offline on
a laptop**; every figure on every screen must be **computed, never invented**;
every AI decision must carry **evidence a person can read**; a human, not a
model, makes the final call on identity; and every mutation is **audited**.

---

## 2. The solution in one paragraph

**SAMAN** (Standardised Asset & Material Analysis Network; tagline *One
Nation, One Material Code*) ingests each CPSE's catalogue (CSV or `.xlsx`,
including SAP's split short/long text), normalises and classifies every row,
extracts technical attributes, and runs a **tiered matching engine** (anchor
keys → probabilistic linkage → semantic similarity) whose candidates all pass a
**hard-constraint veto layer** that refuses a merge when an identity-critical
attribute differs, no matter how similar the text reads. Duplicates cluster
into one **golden record** per real material with per-field provenance;
functional equivalents (another manufacturer's interchangeable part) are a
*separate, directed relation*, never merged. Uncertain pairs go to a
keyboard-first **Workbench** where stewards decide; every decision is a label
that retrains a small, readable model that orders the queue and never decides.
A registrar issues the **CNMC** (`CCCC-SSS-NNNNNN-K`, Damm check digit,
immutable). Around that core: a reversible ERP **migration** (plan → dry run →
apply → rollback), **Smart-Create** that stops duplicates at the point of
creation, executive and opportunity **dashboards** (joint tenders, price
variance, transfers, dead stock, data quality), per-CPSE and ministry
**reports**, a phone **Scan** screen and printable bin labels, a **restricted
mode** that finds overlaps across CPSEs without exchanging plaintext, an
**assistant** that navigates, explains and answers from the project's own
documents, and a hash-chained **audit ledger** behind everything. It runs on a
laptop with no network; a language model is optional and only ever rephrases
or explains, never decides.

**Headline numbers (held-out 40 % of ground truth, synthetic estate of
~11,800 rows across 4 CPSEs; all reproducible with `make demo`):** duplicate
precision **0.997**, recall **0.960**; cluster-level B-cubed P 0.999 / R 0.983;
blocking recall **0.994**; veto precision on 1,020 planted near-miss pairs
**1.000**; equivalence P 0.927 / R 0.944, direction accuracy 0.990; automation
rate 0.994 (3,778 pairs left for humans). The naive baseline (exact normalised
text) finds 3 % of duplicates. The gates also pass on the 156k-row benchmark
profile. **All data is synthetic** and every screen says so.

---

## 3. Who uses it (roles) and the seeded demo accounts

All seeded accounts use the password `demo` (demo mode only; the login page
says so). Role is what the API enforces; the UI only reflects it.

| Account | Role | Sees / may do |
|---|---|---|
| `registrar@min.gov.in` | registrar | everything; issues CNMCs; sets policies; Admin page |
| `admin@saman.gov.in` | admin | users, health, snapshot, reports; not code issue |
| `approver@min.gov.in` | approver | every CPSE's rows; decides conflicts; approves |
| `steward@cpcl.in`, `steward@iocl.in` | steward | own CPSE's rows and prices; the golden layer; other CPSEs' prices only as anonymised bands; Workbench decisions |
| `engineer@cpcl.in` | engineer | approves substitutes for the equipment they touch |
| `auditor@cag.gov.in` | auditor | read everything, change nothing |
| `viewer@min.gov.in` | viewer | golden layer and dashboards |

Row-level visibility (spec §0.9b) is one function, `visibility.redact_prices`,
used by dashboards, item page, migration planner, reports and Copilot alike, so
the Copilot cannot become a way around it. Separation of duties: whoever
proposed or edited a golden record may not approve/issue it.

---

## 4. Architecture and tech stack

**Monorepo**, one-command run: `make dev` (API `:8000`, UI `:5173`) or `docker
compose`. No cloud service is required for anything.

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, **SQLite** (`data/app.db`, WAL) | ~35 tables, 24 routers under `/api`; pytest (≈1,300 tests), ruff |
| Matching | rapidfuzz (Tier 1 fallback), **splink** (Fellegi–Sunter over DuckDB, Tier 1 primary when installed), scikit-learn TF-IDF char 3–5-grams + SVD(192) (Tier 2; sentence-transformers optional), pint (unit-aware comparison) | every optional engine degrades to a working fallback and `/api/health` says which is live |
| Language model (optional) | local **Ollama** (`qwen2.5:3b` default, 7B preferred when present) or a remote OpenAI-compatible endpoint (`SAMAN_LLM_URL/KEY/MODEL`); otherwise a deterministic adjudicator | only rephrases evidence or answers from the project's documents; every figure it emits is checked against its sources; "sovereign mode" switches it off entirely |
| Frontend | React 18, Vite 6, TypeScript, Tailwind (monochrome design tokens, two semantic tones), framer-motion, Recharts + hand-drawn SVG charts; no component library | vitest (137 tests); visual checks with Playwright (headless Chromium) |
| On-device | tesseract.js (OCR in the browser), zxing (barcode/QR), Web Speech fallback | the phone's image never uploads |
| Server-side optional | rapidocr (nameplate OCR), faster-whisper (speech in), piper (speech out) | `make deps-ocr / deps-stt / deps-tts` |
| Deployment | `deploy/single/Dockerfile` (one image: uvicorn serves API + built UI + demo DB; `render.yaml` Blueprint), `deploy/` compose stack with Caddy (+ optional local Ollama profile), ngrok/cloudflared tunnels for laptop demos | Render free plan: 512 MB, 0.1 CPU; dashboards are memoised and warmed at start for it |
| Licences | permissive only; `make licenses` regenerates `THIRD_PARTY_LICENSES.md` and fails CI on GPL/AGPL in the required set | |

**Repository layout**

```
backend/app/            FastAPI app; one module per concern (see §5), routers/ per screen
backend/app/data/       taxonomy (classes.yaml), abbreviations, brands, bearing tables, llm_eval.yaml
backend/tests/          pytest suites (one file per module/screen)
backend/scripts/        screenshots.py (README images from the real UI), licenses.py
frontend/src/routes/    one file per screen; components/, lib/api.ts (typed client)
frontend/public/ocr/    self-hosted tesseract.js worker + eng.traineddata.gz
deploy/                 compose stack, Caddyfile, single-image Dockerfile, HF/Render notes
docs/                   REFINEMENT_PLAN.md (what is done/next), ROADMAP.md, sap-integration.md, screenshots/
data/                   app.db, erp_mock.db, models/ (pairwise.json, embedder.joblib), outbox/, snapshot/, eval/
SAMAN_CLAUDE_CODE_SPEC.md   the original build spec (§ numbers quoted everywhere)
README.md               the long-form technical document (1,400 lines; results, screens, traceability)
KNOWN_GAPS.md           honest list of what is not built or built only as far as stated
```

---

## 5. How the engine works (the part judges ask about)

**Ingest & normalise** (`ingest.py`, `normalize.py`, `extract.py`, `taxonomy.py`).
CSV or `.xlsx` with header auto-mapping (SAP names like `MATNR`, `MAKTX`
recognised; a long-text sheet joined by material code). Normalisation: NFKC,
Hindi domain terms → English, Devanagari transliteration, whole-token
abbreviation expansion (`BRG`→`BEARING`, 198 rules), separators, UoM
canonicalisation with `pack_qty`. Classification into 8 classes
(`bearing.ball.deep_groove`, `valve.gate`, `gasket.spiral_wound`,
`pipe.seamless`, `fastener.bolt.hex`, `cable.power`, `chemical.reagent`,
`ppe.helmet`) with a confidence gate; low-confidence rows go to an anchor-key
only pool. Attribute extraction per class schema (bore/OD/width from a bearing
designation, size/class/material for a valve, …), each attribute tagged
`identity_critical`, `performance_band` or `cosmetic`.

**Blocking** (`blocking.py`): seven passes (anchor keys, class + defining
attribute, identity signature, brand tokens, MPN prefix, ANN over text
vectors, …) → 0.994 recall of true pairs while scoring a small fraction of all
pairs. The identity-signature pass is what made the 156k-row profile pass.

**Tiers** (`match.py`, `linkage.py`, `embed.py`):
- **Tier 0 anchors** — normalised MPN, validated GTIN, exact normalised-text hash.
- **Tier 1 linkage** — splink (Fellegi–Sunter, DuckDB) with rapidfuzz features; rapidfuzz-only fallback. Both meet the gate; the health page names which is live.
- **Tier 2 semantic** — TF-IDF char 3–5-grams + SVD cosine (sentence-transformers if installed). The fitted embedder is persisted (`data/models/embedder.joblib`) so Smart-Create probes use the pipeline's vector space.
- **Veto layer** (`compare.py`, spec §2A) — applied to *every* candidate including anchor matches: an identity-critical attribute that differs (bore 25 mm vs 30 mm) refuses the merge whatever the text score; a performance attribute outside its band refuses; inside the band merges. Same part number with conflicting specification = **conflict**, routed to an approver, never merged or dropped.
- **Bands** — confidence ≥ 0.86 auto-merge (still queued for policy confirmation), 0.45–0.86 grey (a person decides), < 0.45 auto-reject (a sample queued for audit). Thresholds tuned on the 60 % split only (`make tune`).
- **Tier 3 adjudication** (`adjudicate.py`) — a deterministic recommendation with reasons for every grey pair (`lean_merge / lean_review / lean_split / flag_conflict`); a language model may only rephrase it, and its output is discarded if it introduces a figure not in the evidence.
- **Tier 4 equivalence** (`equivalence.py`, spec §2B) — a separate directed relation (SKF ↔ FAG ↔ NSK 6205; class 600 valve can replace class 300, not the reverse) proposed by rules, approved by an engineer per equipment; never a merge.

**Clustering & golden records** (`cluster.py`, `standardize.py`): connected
components of accepted pairs, one golden record per cluster rendered from a
class template, attribute fusion by four stated rules with per-field
provenance (which member, which rule), UNSPSC and HSN on every class.

**Learning loop** (`learn.py`): every Workbench approve/reject is a label; a
24-feature standardised logistic regression (saved as readable JSON) orders the
grey queue by uncertainty with a random fifth mixed in; champion/challenger
auto-retrain every 25 reviewer labels, promoted only if not worse on held-out
(AUC 0.9986); trains on reviewer labels alone once they outnumber the
simulated ones; per-class metrics and an out-of-sample confusion matrix on
real labels; threshold suggestions are shown, never applied. **It never
decides.**

**CNMC** (`cnmc.py`): `CCCC-SSS-NNNNNN-K` — family, segment, serial issued
once and never reused, Damm check digit (catches every single-digit error and
adjacent transposition; Luhn does not). Registrar-only, or under a per-family
**auto-issue policy** (`autoissue.py`) with three stated gates (anchored pairs
in full agreement; class held-out precision ≥ target; no grey task pending),
off by default, issued in the name of the registrar who set it.

**Evaluation** (`metrics.py`, `tuning.py`): ground truth split 60/40; every
reported number is held-out; pairwise + B-cubed + blocking recall + veto
precision + equivalence + per-class with the worst class named + the naive
baseline; snapshot recorded on the run and read by the dashboard, never
recomputed per request.

---

## 6. The screens (all under one React shell; `/api/...` behind each)

| Route | What it does |
|---|---|
| `/welcome`, `/login` | public front page and sign-in (account picker in demo mode); the assistant is available here and sends visitors to sign in for anything inside |
| `/` Home | role-specific: queue size, own-CPSE report card, dashboards |
| `/search` | every catalogue, read like a description (abbreviations expanded and said so, Hindi), relevance order, did-you-mean, recent searches; row opens a drawer; `⌘K` opens the same search anywhere |
| `/items/:id`, `/clusters/:id` | one row / one material: golden record with provenance, every CPSE's code under one CNMC, duplicates vs equivalents in separate blocks, stock, last price and trend, installed-on equipment; edit, merge, split, issue |
| `/compare?a=&b=` | any two rows scored now by the same matcher; nothing stored |
| `/workbench` | keyboard-first review over all three bands (`A R J K M U`), filters by class/CPSE/role, one-reason bulk decisions for the policy bands, five-minute undo, "why" on every card, seconds per decision recorded |
| `/substitutes` | equivalence proposals for an engineer to approve per equipment |
| `/dashboard/executive` | KPIs that reconcile with `/api/metrics`, progress by CPSE, harmonisation by family, class × CPSE heatmap, pipeline ladder, veto attributes, held-for-review, held-out scorecard, savings ladder, stock age, data-quality scorecard; every figure opens its rows; provenance line; print to PDF |
| `/dashboard/opportunity` | joint tenders with an adjustable capture assumption, price variance per base unit, vendor overlap, transfers, dead stock, ABC; purchase window selectable |
| `/copilot` | guarded natural-language questions: whitelisted parameterised queries or retrieval, never generated SQL, citations and the query shown, visibility applied; answers "why were X and Y not merged" |
| `/smart-create` | check a description (+ part number, barcode, UoM, or a photographed nameplate) before raising a code: reuse / equivalents / ruled-out with the attribute that refused each; create-anyway needs a reason; draft requests |
| `/scan`, `/labels/:code` | phone camera, barcode gun or typed code → the material, its stock across CPSEs, substitutes; wrong-item report; printable QR + Code 128 label |
| `/onboard` | register a CPSE, upload CSV/xlsx, confirm column mapping, dry run, ingest, run the pipeline with progress |
| `/migration` | plan → dry run (LSMW/LTMC load files) → impact → apply to the (mock) ERP → verify → rollback; open POs auto-held |
| `/pprl` Restricted mode | overlap between two CPSEs from Bloom-filter fingerprints of normalised attributes, no plaintext exchanged |
| `/audit` | the hash-chained ledger, verified from the UI (`GET /api/audit/verify` names the first broken sequence) |
| `/admin` | users and roles with activity, sovereign mode, engine health and "what runs where", demo snapshot/restore, reports (per CPSE + ministry roll-up), auto-issue policy, retraining panel |
| Assistant (floating, every screen) | navigate ("open cluster 268", "वर्कबेंच खोलो"), explain (topic cards), query (hands to the Copilot), or answer from the documents via the model, streamed a checked sentence at a time with clickable sources; voice in/out kept on the machine; `?` opens keyboard help anywhere |

---

## 7. Security and data-sovereignty story

- **Front door:** only health, auth, bootstrap and the assistant's public
  endpoints are reachable without a session; a test walks every registered
  route and fails if a new one is not either behind `require_user` or listed
  public on purpose. Signed cookies (timed), login throttling, security headers,
  HSTS when secure cookies are on.
- **Row-level visibility** (§3) for prices and valuations; the Copilot and
  the reports apply the same function.
- **Audit chain:** every mutation (decisions, undo, merges, splits, code
  issue, policy changes, sign-ins, report sends, snapshot/restore, scan
  reports) is an `audit_event` whose hash covers its own sequence number, so
  reordering and tampering are both detected.
- **No network at runtime by design:** fonts and OCR models self-hosted; the
  remote model is an explicit operator choice labelled on the health chip;
  sovereign mode ignores any model.
- **Restricted mode** answers "which materials do we both hold?" without
  either CPSE handing over its catalogue.
- Never commit `deploy/.env`; API keys pasted during development (a Groq
  key, a Render key) are to be rotated after the event. Nothing in this repo
  contains a secret.

---

## 8. Working on the project — commands and rules

**Setup & run**

```
make setup            # backend venv (Python 3.12) + frontend deps
make demo             # seed synthetic estate, run the pipeline, print held-out metrics (~60 s)
make dev              # API :8000 (docs at /api/docs) + UI :5173
make check            # what CI runs: ruff, pytest, vitest, tsc, licence gate — must be green before every push
make demo-snapshot / demo-restore   # restore point for a live demo (~1 s)
make report / autoissue / llm-eval / learn / evaluate / seed-large / tune
```

Node lives at `/home/prashant/.nvm/versions/node/v22.22.3/bin` on the owner's
laptop (`export PATH=...:$PATH` before `npm`/`npx`). Playwright's Chromium is
at `~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome`.

**Rules we do not break** (from the spec §10 and our own practice):

1. **Never invent data.** No hard-coded metrics, no mocked "AI" output, no
   placeholder savings. If something is not computed, show an honest empty
   state and say "synthetic" where the data is.
2. **No network calls at runtime** except an operator-configured model
   endpoint, labelled as such.
3. **Permissive licences only**; run `make licenses` after adding a dependency.
4. **Models never decide identity.** The veto layer is rules; the pairwise
   model orders; the language model writes and is checked.
5. **Verify UI changes visually** (Playwright screenshot) and keep tests green.
6. Short, plain commit messages that say what changed; **no attribution
   lines** in commits; push to `main` (Render deploys from it).
7. Record anything not built in `KNOWN_GAPS.md`; mark partial as partial.
8. Design: monochrome tokens, two semantic tones, IBM Plex, no component
   library, every chart hand-drawn or Recharts within the tokens.

**Where status lives:** `docs/REFINEMENT_PLAN.md` (stages 1–4, model items
L1–L17 / P1–P6, automation, reports, small add-ons, each marked done/next),
`KNOWN_GAPS.md`, and the traceability table at the end of `README.md`.

---

## 9. Where it stands (September 2026)

**Done and verified end to end** (backend ≈1,300 tests, frontend 137, all
green; live on Render): everything in §2–§7 above. Recent work, in order:
front door and security review; scan and labels; embedder persistence for the
free host; learning loop with champion/challenger; per-CPSE reports;
measured LLM harness, wider corpus, Hindi retrieval, answers in the question's
language, answer memo and streaming, answer log; Workbench filters, bulk
decisions, undo, "why"; CSV export, shortcut help, what-runs-where, demo
restore; provenance on dashboards, user activity; search read like a
description; scan history, torch, wrong-item report; Smart-Create barcode and
drafts; dashboard drill-down, own-CPSE fold, purchase window; compare any two
rows; assistant follow-ups and clickable sources; `.xlsx` onboarding with
long-text join; auto-issue policy; ministry roll-up; dormant-code retirement
suggestion; `make e2e` (the five demo moves in a real browser); stock-count
mode and bin binding on Scan; the Scan screen installable and working offline
(counts queue on the device); attachments on golden records; incremental
pipeline runs that keep every decision; vendors grouped by company and a
Vendors tab; the interface in Hindi at a click; house abbreviations taught per
CPSE; an install guide (`docs/INSTALL.md`).

**Next, from the plan:** local 3B/7B rows for the model harness (`make
llm-eval` with Ollama running); per-class threshold sweeps; price-anomaly
flags; class-template drafting for new families; a public GeM/CPPP corpus to
measure on real text; signed bundles between CPSE nodes; realised-savings
tracking once post-consolidation POs exist; a screen-reader walkthrough.

**Known limits worth saying out loud:** all data is synthetic (with full
ground truth, which is what makes the metrics honest); no live SAP has been
connected (the adapter, load files, RFC contract and BAdI hook exist and are
tested against a recorded fake); the language model is retrieval-grounded, not
fine-tuned, and the model that *is* trained is the small pairwise one; camera
OCR is measured on rendered nameplates, not warehouse photographs.

---

## 10. Demo flow (five moves, ~4 minutes)

1. **Search `6205`** — the same bearing under four names in four companies; open one, see every CPSE's code under one CNMC and the stock across the estate.
2. **Workbench, grey band** — a card that reads alike but the veto refused (bore 25 vs 30 mm); the deterministic "why"; approve one with `A`, take it back with `U`; the model's opinion that never decides.
3. **Smart-Create** — type a house-style description with a Hindi token (or scan a barcode): the existing coded material at 99.8 %, the equivalent from another manufacturer, the near-misses ruled out by name; save as a draft or reuse.
4. **Executive dashboard → Opportunity** — every figure computed and reconcilable, joint-tender savings under a stated capture assumption, transfers instead of purchases; click any bar to see the rows.
5. **Audit + Admin** — the hash chain verified live; what runs where (nothing leaves the machine); the per-CPSE report and the ministry roll-up; the auto-issue policy with its gates.

Related write-ups: `docs/ROADMAP.md` (beyond the hackathon: federation,
GeM/SAP integration, a national registry), `docs/sap-integration.md` (the
three integration doors), the demo scripts and pitch kept as Claude artifacts
by the owner.
