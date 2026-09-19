# SAMAN refinement plan

Four stages, each ending at a gate that must be true before the next begins.
Every item is tagged **improve** (what exists), **add** (what is missing) or
**fix** (what is honest but weak). Effort is one person's calendar time.
Nothing here changes the rules that made the prototype credible: every figure
computed, every assumption shown, nothing decides unaccountably, and
`KNOWN_GAPS.md` stays public. `ROADMAP.md` says who this is for and why; this
file says what to build, in what order.

## Where each problem-statement capability stands

| PS capability | Built today | The refinement that moves it most |
|---|---|---|
| AI matching across CPSEs | Four tiers, veto layer, blocking recall 0.995, P 0.997 / R 0.960 held out | Real public data run (GeM/CPPP descriptions); per-class thresholds; incremental reruns |
| Duplicates, near-duplicates, equivalents | Veto in real units; directed equivalence; engineer approval bound to equipment | Datasheets on the decision; the LLM as a low-trust equivalence *proposer* (spec source 4, unbuilt) |
| Standardised descriptions and attributes | Class templates, 4-rule fusion, per-field provenance, UNSPSC + HSN | Class-template drafting from rows; steward-editable abbreviation dictionary; Odia/Tamil terms |
| Classification | 8 classes with a confidence gate | Fifty classes via the drafting tool; a "wrong class" correction path from the Workbench |
| Common National Material Code | Immutable CNMC, Damm check digit, registrar-only | Code-issue policy per family; dispute workflow; DoS/NCB alignment note |
| Mapping of legacy codes | Item page, scan card, printed labels | Bin-location binding; labels at goods receipt |
| Legacy migration support | Plan → dry run → apply → verify → rollback; open POs held | Approval workflow with a diff view; scheduled windows; live SAP sandbox |
| User validation workflow | Workbench, separation of duties, learned queue order | Bulk actions; seconds per decision; filters and assignment; undo within a window |
| Analytics dashboard | Executive + Opportunity, eight analytic sections, memoised | Drill-down to rows; exports; date scoping; a steward's own-CPSE view |
| Audit and governance | Hash chain verified from the page | Signed exports, retention policy, external anchoring |
| SAP / ERP integration | Three doors, none opened on a live system | Sandbox client run; credentials in a vault; GeM category mapping and PO round-trip |
| Procurement history analysis | 12-month windows, variance, vendor overlap, ABC | Vendor de-duplication; realised-savings ledger |
| Units harmonisation | Base UoM + pack quantity, unit-aware comparison | Steward review of unit conversions per class |
| Inventory visibility and optimisation | Consolidated stock, transfers, dead stock, scan on the phone | Offline-capable Scan app; stock-count mode; a real cross-CPSE stock feed |
| Inter-CPSE collaboration | Joint-tender candidates, restricted mode | Tender pack export; lead-buyer suggestion; signed bundles between nodes |
| Faster specification finalisation | Smart-Create with OCR, approvals shown | Save a probe as a draft; barcode into Smart-Create; specification sheet export |
| Strategic sourcing foundation | Vendor overlap, combined volume | Vendor alias table; category spend view |

## Stage 1 · one to two weeks · polish every screen

*Goal: nothing new in the engine. Make what exists feel finished on a phone
and at a desk.*

| Screen | Tag | Item | Why | Effort |
|---|---|---|---|---|
| Workbench | add | Bulk confirm for the high band: select a page, one reason, one audit event per row | 7,381 policy confirmations one card at a time is not a steward's afternoon | 2 d |
| Workbench | add | Seconds per decision recorded on the card; shown on the dashboard | The first number a pilot is judged on | 2 d |
| Workbench | improve | Filters (class, CPSE, band, assigned to me); undo within five minutes | Queues are worked by family, and everyone mis-clicks | 2 d |
| Search | improve | Sort by relevance, recent searches, "did you mean" from the abbreviation table | Half of real queries are misspelt abbreviations | 2 d |
| Scan | add | Installable app (PWA) with the OCR engine cached; works with no signal, syncs later | Stores have no signal; the phone must still answer | 3 d |
| Scan | add | Stock-count mode (scan, count, next); bin binding ("this bin holds this code") | The storekeeper's real daily job | 3 d |
| Scan | improve | Torch toggle, scan history, a "wrong item?" report | Dim stores; mistakes need a path back | 1 d |
| Smart-Create | add | Barcode and part-number fields feeding the check; save a probe as a draft request | Most new-code requests start from a box in hand | 2 d |
| Dashboards | add | Drill-down: every bar and tile opens the rows behind it; CSV and PDF export | An executive's next question is always "which ones" | 3 d |
| Dashboards | improve | A steward's own-CPSE view; date scoping on the money sections | The same page must serve two readers | 2 d |
| Onboard | improve | Excel input, long-text tables, a downloadable rejection report, progress for large files | Real extracts are .xlsx with MAKTX in one sheet and long text in another | 3 d |
| Item / Cluster | add | Side-by-side compare of any two rows; attachments (datasheet, drawing) on a golden record | Approvers ask for the datasheet first | 3 d |
| Assistant | improve | Hindi answers when asked in Hindi; clickable citations; the last five turns as context | The people at the bin do not write English questions | 2 d |
| Whole site | improve | Hindi interface toggle; loading states on every fetch; an accessibility pass with a screen reader | A government instrument is used by everyone | 4 d |

**Gate:** a steward clears a page of the high band in under a minute; the
Scan app resolves a label with the phone in flight mode; every dashboard bar
opens its rows.

## Stage 2 · two to four weeks · deepen the engine, on real text

*Goal: move the numbers that matter from synthetic to measured on real
descriptions, and let the system grow past eight classes.*

| Area | Tag | Item | Why | Effort |
|---|---|---|---|---|
| Data | add | A public corpus from GeM and CPPP tender documents (item descriptions only), a few thousand rows, run through the pipeline with measured precision | The one answer to "your data is synthetic" that a slide cannot give | 3 d |
| Data | fix | Fifty real nameplate photographs in bad light; OCR score on them; repair rules tuned | 0.967 is on drawn plates and says so | 2 d |
| Classes | add | Class-template drafting: from a class's rows, propose attributes, units, tolerances and roles for an expert to approve in a form | Eight classes do not cover a refinery; this is the step to fifty | 1 wk |
| Classes | add | Steward-editable abbreviation dictionary per CPSE, versioned, audited | Every house style has words the taxonomy does not know | 3 d |
| Matching | improve | Per-class thresholds swept on the tuning split; incremental reruns that touch only new rows and their neighbours | Bearings and chemicals do not share one T_HIGH; 200 new rows should not cost a 19-minute rerun | 1 wk |
| Matching | add | The language model as equivalence *proposer*, the spec's lowest-trust source: suggestions only, into the review queue, never a merge | Named in the spec; adds recall where rules stop | 3 d |
| Matching | improve | Bundle MiniLM weights for an offline Tier 2 install option; measure against TF-IDF on the real corpus | Meaning similarity may win on real text; today it is unmeasured there | 2 d |
| Learning | improve | Retrain on real reviewer labels only once they exceed the simulated ones; show the model's precision by class on the admin page | The learned model must be judged on people's decisions, not the generator's | 2 d |
| Procurement | add | Vendor alias table and normalised vendor overlap; price-anomaly flags with the assumption shown | Overlap matches exact strings today | 3 d |
| Languages | add | Hindi attribute words inside extraction; Odia and Tamil term tables | Plants write in their own language | 2 d |

**Gate:** precision above 0.95 on the public corpus for two families,
published with the corpus; fifty classes drafted and ten approved by an expert.

## Stage 3 · one to two months · enterprise readiness

*Goal: from a laptop prototype to something an IT department will install and
an auditor will accept.*

| Area | Tag | Item | Why | Effort |
|---|---|---|---|---|
| Database | improve | PostgreSQL behind the same models; memo, audit chain and login throttle on shared storage; migrations | One node on SQLite is a CPSE, not a registry | 1 wk |
| Identity | add | SSO (Parichay / the CPSE directory), MFA for registrars, session list and revocation, password policy; demo login off | Accounts must belong to people | 1 wk |
| SAP | fix | Run the RFC adapter against a sandbox client; credentials in a vault; the BAdI hook installed by a basis team; IDoc or CPI event feed for stock and PO changes | Three doors built, none opened | 2 wk |
| GeM | add | Class-to-GeM-category mapping table; tender pack export (specification sheet from the golden record, combined quantity, lead buyer); PO round-trip into purchase history | GeM is the buying counter; SAMAN writes what it buys from | 2 wk |
| Money | add | Realised-savings ledger: post-consolidation POs against the baseline | Identified savings are a claim; realised ones are a fact | 1 wk |
| Federation | add | Signed, versioned bundles of golden records and codes between CPSE nodes and the registry; import with conflict handling | The shape a national registry takes | 2 wk |
| Audit | improve | Signed chain exports; retention policy; periodic anchoring of the chain head outside the machine | Tamper-evident becomes tamper-proof in practice | 3 d |
| Operations | add | Backups and a restore drill; monitoring; an offline installer; an upgrade path that keeps issued codes; encryption at rest | What an IT department asks on day one | 1 wk |
| Scale | fix | Measure at one million rows; virtualised tables everywhere; background jobs for pipeline runs with progress | A national master is that size | 1 wk |

**Gate:** one joint tender floated on GeM from a consolidated demand and its PO
read back; the registry holding two CPSE nodes' codes with no conflict.

## Stage 4 · three to six months · a standard, not a project

*Goal: the part that is not software, and the software that makes it stick.*

| Area | Item | Why |
|---|---|---|
| Governance | A body that owns class templates and code-issue policy; a dispute process with an SLA; alignment with the Directorate of Standardisation and a BIS working draft for the code format | None of this is software; all of it decides whether the software is used |
| Ecosystem | A public read-only code lookup API; UNSPSC / HSN / NSN mapping export; a supplier-side specification view | A code is worth more when vendors and GeM can read it |
| National view | Ministry dashboard across CPSEs with the same honesty rules; procurement policy on when a joint tender is mandatory and how savings are attributed | The reason the ministry funds it |
| People | Training for stewards and approvers; the assistant's corpus becomes the manual; a certification for codification cells | Adoption is a people problem |

**Gate:** a second ministry adopts the code without changing the software.

## What to improve in what already exists, regardless of stage

- **Reruns.** The pipeline re-embeds and re-matches everything; make it
  incremental so an upload of 200 rows costs seconds.
- **Frontend test depth.** 117 tests cover the state machines; add browser
  tests for the five demo moves so a regression is caught before a judge
  sees it.
- **The learned model's story.** Show its confusion matrix on real labels and
  hide it while labels are simulated.
- **Explanations.** Every refusal already carries its reason; surface it as
  one sentence on the Workbench card and in the Copilot answer.
- **Captions.** Every chart says the data is synthetic; when real data
  arrives, the same captions must say which source and which date.
- **Docs.** One "install in a CPSE" guide with the two shapes (laptop, server),
  the environment variables, and what each engine needs.

## What not to build

- A model that decides a match. The veto layer stays rules; the language
  model stays a writer.
- Trend charts, forecasts or rates from a single day of activity. Five
  decisions cannot support a rate.
- A cloud-only design. Offline first; remote only for a demo, and labelled.
- Fine-tuning on simulated labels. It teaches the generator, not materials.
- Anything that deletes a legacy row. Superseded means blocked, never gone.
