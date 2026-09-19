co# SAMAN refinement plan

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
| Workbench | add · **done** | Bulk confirm for the high band: select a page, one reason, one audit event per row | 7,381 policy confirmations one card at a time is not a steward's afternoon | 2 d |
| Workbench | add · **done** | Seconds per decision recorded on the card; shown on the dashboard | The first number a pilot is judged on | 2 d |
| Workbench | improve · **done** | Filters (class, CPSE, band, assigned to me); undo within five minutes | Queues are worked by family, and everyone mis-clicks | 2 d |
| Search | improve · **done** | Sort by relevance, recent searches, "did you mean" from the abbreviation table | Half of real queries are misspelt abbreviations | 2 d |
| Scan | add · **done** | Installable app (PWA) with the OCR engine cached; works with no signal, syncs later | Stores have no signal; the phone must still answer | 3 d |
| Scan | add · **done** | Stock-count mode (scan, count, next); bin binding ("this bin holds this code") | The storekeeper's real daily job | 3 d |
| Scan | improve · **done** | Torch toggle, scan history, a "wrong item?" report | Dim stores; mistakes need a path back | 1 d |
| Smart-Create | add · **done** | Barcode and part-number fields feeding the check; save a probe as a draft request | Most new-code requests start from a box in hand | 2 d |
| Dashboards | add · **done** (CSV on every table, PDF via print) | Drill-down: every bar and tile opens the rows behind it; CSV and PDF export | An executive's next question is always "which ones" | 3 d |
| Dashboards | improve · **done** | A steward's own-CPSE view; date scoping on the money sections | The same page must serve two readers | 2 d |
| Onboard | improve · **done** (progress bar: pipeline only) | Excel input, long-text tables, a downloadable rejection report, progress for large files | Real extracts are .xlsx with MAKTX in one sheet and long text in another | 3 d |
| Item / Cluster | add · **done** | Side-by-side compare of any two rows; attachments (datasheet, drawing) on a golden record | Approvers ask for the datasheet first | 3 d |
| Assistant | improve · **done** | Hindi answers when asked in Hindi; clickable citations; the last five turns as context | The people at the bin do not write English questions | 2 d |
| Whole site | improve · **done as far as measured**: Hindi toggle; every route has one h1, a main landmark, named buttons and labelled inputs (checked in a browser); a screen-reader walkthrough is still a person's afternoon | Hindi interface toggle; loading states on every fetch; an accessibility pass with a screen reader | A government instrument is used by everyone | 4 d |

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
| Classes | add · **done** | Steward-editable abbreviation dictionary per CPSE, versioned, audited | Every house style has words the taxonomy does not know | 3 d |
| Matching | improve · **done** (incremental reruns; per-class sweep in `make tune`: bearings +0.03 F1 from a lower cut, other classes ~0, reported not applied) | Per-class thresholds swept on the tuning split; incremental reruns that touch only new rows and their neighbours | Bearings and chemicals do not share one T_HIGH; 200 new rows should not cost a 19-minute rerun | 1 wk |
| Matching | add | The language model as equivalence *proposer*, the spec's lowest-trust source: suggestions only, into the review queue, never a merge | Named in the spec; adds recall where rules stop | 3 d |
| Matching | improve | Bundle MiniLM weights for an offline Tier 2 install option; measure against TF-IDF on the real corpus | Meaning similarity may win on real text; today it is unmeasured there | 2 d |
| Learning | improve · **done** | Retrain on real reviewer labels only once they exceed the simulated ones; show the model's precision by class on the admin page | The learned model must be judged on people's decisions, not the generator's | 2 d |
| Procurement | add · **done** (alias table, normalised overlap; price flags at 1.5× the others' median, rule printed beside them, on Opportunity, the item page and the weekly report) | Vendor alias table and normalised vendor overlap; price-anomaly flags with the assumption shown | Overlap matches exact strings today | 3 d |
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

## The models: making them stronger, measured

Two models do the work that people notice: the learned pairwise model that
orders the review queue, and the language model that words sentences and
answers questions from the documents. Neither may decide a match; that rule
does not change. "Stronger" here means a number that moved on a fixed test,
never a feeling.

### The language model

**Status key:** `done` shipped in this round · `doing` in progress today ·
`next` planned, in order.

| # | Item | Status | Why |
|---|---|---|---|
| L1 | A measured harness: `make llm-eval` runs sixteen questions from the documents (English, Hinglish, Hindi) and reports acceptance, correctness against expected words, and seconds, for whatever model is configured | done | Without it "better" is an opinion. Baseline, remote Qwen 27B on Groq: accepted 14/16, correct 12/16. Local 3B: accepted 15/16, correct 9/16; 7B: 16/16, 10/16 (README, "Ask SAMAN") |
| L2 | Wider corpus: the SAP integration guide, the roadmap and this plan join the README, gaps list and spec | done | Judges ask about integration and the future; the model should read the same pages they do |
| L3 | Retrieval reads Hindi, Hinglish and house abbreviations by normalising the question the way a description is normalised before searching | done | "वीटो लेयर क्या करती है" and "BRG" now find the right passages |
| L4 | Answer in the language of the question; Hindi in Devanagari, Hinglish as typed | done | The people at the bin do not ask in English |
| L5 | Two worked examples in the Tier-3 prompt so a small model writes one clean sentence | done | Few-shot lifts a 3B model more than any setting |
| L6 | Answer memo per question and model for the life of the process; the 3B model's seven seconds happen once per question | done | A demo asks the same questions; a store asks them all day |
| L7 | Acceptance counters per caller (assistant, Copilot, Tier 3), exposed on the assistant's model block: accepted, declined, invented figure, too long | done | Tells us, per model, how often its words survive the guards; the number to compare 3B against 7B |
| L8 | Figure guard reads sentences: a trailing full stop no longer makes "0.9775." a different number from "0.9775" | done | A correct answer was being thrown away for punctuation |
| L9 | Prefer a larger local model when the machine has one: `SAMAN_OLLAMA_PREFER=qwen2.5:7b,qwen2.5:3b` picks the first present | done (opt-in) | This laptop has the 7B pulled; a workstation should use it, a 4 GB box should not |
| L10 | One bounded retry on a rate-limited remote call | done | A free tier meters tokens per minute; the demo must stutter, not stop |
| L11 | Run L1 for `qwen2.5:3b` and `qwen2.5:7b` locally; publish all three rows in the README; choose the default per machine size from the numbers | done (3B 15/16 · 9/16 · 1.2 s; 7B 16/16 · 10/16 · 2.5 s; remote 14/16 · 12/16; default stays 3B) | The decision the harness exists for |
| L12 | Stream the answer to the widget token by token | done | A 3B model reads as slow when the reader waits for the whole sentence; streaming makes seven seconds feel like two |
| L13 | Warm the memo at start with the assistant's suggested questions | done | The first click in a demo should not pay the model's cold start |
| L14 | Keep an eval log: every accepted answer with its sources, every refusal with its reason, so the harness grows from real questions people asked | done | A test set written by users beats one written by us |
| L15 | Quantisation and hardware notes per model size (Q4 for 3B and 7B on CPU; a GPU makes the 7B the default) in the install guide | done (docs/INSTALL.md) | The size question is a deployment question |
| L16 | Fine-tuning, only when the corpus is real: reviewer decisions and the documented question–answer pairs from L14, exported as JSONL (`make learn-corpus` exists); a LoRA on the local Qwen scored on the same harness before it is allowed to replace the base model | later | Today the corpus is mostly simulated labels; a model trained on them learns our generator. The harness is the gate |
| L17 | Distil the remote model's accepted answers into the local eval set, never into the local model's weights | later | A cheap way to grow L14 with good examples while keeping the local model honest |

### The learned pairwise model

| # | Item | Status | Why |
|---|---|---|---|
| P1 | Champion/challenger auto-retrain: after every 25 reviewer labels (simulated ones do not count) a challenger is trained in the background, scored on the held-out split, and promoted only if it is not worse; every attempt is recorded in a history file and on the audit chain | done | The loop that turns decisions into a better queue order without anyone pressing a button, and a record of every model that ever served |
| P2 | Richer, still readable features: 24 named features (the 15 plus identity coverage, held-for-review, equivalence flag, brand equal/differs, same CPSE, part number differs, token overlap, length ratio), kept because held-out AUC rose 0.9974 → 0.9986 and grey-band AUC 0.9655 → 0.9764 on the same labels; an old 15-feature model still loads by name | done | More signal for the same one-screen explanation, measured |
| P3 | Per-class held-out AUC, precision and recall on the admin page | done | The bearing queue and the chemical queue are different problems |
| P4 | Threshold suggestions per class from the labels, shown as suggestions with "not applied"; a registrar changes thresholds deliberately | done | The model may advise on policy; it may not set it |
| P5 | Retrain on real labels only once they outnumber the simulated ones; show a confusion matrix on real labels | done | Judged on people's decisions, not the generator's |
| P6 | Active learning in the queue: mix the most uncertain pairs with a few random ones so the model's blind spots are sampled too | done | Uncertainty sampling alone forgets what it never sees |

### More automation, with a human gate on each

| Item | Status | The gate |
|---|---|---|
| Auto-retrain (P1) | done | Promotion only if not worse; audited |
| Scheduled per-CPSE report | done | Sent to the CPSE's contact; every figure computed; assumptions attached |
| Auto-issue codes for clusters that pass every gate (anchored, all attributes agree, held-out precision above target for that class) | done | Registrar sets the policy per family; every issue audited; nothing issued for a class below target |
| Nightly incremental pipeline over new rows | done (`make pipeline --incremental` on the nightly line) | Runs record their stats; the dashboard shows the run id and time |
| Re-evaluate the held-out snapshot after each run | done | Already recorded on the run; the dashboard says when |
| Retire an unused legacy code suggestion (no stock, no PO, no movement in 24 months) | done | Suggestion only; migration plan needs approval |

## Reports to each CPSE

| Item | Status | Why |
|---|---|---|
| One document per CPSE, computed from the database: catalogue size and coded share; duplicates inside their own catalogue with examples; duplicates shared with each other CPSE; pending reviews by band and decisions made; their quality scorecard row and the weakest rate; stock, dead stock, transfers where they are source or destination with only their side priced; joint tenders they are part of and the saving attributable to them at the stated capture; Smart-Create prevention by their users; a list of concrete next actions with the count behind each | done | A steward should not have to open six screens to know what SAMAN found in their catalogue |
| Delivery by e-mail when SMTP is configured; otherwise an `.eml` written to an outbox, so an offline installation and the demo still produce the artefact; every send on the audit chain | done | Offline first, and a file a judge can open |
| Preview and Send from the Admin page for any CPSE; a steward's own report from the Home page; a CLI and a weekly cron line | done | On demand and on schedule |
| A ministry roll-up: the same report across CPSEs with per-CPSE attribution redacted to bands | done | The reader above the CPSE |

## Small add-ons judges ask about

| Item | Status | Effort |
|---|---|---|
| Export any table (search results, queue, dashboard section) as CSV | done | 1 d |
| A printable specification sheet from a golden record, for a GeM bid | next | 1 d |
| "Why?" on every card and Copilot answer: the refusal or merge reason as one sentence, already computed | done | 1 d |
| Keyboard shortcut help (`?`) on every screen | done | ½ d |
| A "what runs where" panel on the health page listing each engine, its version and whether it is local or remote | done | ½ d |
| Session activity per user on Admin (last sign-in, decisions, reports sent) | done | 1 d |
| Provenance tooltip on every dashboard figure: computed at, from how many rows, memo version | done | 1 d |
| Demo reset button for admins (restore the snapshot in under five seconds; exists as `make demo-restore`) | done | ½ d |

## What to improve in what already exists, regardless of stage

- **Reruns.** Incremental runs score only the rows that arrived since the
  last run; decided pairs, attachments and bin bindings survive a rerun (done).
- **Frontend test depth.** 135 unit tests cover the state machines; `make e2e`
  drives the five demo moves in a real browser (done).
- **The learned model's story.** Show its confusion matrix on real labels and
  hide it while labels are simulated.
- **Explanations.** Every refusal already carries its reason; surface it as
  one sentence on the Workbench card and in the Copilot answer.
- **Captions.** Every chart says the data is synthetic; when real data
  arrives, the same captions must say which source and which date.
- **Docs.** `docs/INSTALL.md`: the two shapes, every setting, what each
  engine needs, and how to size the model (done).

## What not to build

- A model that decides a match. The veto layer stays rules; the language
  model stays a writer.
- Trend charts, forecasts or rates from a single day of activity. Five
  decisions cannot support a rate.
- A cloud-only design. Offline first; remote only for a demo, and labelled.
- Fine-tuning on simulated labels. It teaches the generator, not materials.
- Anything that deletes a legacy row. Superseded means blocked, never gone.
