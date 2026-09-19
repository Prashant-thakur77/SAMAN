# SAMAN: who it is for, and what real life still needs

A prototype proves a method. Real life is a store at two in the morning, a
catalogue nobody has cleaned since 2004, an SAP client that cannot be touched
without a change request, and a registrar who will be asked in a committee
why one bearing got the code and another did not. This document says who
SAMAN is for, what each of them has today, what they would still be missing
on the day a CPSE switched it on, and the order in which to close those gaps.
`KNOWN_GAPS.md` records what the build spec asked for and what was built;
this is the list of what the spec never asked for and a deployment would.
`REFINEMENT_PLAN.md`, beside this file, turns it into stages with gates,
items and effort.

## Who it is for

Eight people, each with one moment when the platform has to answer.

| Who | The moment | What they have today | What they would still need |
|---|---|---|---|
| **Storekeeper** at the bin, **receiving clerk** at the gate | A part in one hand, a phone or a barcode gun in the other: *what is this, do we have it, what is its code?* | **Scan**: a barcode, a QR label, a CPSE code or a part number resolves to the material, its stock everywhere, what it is fitted to and its approved substitutes; a nameplate photographed and read on the phone itself; a printable label so the next scan is instant | Labels printed at receipt, not only on demand; a scanner on a handheld terminal that has no browser; nameplates in Hindi and Odia; a way to say "this bin holds this code" and have it stick |
| **Maintenance engineer** at 2 a.m. | A pump is down; the bearing is in someone else's store under someone else's name | **Scan** the pump's tag plate and see every spare on its bill of materials with how many are on the shelf here and how many a sister CPSE holds under whatever name; search across every CPSE, the item page's "also called", the substitutes an engineer approved for that equipment, a transfer suggestion with a rupee value | The one thing no prototype has: a real cross-CPSE stock feed, and a CMMS link so the tag plate's QR is the plant's own, not one this platform printed |
| **Data steward** at a CPSE | Owns a catalogue and is measured on its quality | Onboarding with SAP headers recognised, the Workbench, the quality scorecard with its weights printed, the ABC class | Bulk actions on the queue, a per-class dictionary of house abbreviations they can edit, a monthly quality report they can send upward, and the ability to say *no* to a national decision with a reason that stays on the record |
| **Approver / technical authority** | Signs that two things are the same, or that one may replace the other, for equipment where a wrong answer breaks something | Conflict queue, separation of duties, substitute approval bound to the equipment's criticality | Engineering data attached to the decision (datasheets, drawings), delegation when they are on leave, and an escalation path when two CPSEs' engineers disagree |
| **Registrar** at the national level | Issues the code and answers for it | Immutable CNMC with a check digit, the audit chain, the executive dashboard's "how the machine decided" block | A multi-writer registry (SQLite is one node's database), a formal code-issue policy, dispute handling, alignment with the Directorate of Standardisation's codification practice |
| **Procurement head / CFO** | Wants the joint tender and the number they can defend | Opportunity dashboard, joint-tender candidates with the capture assumption exposed, the savings ladder | Realised savings: what was actually paid after a consolidation, against the baseline; a tender-pack export; GeM category mapping so the consolidated demand can be floated |
| **Auditor** (CAG, internal) | Needs to know what happened, by whom, and that nothing was changed since | Hash-chained audit trail verified from the page, decisions with reasons, model weights in plain sight | Signed exports of the chain, retention policy, evidence bundles per code |
| **SAP basis / IT** | Has to connect it without breaking the ERP | The adapter contract, load files for LSMW/LTMC, an RFC adapter tested against a recorded fake, an API-key hook for a BAdI at MM01, a reversible migration with byte-identical rollback | A sandbox client to run it against, the proprietary RFC SDK, SSO, backups, monitoring, an upgrade path, and installation media for a network that has no internet |

## What real life needs that a prototype does not

In the order a pilot would hit them.

1. **Real catalogues.** Every figure in the demo is computed from a synthetic
   estate. The first real extract will have long-text tables, three
   languages, thirty years of abbreviations and columns nobody remembers the
   meaning of. The onboarding path accepts it today; the class templates and
   the abbreviation dictionary will need a week per CPSE of a steward's time.
2. **Classes.** Eight material classes cover the demo. A refinery's master
   has hundreds. A class is a YAML file of attributes, roles and tolerances,
   so adding one is data entry with a domain expert, but there is no tool for
   that entry and no way to derive a draft template from the rows themselves.
3. **One database, one writer.** SQLite is right for a CPSE's own node and
   wrong for a national registry with many writers. The schema is SQLAlchemy
   and moves to PostgreSQL without a rewrite; the audit chain, the memo and
   login throttling assume one process and would move to shared storage.
4. **Identity.** The demo has seven seeded accounts and a shared password by
   design. A deployment needs the government SSO (Parichay or the CPSE's own
   directory), MFA for registrars, and accounts that belong to people.
5. **SAP, live.** Three doors are built and none has been opened on a real
   system, because the RFC SDK is proprietary and no client was available.
   The first afternoon against a sandbox client will find the differences
   between the documented BAPIs and the configured ones.
6. **Operations.** Backups, a restore drill, monitoring, an offline install
   (the platform needs no internet at runtime, and the *installation* should
   not either), and an upgrade path that keeps issued codes intact.
7. **Measurement in the field.** Two numbers nobody has yet: minutes a
   reviewer spends per decision, and rupees actually saved after a joint
   tender. Both are one table and one screen away, and both are the numbers a
   ministry will ask for first.
8. **Governance.** Who owns a class template, who may issue codes for which
   family, how a CPSE disputes a merge, and how the CNMC relates to the
   Directorate of Standardisation's codification and to BIS. None of this is
   software; all of it decides whether the software is used.

## The plan

Four phases. Each has an acceptance gate in the spirit of the build spec's
§8 gates: a number that must be true before the next phase starts.

### Phase 0: to the demo

*Goal: a demo a judge can hold in their hand.*

- **Scan on the phone** (built): barcode and QR through the camera, a
  nameplate read on the device, a handheld gun into the same field, and a
  printable label so the loop closes.
- Collect fifty real nameplate photographs (a workshop, a lab, a hostel
  pump room; phones in bad light) and measure the reader on them. The
  current 0.967 is on drawn plates and says so.
- Hindi and Hinglish in search (built): the query is read the way a
  description is, so `वाल्व गेट 50NB` asks for gate valves; Smart-Create
  already tolerated a Hindi token. Still open: Hindi attribute words
  (`व्यास`, `दबाव`) inside attribute extraction, and Odia and Tamil terms.
- The link that does not sleep: the Student Developer Pack's credit buys a
  small always-on server for a year; move the compose stack there with the
  local language model and the voice engines.

*Gate:* a judge scans a label printed from the app with their own phone and
sees the material in under three seconds.

### Phase 1: a pilot (three months, two CPSEs, two families)

*Goal: real data, real users, real numbers.*

- A data-sharing agreement and a real extract from two CPSEs for bearings
  and valves; the steward's week per catalogue; class templates extended
  from the rows.
- PostgreSQL behind the same SQLAlchemy models; the memo, the audit chain
  and the throttle on shared storage.
- SSO and real accounts; the demo login switched off.
- A sandbox SAP client and the RFC adapter run against it; the BAdI hook at
  MM01 installed by the basis team.
- **Realised-savings ledger**: purchase orders after a consolidation, read
  through the adapter, compared with the baseline the opportunity dashboard
  computed. One table, one screen, one number a CFO can quote.
- **Reviewer time**: the Workbench records seconds per decision; the learned
  model's queue ordering is judged by that, not by AUC alone.

*Gate:* held-out precision above 0.95 on the two real families, and one
joint tender floated on a consolidated demand.

### Phase 2: scale (six to twelve months)

*Goal: the whole master, many CPSEs, one registry.*

- Class authoring: a tool that drafts a template from a class's rows (the
  attributes that appear, the units seen, the tolerances that separate
  variants) for an expert to approve.
- Vendor de-duplication with the same normaliser and an alias table.
- Federation: signed, versioned bundles of golden records and codes between
  CPSE nodes and the national registry; the export exists, the signature and
  import do not.
- GeM category and HSN carried on every code so a consolidated demand can be
  floated without reclassification.
- Labels at receipt: the goods-receipt screen prints the CNMC label as the
  box arrives.
- A progressive web app so the Scan screen installs on a phone and works
  in a store with no signal, syncing when it has one.

*Gate:* the registry issues codes for fifty classes across six CPSEs with a
registrar's decision time under one minute per code.

### Phase 3: institutionalise

*Goal: a standard, not a project.*

- Alignment with the Directorate of Standardisation's codification practice
  and a BIS working draft for the code's format and issue policy.
- A dispute process with an SLA, and a governance body that owns the class
  templates.
- Training for stewards and approvers; the assistant's document corpus
  becomes the manual.
- Procurement policy: when a joint tender is mandatory, and how savings are
  attributed between CPSEs.

*Gate:* a second ministry adopts the code without changing the software.

## How to work on it

- **One gate per phase, measured, not asserted.** The build spec's four
  gates kept the prototype honest; the pilot needs the same discipline on
  real data.
- **Every figure travels with its assumption.** The savings ladder shows the
  capture assumption beside the estimate. Keep doing that; a number without
  its assumption will be quoted without it.
- **Nothing decides unaccountably.** The veto layer is rules, the learned
  model orders and never decides, the language model words and never
  invents. Anything added should be able to answer "why" on the audit page.
- **The gaps list stays public.** `KNOWN_GAPS.md` is updated at the end of
  every milestone with what was not done and why. It has been worth more to
  reviewers than any claim.
- **Cadence.** Weekly: one measured improvement, its number in the README,
  its test in the suite. Monthly: a demo to a steward who was not in the room
  when it was built.

## The next ten things, in order

| # | Task | Effort | Why now |
|---|---|---|---|
| 1 | Fifty real nameplate photographs and a measured OCR score on them | 2 days | The reader is measured on drawn plates; a judge will ask about real ones |
| 2 | Hindi attribute words in extraction, and Odia and Tamil term tables (search transliteration is built) | 2 days | Half the descriptions in a real master carry them |
| 3 | Always-on host on the Student Pack credit, compose stack with the model | 1 day | The free host sleeps and has no language model |
| 4 | Reviewer seconds per decision, on the card and on the dashboard | 2 days | The first number a pilot will be judged on |
| 5 | Bulk actions on the Workbench queue (approve a page of high-band confirmations at once) | 2 days | 7,381 policy confirmations one card at a time is not a steward's afternoon |
| 6 | Class-template drafting from rows (attributes, units, tolerances seen) | 1 week | Eight classes do not cover a refinery |
| 7 | PostgreSQL behind the models; memo and throttle on shared storage | 1 week | The step from one node to a registry |
| 8 | Vendor alias table and normalised vendor overlap | 3 days | Overlap analysis matches exact strings today |
| 9 | Realised-savings ledger read through the ERP adapter | 1 week | Identified savings are a claim; realised ones are a fact |
| 10 | Signed bundles between nodes (export exists; sign and import do not) | 2 weeks | Federation is the shape a national registry takes |
