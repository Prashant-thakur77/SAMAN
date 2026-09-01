# CLAUDE CODE BUILD SPEC — SAMAN
### Standardised Asset & Material Analysis Network
**SIH 2026 · Problem Statement SIH26099 · Ministry of Petroleum & Natural Gas (CPCL)**
*Tagline: "One Nation, One Material Code" — SAMAN issues the CNMC for every item.*

You are building a **fully functional local prototype** of an AI platform that harmonizes material codes across Indian public-sector companies (CPSEs). Same physical item, different codes/descriptions in every company ("BALL BEARING SKF 6205-2Z" vs "BRG,BALL,6205ZZ,SKF") → this platform ingests catalogs, finds duplicates/equivalents, drafts one golden record + a Common National Material Code (CNMC) per real item, routes matches through human review, and exposes dashboards + a chat copilot on top.

Everything must run **offline on a laptop** with one command. No cloud calls by default. Graceful degradation everywhere.

**How to use this spec (read first):**
- Build **milestone by milestone** (§8). After each milestone: run the tests, commit, and report status — do not run ahead.
- **Do not proceed past M3 until the §0.6 metrics are actually met on the held-out set.** Report the numbers; if a target is missed, tune and re-report rather than moving on.
- Where this spec gives a target number, an acceptance criterion, or a "must", treat it as a test to write — not prose. Every AC in §6 and every "Acceptance:" line in §2A–§2C becomes a pytest or a Playwright-style check.
- If you believe a requirement here is wrong or infeasible, say so and propose an alternative **before** implementing something different. Never silently substitute.
- Prefer boring, readable code over cleverness: this is a demo that six students must be able to explain line-by-line to government evaluators.

---

## 0. Hard requirements (non-negotiable)

1. Monorepo, one-command run: `docker compose up` AND a no-docker path (`make dev` → backend :8000, frontend :5173).
2. Backend: **Python 3.12 + FastAPI + SQLAlchemy + SQLite** (file db at `./data/app.db`). No Postgres for the prototype.
3. Frontend: **React 18 + Vite + TypeScript + Tailwind + framer-motion**. No component library (build primitives ourselves — this is a design-led prototype).
4. Matching stack with graceful degradation:
   - Tier 0: exact anchor keys — normalized **MPN/OEM part number** and **GTIN** (highest-precision real-world keys), plus normalized text hash.
   - Tier 1: probabilistic linkage — **`splink`** (MIT, DuckDB backend) with blocking rules on (class, brand-token, mpn-prefix) and `rapidfuzz` token_set_ratio comparison features. If splink is unavailable, degrade to rapidfuzz-only scoring and report it at `/api/health`.
   - Tier 2: semantic — `sentence-transformers` (`all-MiniLM-L6-v2`) if importable; **else fall back to scikit-learn TF-IDF char 3-5grams cosine**. Detect at startup, expose which mode is active at `GET /api/health`.
   - **Hard-constraint VETO (non-negotiable, applied to candidates from EVERY tier — including Tier-0 anchor keys):** see §2A. Similarity never overrides a veto. Special case: an anchor-key match (same MPN) whose identity_critical attributes conflict is a **data-quality error**, not a match — flag it `conflict` into the review queue with both values shown; never silently merge and never silently drop.
   - Tier 3 (optional): LLM adjudication via **Ollama** if `OLLAMA_URL` env is set (model `qwen2.5:7b` or `llama3.1:8b`); **else a deterministic rule-based adjudicator** (attribute-overlap scoring). The demo must never break without Ollama.
   - **Tier 4 — Equivalence engine (separate relation, see §2B).** Duplicate detection and functional-equivalence detection are DIFFERENT problems and must not share a code path.
5. Seeded synthetic data with ground truth (see §7). Metrics vs truth must be computable: `GET /api/metrics` returns precision/recall/F1 of current clustering.
6. **Evaluation must be honest (graded):** split the ground truth into a **tuning set (60%) and a held-out set (40%)**; all thresholds are tuned only on the tuning set and every reported number comes from held-out. `GET /api/metrics` reports, on held-out: pairwise precision/recall/F1, **cluster-level B-cubed precision/recall** (pairwise metrics can look excellent while clusters are badly over-merged), blocking recall, veto precision, equivalence precision/recall + direction accuracy, per-class breakdown with the **worst-performing class named explicitly**, and a **naive baseline** (exact normalized-text match) alongside ours so the lift is visible. Never report a single averaged number alone.
7. All AI decisions produce an **evidence object** (per-tier scores, matched attributes, source rows) persisted and shown in UI.
8. Hash-chained audit log: every mutation writes an event with `sha256(prev_hash + payload)`; `GET /api/audit/verify` re-walks the chain.
9. Roles via lightweight session auth (no Keycloak in prototype): seeded users, login screen = pick user + password `demo`. Roles: `registrar`, `admin`, `approver`, `steward`, `auditor`, `viewer`. Enforce on API (dependency) and UI (route guards). **Separation of duties: the user who proposes or edits a golden record cannot be the user who approves it** (API rejects self-approval with 409 and an explanatory message); CNMC issuance is registrar-only. Record `proposed_by` and `approved_by` separately on every decision.
9a. **Audit chain must resist tampering AND reordering:** each event stores `seq`, `ts`, `prev_hash`, and `hash = sha256(seq || prev_hash || canonical_json(payload))`, starting from a genesis event. `GET /api/audit/verify` re-walks the chain and reports the first break with its `seq`. Deletions are never physical — they are `void` events referencing the original. Include a pytest that mutates a payload directly in the DB and asserts verification fails at the right sequence number.
9b. **Data-visibility policy (state it in the UI, judges will ask):** a CPSE steward sees their own raw rows plus the shared golden layer; **raw per-CPSE prices of other CPSEs are visible only to the registrar/auditor roles**, while stewards see anonymized aggregates ("market range ₹X–₹Y, n=4 CPSEs"). Enforce this in both the API and the Copilot's SQL views — the Copilot must not become a bypass for row-level security. Add a test that a steward-scoped Copilot question about another CPSE's price returns aggregates only.
10. Accessibility: keyboard-first workbench, visible focus rings, WCAG AA contrast, `prefers-reduced-motion` respected.
11. README with screenshots, run instructions, demo script.

---

## 1. Design system — minimalist monochrome, gov-grade

Inspiration: **GOV.UK Design System** (typography-first, black-on-white sobriety), **USWDS** density, data.gov.in restraint. The app should feel like a serious government instrument, not a SaaS toy.

### 1.1 Tokens (CSS variables, Tailwind config)
Light mode:
- `--bg: #FFFFFF`, `--surface: #FAFAFA`, `--ink: #0A0A0A`, `--muted: #525252`, `--hairline: #E5E5E5`, `--inverse: #0A0A0A` (buttons: black bg, white text)
Dark mode:
- `--bg: #0A0A0A`, `--surface: #121212`, `--ink: #FAFAFA`, `--muted: #A3A3A3`, `--hairline: #262626`, `--inverse: #FAFAFA` (buttons: white bg, black text)
Functional color is rationed to TWO semantic tones used only for decisions/status text+dot, never large fills:
- `--ok: #15803D` (dark mode `#4ADE80`), `--danger: #B91C1C` (dark mode `#F87171`)
Everything else is grayscale. No gradients, no shadows except a 1px hairline + subtle `shadow-sm` on overlays.

### 1.2 Branding
- Product name **SAMAN** everywhere (wordmark, page title, README, API title, footer). Expand once on the login screen as "Standardised Asset & Material Analysis Network"; tagline under it: "One Nation, One Material Code".
- SAMAN is the *platform*; **CNMC** is the *code it issues* — never use them interchangeably in UI copy.
- Wordmark: `SAMAN` in Plex Sans, `tracking-[0.18em]`, uppercase, 20px; no logo image.

### 1.3 Type & layout
- Fonts: **IBM Plex Sans** (UI) + **IBM Plex Mono** (codes, CNMC, SQL, evidence). Self-host via `@fontsource`.
- Scale: 12 / 14 / 16 / 20 / 28 / 40. Micro-labels: 11px uppercase, `tracking-[0.08em]`, muted.
- 8px spacing grid. Content max-width 1280px. Dense data tables: 40px rows, hairline dividers only.
- Shell: left sidebar (240px, collapsible to 64px icon rail) + top command bar (global search input, ⌘K opens it, theme toggle, user chip). Page header pattern: uppercase micro-label (section) → H1 → one-line description → actions right.
- CNMC codes always rendered in Plex Mono inside a 1px-border chip.

### 1.4 Dark/light mode
- Class strategy (`<html class="dark">`), toggle in command bar, persisted to `localStorage`, defaults to `prefers-color-scheme`. Theme swap animates via 150ms opacity crossfade on a full-screen overlay (not per-element transitions).

### 1.5 Motion spec (framer-motion; this is a graded feature)
- Route transitions: outgoing fades 120ms; incoming **slides in from right x:24→0 + opacity 0→1, 240ms, easing `[0.22, 1, 0.36, 1]`**.
- Side panels/drawers (item detail, evidence): slide from right (`x: 100%→0`, 280ms, same easing) with scrim fade.
- Tables/lists: stagger children 20ms, y:8→0.
- Workbench card decision: on Approve, card slides right + fades; on Reject, slides left + fades (160ms); next card rises y:12→0.
- KPI numbers: count-up on mount (400ms). Charts draw-in once.
- Command palette (⌘K): scale 0.98→1 + fade, 150ms.
- All motion wrapped so `prefers-reduced-motion` reduces to opacity-only.

---

## 2A. Attribute comparators & the hard-constraint veto layer

Text similarity cannot tell a 6205 bearing rated 200 kg from one rated 500 kg. This layer is how we answer that question, and it is graded.

**Every attribute in every class schema (see §7 seed) declares:**
```yaml
bore_mm:      {type: numeric, unit: mm, role: identity_critical, tolerance: 0}
outer_dia_mm: {type: numeric, unit: mm, role: identity_critical, tolerance: 0}
load_rating_kg: {type: numeric, unit: kg, role: performance, tolerance_pct: 5, direction: higher_ok}
pressure_bar: {type: numeric, unit: bar, role: performance, tolerance_pct: 5, direction: higher_ok}
temp_max_c:   {type: numeric, unit: C, role: performance, tolerance_pct: 10, direction: higher_ok}
seal_type:    {type: enum, role: identity_critical, values: [ZZ, 2RS, open]}
material:     {type: enum, role: identity_critical}
brand:        {type: categorical, role: cosmetic}
colour:       {type: categorical, role: cosmetic}
```

Roles:
- `identity_critical` — MUST match exactly (after unit normalization). **Any mismatch = veto: the pair can never be a duplicate**, no matter the embedding score. Bore, thread size, flange rating, voltage, schedule, seal type.
- `performance` — compare with a **tolerance band** (`tolerance_pct` or absolute `tolerance`). Inside band → treated as equal for duplicate purposes. Outside band → not a duplicate, but a **candidate for equivalence** (§2B) if the direction rule allows.
- `cosmetic` — never vetoes; contributes to confidence only (brand, packaging, colour).

**Implementation:** `app/compare.py` exposes `compare_attrs(a, b, class_schema) -> {verdict: match|veto|tolerance_match, per_attr: [...], vetoed_by: [...]}`. The matcher calls it for every candidate pair; a veto short-circuits and is persisted in the evidence object with the exact offending attribute and both values. **The UI must show vetoes explicitly** — "Not a duplicate: bore 25 mm vs 30 mm" is a more impressive demo moment than a green match.

Comparators to implement: numeric-with-unit (via `pint`, tolerance-aware), enum/exact, range-overlap (e.g. temp ranges), tolerance-string parsing (`±0.05`, `H7`), and text fallback.

**Acceptance:** the seed data (§7) must contain planted near-miss traps — same description text, different `bore_mm`; same bearing designation, `load_rating_kg` 200 vs 500; identical valve text, `pressure_bar` differing 5% (inside band) and 40% (outside). `make demo` must report a **veto precision metric**: % of planted traps correctly refused. Target ≥ 98%.

### 2A.1 Normalization traps that silently break matching (must handle)
These are the real-world cases that quietly destroy recall or precision. Each needs code and a test:
- **Pack-size / UoM basis.** "BEARING 6205, BOX OF 100" (UoM: BOX) and "BEARING 6205" (UoM: EA) are the same material at different pack basis. Extract `pack_qty` and normalize to a base UoM; pack size is `cosmetic` for identity but must be surfaced on the golden record and used in price-per-unit comparisons (otherwise the Opportunity engine reports nonsense savings).
- **Transliteration, not just multilingual embeddings.** "बेयरिंग 6205" must match "BEARING 6205" even in the TF-IDF fallback path where no multilingual model exists. Implement a Devanagari→Latin transliteration + Hindi domain-term dictionary in `normalize.py`, applied before embedding. Never rely on the model alone for this.
- **Class-assignment failure disables the veto layer.** If an item is misclassified, its class schema (and therefore its identity_critical fields) never applies. Require a class-confidence score; below threshold the item goes to an `unclassified` pool where **only exact anchor-key matching is allowed** and the workbench shows a "class uncertain" warning. Never allow a silent no-schema match.
- **Blocking recall trap.** If the blocking key depends on a brand token and the brand is missing or misspelled, the true pair is never even compared — invisible in precision metrics. Use **multi-pass blocking** (class+bore band, MPN prefix, first-3-token sort key, embedding ANN neighbours) and report a **blocking recall metric**: % of ground-truth duplicate pairs that survive into candidate generation. Target ≥ 0.97. This metric is graded separately from matcher recall.
- **Numeric parsing edge cases:** fractions ("1/2 inch"), ranges ("-20 to 120 C"), tolerances ("25±0.05"), thousand separators ("1,200"), unit-in-description vs unit column conflicts. `compare.py` must parse these, and conflicts between a parsed description value and the structured column must raise a review flag rather than silently trusting one.

## 2B. Functional equivalence — a separate, directed relation

The problem statement asks for identical, duplicate, near-duplicate **and functionally equivalent** items. The first three are similarity problems; the fourth is not, and pure NLP does not solve it. We build an explicit rules + knowledge layer, and we say so plainly to evaluators rather than pretending embeddings cover it.

**Key modelling decision: duplicate is symmetric, equivalence is DIRECTED.** A 500 bar valve can substitute for a 300 bar requirement; the reverse is unsafe. Store direction.

`relation(id, item_a, item_b, rel_type: duplicate|equivalent|supersedes, direction: bidirectional|a_to_b, confidence, basis: designation|crossref|rule|llm, evidence_json, status)`

**Four evidence sources, in precision order:**
1. **Standard designation parsing** — many industrial items encode their own specs. Implement parsers for at least: ISO bearing designations (`6205-2Z` → series 62, bore 25 mm, seal ZZ), pipe schedule/NPS, metric thread (`M12x1.75`), flange class (`ANSI 150#`), fastener grade. Two items whose parsed designations agree on all identity-critical fields are equivalent even with wildly different text.
2. **OEM cross-reference table** — a seeded (and steward-editable) table of interchangeable part numbers across manufacturers (SKF 6205-2Z ↔ FAG 6205-2ZR ↔ NSK 6205ZZ). Loadable as CSV; the wizard lets a CPSE upload their own crossrefs.
3. **Substitution rule DSL** — YAML rules per class, e.g.
   ```yaml
   - class: bearing.ball.deep_groove
     equivalent_if: [bore_mm ==, outer_dia_mm ==, width_mm ==, seal_type ==]
     substitutable_if: [load_rating_kg >=, temp_max_c >=]   # directed: B substitutes A
     never_if: [material !=]
   ```
   Rules are data, not code — stewards edit them in the Taxonomy Manager.
4. **LLM proposal (lowest trust)** — the local LLM may *propose* equivalence with a written justification, but a proposal is only ever a review-queue suggestion; it can never auto-approve, and it is always subject to §2A vetoes.

**UI:** equivalence is displayed distinctly from duplicates — a directed arrow ("B ➜ can substitute A") plus the basis badge (designation / crossref / rule / LLM). The item page lists "Duplicates (merged into this CNMC)" and "Equivalents (separate CNMC, interchangeable)" as two separate blocks. **Equivalent items do NOT get merged into one CNMC** — they keep distinct codes and carry a substitution link. This distinction is a scoring point; do not collapse them.

**Acceptance:** seed data must contain equivalence ground truth (cross-brand crossrefs, higher-rated substitutes, and traps where direction matters). `make demo` reports equivalence precision/recall separately from duplicate metrics, and shows at least one asymmetric pair in the demo flow.

## 2C. Two-way ERP migration (not export-only)

Exporting a mapping file is a report; migration means the CPSE's live SAP master actually starts pointing at the CNMC. Build the full path against a **mock ERP** (`app/erp_mock.py`, a simple SQLite "SAP" with MARA/MAKT-like tables, open POs, stock and valuation rows), with real connectors designed but stubbed.

Pipeline: **plan → dry-run → impact check → staged apply → verify → rollback.**
- `POST /migration/plan` → builds a change set from approved clusters: which legacy codes get the CNMC cross-reference, which duplicates get *blocked* (never hard-deleted — set a deletion/blocked flag, the way real SAP consolidation is done), which become the surviving master.
- `POST /migration/dryrun` → returns a per-record diff plus an **impact report**: open purchase orders, stock on hand, historical movements and valuation attached to each affected code. Any record with open transactions is flagged `hold` by default and excluded from auto-apply — this is exactly the step real consolidations get wrong.
- `POST /migration/apply` (registrar-only, batch-scoped) → writes to the mock ERP through an idempotent, batched writer; every touched row is journaled as a `migration_change` record (before-image + after-image + state) under its `migration_batch`.
- `POST /migration/rollback/{batch_id}` → restores before-images; verify endpoint re-diffs.
- Connector interface `ErpAdapter` with methods `read_masters`, `write_crossref`, `block_material`, `read_open_transactions` — mock implementation now, documented SAP path (BAPI/IDoc-style batch, or LSMW/LTMC-style load file) for production.

**UI:** a Migration screen — pick approved clusters → dry-run → impact table (green = safe, amber = open POs → hold, red = valuation conflict) → apply batch → journal view with a Rollback button.

**Acceptance:** in `make demo`, migrating a batch updates mock-ERP rows, an item with an open PO is auto-held, and rollback restores the mock ERP to a byte-identical prior state (assert in pytest).

## 2D. Golden-record standardization engine (PS capability #3 & #5 — build explicitly)

The PS asks for *"automated standardization of material descriptions and technical attributes"*. Finding duplicates is only half of it: the platform must **produce the clean, canonical record** that replaces them.

**Per-class description template (data, not code):** each class schema declares an ordered description grammar, e.g.
```yaml
bearing.ball.deep_groove:
  template: "{noun}, {type}, {bore_mm}MM BORE, {outer_dia_mm}MM OD, {width_mm}MM W, {seal_type}, {brand} {mpn}"
  noun: "BEARING"
  casing: upper
  max_len: 120
```
Rendering is deterministic (template + normalized attributes), so the same cluster always yields the same standardized description. The local LLM may *polish* wording only where a template slot is missing, and its output is validated back against the template — never free-form text into the golden record.

**Attribute fusion rules (how conflicting source values are resolved), in order:**
1. value present in the highest-confidence extraction (structured column > parsed designation > description text > LLM);
2. most frequent value across cluster members (majority vote), ties broken by most recent `po_date`;
3. most complete/precise value (e.g. `25.0 mm` beats `25 mm approx`, a value with units beats one without);
4. unresolved conflicts on an `identity_critical` attribute → the cluster is **not auto-approved**; it is flagged `conflict` and routed to a steward with both values shown.

Every fused field is persisted as a `golden_field_provenance` row (`golden_id`, field, `source_member_id`, rule) and shown in the evidence panel — a judge asking "where did this description come from?" gets an exact answer.

**Also standardize:** UoM to a base unit with `pack_qty` captured separately, brand/OEM to the canonical alias, classification to the taxonomy node, and specification values to canonical units and precision. Output a `standardization_delta` per member (what changed from legacy text → golden text), because that delta is what CPSEs actually review.

**Acceptance:** `GET /api/clusters/{id}` returns the golden record with per-field provenance; re-running the pipeline on unchanged data produces byte-identical golden descriptions (determinism test in pytest); a conflict on an identity_critical attribute blocks auto-approval (test).

## 2E. Inventory visibility & inter-CPSE sharing (PS Expected Impact #4 & #6)

Duplicate codes hide stock. Once items share a CNMC, stock becomes visible across CPSEs for the first time — this is the impact the PS names as *"better inventory optimization and visibility"* and *"improved inter-CPSE material identification and collaboration"*, and it needs its own feature, not just a mention.

- Seed `stock(item_id, cpse_id, plant, qty_on_hand, reserved_qty, last_movement_date, unit_value)`.
- **Consolidated stock view on every item page:** total qty across all CPSEs for that CNMC, broken down by CPSE and plant, with total tied-up value.
- **Sharing candidates engine:** an item where CPSE A holds surplus (qty above a configurable coverage threshold, no recent movement → slow-moving) while CPSE B holds shortage (below threshold or zero with recent demand) produces a **transfer suggestion** with quantity, both plants, and the avoided purchase value. Distance is out of scope for the prototype — rank by value and staleness instead, and say so.
- **Slow-moving / dead-stock report:** items with no movement in N months, grouped by CNMC, valued — a number CPSE materials managers care about immediately.
- Surfaced on `/dashboard/opportunity` as a third block alongside joint tenders and price variance, and answerable via the Copilot ("where is idle stock of 6205 bearings?").
- Respect §0.9b visibility: stewards see their own plant-level detail plus cross-CPSE availability flags; full valuation detail across CPSEs is registrar/auditor scope.

**Acceptance:** demo flow must show one transfer suggestion with a rupee value that traces back to real seeded stock rows.

## 3. Repo layout

```
saman/
  backend/
    app/main.py            # FastAPI app, routers mounted
    app/db.py, models.py, schemas.py
    app/auth.py            # session cookie, role dependency
    app/normalize.py       # abbrev dict, units, casing
    app/extract.py         # regex+rules attribute extraction per class
    app/embed.py           # ST or TF-IDF fallback
    app/match.py           # tiered engine, evidence objects
    app/cluster.py         # graph -> clusters -> golden drafts
    app/cnmc.py            # code issuance + check digit
    app/copilot.py         # retrieval + templated/whitelisted SQL + optional Ollama
    app/opportunity.py     # aggregation, price variance
    app/audit.py           # hash chain
    app/metrics.py         # P/R/F1 vs truth
    app/seed.py            # datagen (see §7) + demo users
    tests/                 # pytest: normalize, match, cnmc check digit, audit chain
  frontend/
    src/app.tsx, routes/, components/, lib/api.ts, lib/theme.ts, styles/tokens.css
  docker-compose.yml  Makefile  README.md
```

---

## 4. Data model (SQLAlchemy)

`cpse(id, code, name)` · `raw_item(id, cpse_id, legacy_code, description, uom, plant, price, qty_on_hand)` · `item(id, raw_item_id, norm_text, lang, class_code, mpn_norm, gtin, attrs_json, embed_vector BLOB)` · `pair(id, item_a, item_b, tier_scores_json, verdict, veto_json, evidence_json)` · `relation(id, item_a, item_b, rel_type, direction, confidence, basis, evidence_json, status)` · `substitution_rule(id, class_code, rule_yaml, author, active)` · `crossref(id, mpn_a, brand_a, mpn_b, brand_b, source)` · `migration_batch(id, status, created_by, ts)` · `migration_change(batch_id, erp_table, erp_key, before_json, after_json, state: applied|held|rolled_back)` · `cluster(id, status)` · `cluster_member(cluster_id, item_id)` · `golden_record(id, cluster_id, std_description, attrs_json, status: draft|approved)` · `cnmc(id, golden_id, code, status)` · `review_task(id, cluster_id, band: high|grey|low, state: pending|done, assignee_role)` · `decision(id, task_id, user_id, action: approve|reject|merge|split, note, ts)` · `purchase_history(id, item_id, cpse_id, po_date, qty, unit_price, vendor)` · `stock(item_id, cpse_id, plant, qty_on_hand, reserved_qty, last_movement_date, unit_value)` · `golden_field_provenance(golden_id, field, source_member_id, rule)` · `audit_event(id, ts, user, action, entity, payload_json, prev_hash, hash)` · `user(id, name, role, cpse_id nullable)` · `truth_group(raw_item_id, group_id)`  ← ground truth for metrics.

**Data-authority note:** `raw_item.price` and `raw_item.qty_on_hand` are the point-in-time snapshot from the source file, kept for provenance only. `purchase_history` is authoritative for all price analytics; `stock` is authoritative for all inventory features. Dashboards and the Copilot must never read prices or quantities from `raw_item`.

---

## 5. API (all under `/api`, JSON)

- `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- `POST /ingest` (multipart CSV + cpse code) → validation report; `POST /pipeline/run` → runs normalize→extract→embed→match→cluster async (simple background task), emits progress via `GET /pipeline/status`
- `GET /items?search=&cpse=&class=` (search hits norm_text + attrs + fuzzy), `GET /items/{id}` (with cluster, golden, mappings, evidence, price history)
- `GET /queues?band=` (reads pending `review_task` rows) , `GET /clusters/{id}` , `POST /decisions` (closes the `review_task`, writes a `decision`) (role-gated: steward for grey, approver confirm, registrar for CNMC issue)
- `POST /cnmc/issue/{golden_id}` (registrar) → code `CCCC-SSS-NNNNNN-K` (Damm check digit)
- `GET /dashboard/executive` (KPIs, per-cpse progress, class heatmap), `GET /dashboard/opportunity` (aggregation candidates with est. savings = overlap qty × price spread × 0.6 assumption; price-variance list)
- `POST /copilot/query` → `{answer, citations[], sql?}`; router: (a) retrieval over golden records for "what/which item" questions, (b) whitelisted parameterized SQL templates for analytics questions ("count duplicates by cpse", "top price variance", "pending approvals"), (c) if `OLLAMA_URL` set, LLM composes the final prose — otherwise deterministic templates. NEVER free-form SQL.
- `GET /metrics` (pairwise P/R/F1 vs `truth_group`, automation rate), `GET /audit?entity=`, `GET /audit/verify`, `GET /health`
- Equivalence: `GET /relations?item=` , `POST /relations` (steward-proposed), `GET /rules` / `POST /rules` (substitution DSL, registrar), `POST /crossref/import`
- Migration: `POST /migration/plan`, `POST /migration/dryrun`, `POST /migration/apply` (registrar-only), `POST /migration/rollback/{batch_id}`, `GET /migration/batches`, `GET /migration/batches/{id}` (journal + diffs)
- **Smart-Create (duplicate prevention at source)**: `POST /smart-create/check` → body `{description, mpn?, uom?}` → returns ranked existing candidates with confidence + "create new anyway" token. Counter of prevented duplicates exposed on the Integration Health dashboard. This is a headline differentiator — do not skip it.
- **PPRL restricted mode (stretch, build if M1–M7 are green)**: `POST /pprl/encode` (returns character-3gram Bloom-filter encodings of a CPSE's catalog, no plaintext) and `POST /pprl/compare` (Dice similarity over two encoding sets → overlap report). Demonstrates cross-CPSE matching with zero raw-data exchange. UI: a "Restricted mode" badge + a two-catalog compare screen.
- Admin: `GET/POST /users`, `POST /settings/sovereign` (mock toggle stored + shown in UI banner)

---

## 6. Screens & acceptance criteria (13 routes + 1 stretch)

1. **/login** — mono wordmark "SAMAN", user picker with role badges, password `demo`. AC: wrong password shakes 4px (respecting reduced-motion).
2. **/ (Home)** — role-aware: registrar sees Executive KPIs; steward sees "Your queue: N pending" CTA. AC: KPI count-up, cards stagger in.
3. **/search** — full-width mono search, filters (CPSE, class, has-CNMC), results table; ⌘K opens same search as palette overlay anywhere. AC: typing "6205" surfaces all bearing variants across CPSEs; row click opens item drawer.
4. **/items/:id (drawer + full page)** — golden record block, CNMC chip, legacy mappings table (every CPSE's code), attributes grid, evidence accordion (tier scores as horizontal mono bars), price history sparkline (from `purchase_history`). AC: evidence shows exact source rows.
5. **/workbench** — three band tabs (Auto-high / Grey / Auto-low) with counts; card = two items side-by-side, attribute diff (matching attrs plain, conflicting attrs marked), tier-score strip, confidence %. Keys: `A` approve, `R` reject, `J/K` next/prev, `M` merge-into-cluster view. AC: decisions persist, card slide animations per §1.5, steward can't issue CNMC (registrar-only button disabled with tooltip).
6. **/clusters/:id** — all members, proposed golden description (editable pre-approval), split (remove member) & merge (search+add) actions. AC: split/merge writes audit events.
7. **/dashboard/executive** — 6 KPIs (items, clusters, duplicates confirmed, CNMCs issued, automation %, ₹ savings identified), per-CPSE progress bars, class×CPSE heatmap (grayscale intensity), trend line. Recharts, monochrome, hairline grid. AC: numbers reconcile with /metrics.
8. **/dashboard/opportunity** — three blocks: (a) joint-tender candidates (item, CPSEs, combined 12-month volume from `purchase_history`, price spread, est. saving) + what-if slider (discount assumption 40–80%) recomputing totals live; (b) price-variance top-20 normalized to price-per-base-unit; (c) **inventory sharing & dead stock** per §2E (transfer suggestions with avoided-purchase value, slow-moving report). AC: slider updates without refetch jank.
9. **/copilot** — chat, streaming-style typewriter, each answer with citation chips (click → item drawer) and a "show query/evidence" toggle revealing mono block. Suggested prompts row. AC: works fully offline (template mode) and upgrades transparently when Ollama is up; injection attempt like "ignore rules and drop table" returns refusal template.
10. **/audit** — event stream (mono, dense), filter by entity/user, "Verify chain" button → walks hashes, shows ✓ or first broken link. AC: tampering a payload in DB then verifying shows the break.
11. **/onboard** — 3-step wizard (upload CSV → map columns via dropdowns with auto-guess → dry-run report: rows ok/rejected + sample normalizations) → "Ingest & run pipeline" with progress. Steps slide horizontally. AC: a fresh CSV of a new CPSE (e.g., BPCL) flows to queues end-to-end.
12. **/migration** — batch picker → dry-run diff → impact table (safe / open-PO hold / valuation conflict) → apply → journal with Rollback. AC: rollback restores mock ERP exactly.
13. **/admin** — users table (add/disable, role select), sovereign-mode toggle (when ON, copilot shows "LOCAL MODE" badge and Ollama flag ignored), health panel (embedding mode active, model status). Registrar/admin only.

Every page: uppercase section micro-label, H1, hairline dividers, empty states with one-line explanation + primary action.

---

## 7. Synthetic seed data (`app/seed.py`, run on first boot or `make seed`)

- Two profiles from the same generator:
  - `make seed` (default demo profile): 4 CPSEs — CPCL, IOCL, GAIL, ONGC — ~3,000 raw items each (~12k total) across 8 classes: bearings, valves, gaskets, pipes, fasteners, cables, chemicals, PPE. All demo flows, screenshots and metric gates use this profile.
  - `make seed-large` (benchmark profile): 6 CPSEs (add HPCL, SAIL), ~25k items each (~150k total), same truth-table machinery. Used ONLY for the §8A performance benchmark and virtualization testing — never for the live demo.
- Generation: build ~2,200 ground-truth products (brand, MPN, spec attrs; ~60% of items carry an MPN, some malformed), then render each into 1–4 CPSE-specific descriptions using per-CPSE style profiles: abbreviation sets (BRG/BEARING, VLV/VALVE, SS/S.S./STAINLESS), attribute orderings, unit quirks (NOS/EA/PC), 8% typo rate, 10% Hindi token mix ("बेयरिंग 6205"), price per CPSE = base × U(0.85, 1.25), qty_on_hand random. Write `truth_group` accordingly.
- **Planted traps & equivalence truth (required):** near-miss pairs differing only on an identity_critical numeric (bore 25 vs 30), same-designation pairs differing on `load_rating_kg` (200 vs 500), valve pairs differing 5% (in-band) and 40% (out-of-band) on pressure, cross-brand equivalents (SKF/FAG/NSK same designation), and directed substitutes (higher-rated replaces lower). Record all of these in truth tables so veto precision, equivalence precision/recall and direction accuracy are measurable.
- Seed users: `registrar@min.gov.in`, `admin@saman.gov.in`, `steward@cpcl.in` (+approver, auditor, viewer). All password `demo`.
- `make demo`: seeds, runs pipeline, prints metrics table + URL.

---

## 8. Build order for you (Claude Code) — commit per milestone

Stop after each milestone and report status; do not run ahead into UI polish before M3 metrics are green.

- **M1** Scaffold both apps, tokens, theme toggle, shell (sidebar+command bar), routing + transitions.
- **M2** Models, auth (incl. separation of duties §0.9), seed datagen with planted traps + `purchase_history`, ingest, normalize (abbrev dict ≥120 entries, pack-size + transliteration per §2A.1), extract (regex rules per class, class-confidence gate), health endpoint.
- **M3** Embed (with fallback), multi-pass blocking, tiered match, **§2A comparators + hard-constraint veto layer**, clustering, golden drafts, CNMC service + Damm check digit, metrics vs truth. **Gate (held-out set): duplicate precision ≥ 0.92, recall ≥ 0.80, blocking recall ≥ 0.97, veto precision on planted traps ≥ 0.98** — tune until all four are true, then freeze thresholds.
- **M3.4** §2D standardization engine: per-class description templates, attribute fusion with provenance, determinism test, conflict-blocks-approval test.
- **M3.5** §2B equivalence engine: designation parsers, crossref table, substitution-rule DSL, directed `relation` records, separate equivalence metrics. Equivalents must NOT be merged into one CNMC.
- **M4** Workbench + clusters + decisions + role gates + audit chain.
- **M5** Executive + Opportunity dashboards incl. §2E inventory/sharing/dead-stock blocks and `purchase_history`-driven aggregation.
- **M6** Copilot (retrieval + SQL templates + optional Ollama + guards).
- **M7** Onboarding wizard, admin, audit explorer + verify.
- **M7.5** §2C two-way migration: mock ERP, plan/dry-run/impact/apply/rollback + Migration screen.
- **M8** Smart-Create endpoint + widget, `make licenses` + README "Built with" table + THIRD_PARTY_LICENSES.md + CI license check.
- **M8B** §8A demo survivability: `make demo-restore` snapshot, virtualized tables, server-side pagination, progress streaming, empty states, degraded-mode chip.
- **M9** Motion polish per §1.5, a11y pass, README with screenshots + §9A traceability table + `KNOWN_GAPS.md`, `make demo`, pytest green.
- **M10 (stretch)** PPRL restricted mode (encode/compare + UI badge and compare screen).

Definition of done: fresh clone → `make demo` → login as steward → clear 5 grey tasks with keyboard → login as registrar → issue a CNMC → ask copilot "which CPSE overpays for gaskets" → get cited answer → `GET /api/audit/verify` returns valid → metrics (held-out) show duplicate P ≥ 0.92 / R ≥ 0.80, blocking recall ≥ 0.97, veto precision ≥ 0.98, and separate equivalence metrics → run a migration dry-run showing an open-PO hold, apply it, then roll it back to an identical prior state. All with zero network access.

## 8A. Demo survivability & performance (the finale is a live demo)

- **Pre-baked demo state:** `make demo` must produce a saved DB snapshot (`data/demo.db`) and a `make demo-restore` that resets to it in <5 s. Never run a full 150k-item pipeline live in front of judges — run it on a small "new CPSE joins" file (≈2k rows) that completes in under 60 s, on top of the pre-baked state.
- **Long-job UX:** every pipeline run streams progress (stage, rows done, ETA) via polling `GET /pipeline/status`; the UI shows a determinate progress bar and never blocks the whole page. A crashed job must be resumable, not restart-from-zero.
- **Frontend performance:** tables must be virtualized (windowed rendering) — 150k rows cannot be mounted. Search results paginate server-side (limit/offset + total count). Charts aggregate server-side, never client-side over full data.
- **Backend performance:** index `(cpse_id, legacy_code)`, `mpn_norm`, `class_code` in SQLite; candidate generation must be batched; the `make seed-large` 150k-item pipeline should complete on a laptop CPU in a documented time (record it in the README — judges ask "how long does it take?").
- **First-run and empty states:** fresh DB with no data must still render every screen with a helpful empty state and a "Load demo data" button, never a crash or an infinite spinner.
- **Failure banners:** if a subsystem is degraded (no Ollama, TF-IDF fallback, splink missing), show a single unobtrusive status chip in the top bar, and mirror it in `/api/health` and the admin panel.

## 9. Open-source foundation, inspiration repos & licensing

Use proven engines inside our own architecture. SIH permits open-source libraries with attribution and license compliance; what it forbids is presenting someone else's product as ours. Never fork an existing app as the base.

**Incorporate (permissive licenses only):**
| Library | License | Used for |
|---|---|---|
| `splink` (moj-analytical-services/splink) | MIT | Tier-1 probabilistic record linkage (Fellegi–Sunter), blocking rules, match weights |
| `rapidfuzz` | MIT | fast string/token similarity features |
| `sentence-transformers` (+ MiniLM / bge-m3) | Apache-2.0 | Tier-2 semantic embeddings |
| `scikit-learn` | BSD-3 | TF-IDF fallback path, metrics |
| `duckdb` | MIT | analytics views backing Copilot SQL |
| `fastapi`, `sqlalchemy`, `pydantic` | MIT / BSD | backend |
| React, Vite, Tailwind, framer-motion | MIT | frontend |
| Ollama + Qwen 2.5 (Apache-2.0) / Llama 3.1 (community license) | — | optional local LLM tier |

**Copy the pattern, not the code (study these repos for design):**
- **splink** — its match-weight waterfall and cluster-studio visualizations are the model for our **evidence cards**; mirror the idea of showing per-comparison contribution, not a bare score.
- **dedupe** (dedupeio/dedupe, MIT) — its **active learning via uncertainty sampling** is the pattern for our "teach the model" queue; implement the same loop shape even though we don't import it.
- **vanna** (vanna-ai/vanna, MIT) — the **RAG + NL→SQL** pattern for the Copilot: retrieve schema//example pairs, generate SQL, validate before execute. We reimplement it constrained to whitelisted templates/views (never free-form SQL).
- **FEBRL / GeCo** record-linkage data generators — reference for realistic **corruption models** (typos, abbreviations, field swaps) in `seed.py`.
- **GOV.UK Design System (alphagov/govuk-frontend)** — design language reference only for typography-first government minimalism. Do not import any code or CSS; we build our own primitives per §1.

**Explicitly excluded:** `zingg` (AGPL-3.0) — strong entity-resolution project, but copyleft would encumber a government/CPSE handover. Do not import, vendor, or copy code from it.

**Attribution requirements (build these, they are graded):**
- `README.md` must contain a **"Built with"** table listing every third-party dependency and its license, plus a short "What is original to SAMAN" paragraph: the CNMC registry & check-digit scheme, tiered routing logic, evidence cards, review workbench, guarded Copilot, Smart-Create, opportunity engines, PPRL mode.
- Add `THIRD_PARTY_LICENSES.md` generated from `pip-licenses` and `license-checker` output; add a `make licenses` target that regenerates it.
- Fail the build (CI check) if any dependency reports a GPL/AGPL license.

## 9A. Problem-statement traceability (completeness is an explicit judging criterion)

The README must contain a **traceability table** mapping every capability named in SIH26099 to where it lives in this build. Claude Code must fill and keep this table honest (mark partial items as partial — inflated claims lose more marks than gaps):

| PS-stated capability | Where it lives | Status |
|---|---|---|
| AI-based matching of descriptions & specifications across CPSEs | §0.4 tiers + `match.py` | |
| Identification of duplicate, near-duplicate and equivalent materials | §2A veto layer (dup) + §2B relation engine (equivalent) | |
| Automated standardization of descriptions and technical attributes | §2D templates + attribute fusion + provenance | |
| Intelligent classification and categorization | taxonomy + class assignment with confidence gate | |
| Generation/recommendation of a Common National Material Code | `cnmc.py` (Damm check digit) | |
| Mapping of existing CPSE codes to the common national code | `mapping` table + item page block | |
| Legacy code rationalization and migration support | §2C plan/dry-run/apply/rollback | |
| User validation and approval workflow for AI recommendations | `/workbench` + separation of duties (§0.9) | |
| Dashboard for material master analytics and duplicate detection | `/dashboard/executive` + `/dashboard/opportunity` | |
| Audit trail and governance mechanism | §0.8/§0.9a hash chain + `/audit` | |
| Integration capability with SAP/ERP of participating CPSEs | `ErpAdapter` + SAP-shaped exports + §2C write-back | |
| Analysis of **historical procurement data** | `purchase_history` → aggregation, price-per-unit variance, vendor overlap (below) | |
| Units of measurement harmonization | §2A.1 UoM base + `pack_qty` | |
| Inventory optimization & visibility (Expected Impact) | §2E consolidated stock, transfer suggestions, dead stock | |
| Inter-CPSE collaboration (Expected Impact) | §2E sharing + joint tenders | |
| Faster procurement/specification finalization (Expected Impact) | Smart-Create + standardized specs (§2D) | |
| Foundation for strategic sourcing (Expected Impact) | vendor overlap + combined-volume analysis on the Opportunity dashboard | |

**Historical procurement data must actually be used, not just stored.** Seed a `purchase_history(item_id, po_date, qty, unit_price, vendor)` table and use it for: (a) demand-aggregation windows (items bought by ≥2 CPSEs within a rolling 12-month window → joint-tender candidate, with combined volume), (b) price-variance detection normalized to price-per-base-unit (using `pack_qty` from §2A.1), (c) a "last purchase price + trend" block on the item page, and (d) vendor overlap ("3 CPSEs buy the same item from different vendors at different prices"). Savings estimates must state their assumption inline in the UI, e.g. "assumes 60% of the observed spread is capturable at combined volume".

## 10. Guardrails

- No external network calls at runtime (fonts self-hosted; Ollama is localhost-optional).
- Never invent UI colors beyond §1.1. Never add a component library. Keep bundle lean.
- If a dependency is unavailable, degrade per §0.4 and surface the active mode in /admin health — never crash.
- **Never fake data or results.** No hardcoded metric numbers, no mocked "AI" responses presented as real, no placeholder savings figures. Every number on every screen must be computed from the database. If something isn't built yet, show an honest empty state.
- **No silent scope drops.** If a milestone item is skipped, record it in `KNOWN_GAPS.md` with a one-line reason — an honest gaps list is worth more in evaluation than a hidden hole.
