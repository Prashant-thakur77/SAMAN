# Ground-reality improvements — design

Date: 2026-09-03. Status: approved in conversation; built in the order below.

SIH26099 names eleven capabilities; the build covers all of them and reports
SAP/ERP integration as partial. What a CPSE materials manager will test the
demo against is not the feature list but how it behaves inside their world:
codes are born in SAP, every PO needs an HSN, engineers refuse substitutes
without sign-off, and identified savings are argued with until they are
realised. These sub-projects close those gaps. Each ships with tests, a UI
surface, and an honest line in the README and KNOWN_GAPS.

## 1. Standards on the golden record

Every class carries a UNSPSC code and an HSN heading in `classes.yaml`, each
with the level it was assigned at (commodity/class/family/segment for UNSPSC,
heading/subheading for HSN). They surface on the item page, the cluster page
and the SAP load files. They are class-level defaults with a stated
precision, not per-item tax advice; the UI says so.

## 2. Learning from the Workbench ("our own local model")

Fine-tuning a language model is the wrong lever for matching: the decisions
that matter are pairwise and attribute-driven, and the veto layer must remain
absolute. The right local model is a small, transparent pairwise classifier
trained on reviewer decisions.

- `pair_label(pair_id, label, source, user_id, ts)` is written by every
  approve/reject in the Workbench (`source=reviewer`) and, for the demo, by a
  simulator that labels tuning-split pairs from ground truth
  (`source=simulated`). The simulator never touches tasks or clusters, and
  never reads the held-out split.
- `learn.py` builds a feature vector per pair from the stored tier scores and
  evidence (anchor, fuzzy, semantic, attribute agreement, identity/performance
  counts, brand and class signals), trains a logistic regression with a
  standard scaler, cross-validates, and persists **coefficients as JSON** in
  `data/models/pairwise.json`. No pickle: the model is a readable vector of
  weights and can be audited.
- The model never changes a verdict. It (a) orders the grey queue by
  uncertainty so reviewers see the most informative pairs first, (b) shows
  its probability on the card next to the pipeline's confidence, (c) is
  evaluated against the held-out split so the README can say whether the
  reviewer-trained model beats the hand-tuned score.
- `GET /api/learn/corpus` exports the labelled pairs as JSONL: the corpus a
  future LoRA on the local LLM would need. That corpus does not exist today;
  this is how it starts to.

## 3. A real SAP path

- `RfcErpAdapter` implements the existing `ErpAdapter` contract over `pyrfc`
  (optional import): `RFC_READ_TABLE` for reads of MARA/MAKT/EKPO/MARD/MBEW,
  `BAPI_MATERIAL_SAVEDATA` for the deletion flag and the CNMC cross-reference
  (an append field on MARA, configurable), `BAPI_TRANSACTION_COMMIT` after
  each batch. Selected by `SAMAN_ERP_ADAPTER=rfc`; without `pyrfc` it degrades
  to the mock and says so at `/api/health`. It has not been run against a live
  SAP system and the docs say so.
- Load files: the migration plan exports a zip of `block.csv`,
  `crossref.csv` and a README in SAP field names, for an LSMW recording or an
  LTMC project, so a basis team can apply a batch without any connector.
- Service access for the SAP-side hook: `SAMAN_API_KEYS` maps a key to a
  seeded service user; `X-SAMAN-Key` authenticates machine calls. A BAdI on
  material creation calls Smart-Create's check before MM01 saves. Documented
  in `docs/sap-integration.md` with the ABAP shape of the call.

## 4. Equipment context and approved substitutes

- `equipment(cpse, tag, description, criticality A|B|C)` and
  `equipment_bom(equipment, item, qty)` seeded per CPSE from its catalogue.
- `substitute_approval(relation, status, decided_by, reason, ts)`; a new role
  `engineer` (technical authority) decides. Registrar and admin may too.
- Item page shows where a material is installed and its VED class; every
  equivalence shows its approval state; Smart-Create labels interchangeable
  parts as approved or awaiting engineering approval; transfer suggestions
  flag a source where the material is a critical spare.
- `/substitutes` screen for the engineer: proposed equivalences with the
  equipment they touch, approve/reject with a reason, audited.

## 5. Data-quality scorecard and ABC

- `quality.py`: per CPSE, classification rate, identity-attribute
  completeness, canonical UoM rate, MPN coverage, duplicate rate, stale rate,
  one weighted score. Executive dashboard table.
- ABC by 12-month consumption value per CPSE; shown on dead stock, transfer
  suggestions and the item page. VED comes from equipment criticality.

## Not in this round

Realised-savings ledger, vendor de-duplication, signed federation bundles,
bin labels. Listed in KNOWN_GAPS with what each needs.

## Testing

Backend: pytest per module plus endpoint permission tests. Frontend: vitest
for new panels. Every screen is verified in headless Chromium before commit.
`make check` stays green at every commit.
