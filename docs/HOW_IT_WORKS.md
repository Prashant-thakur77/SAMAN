# How SAMAN works in practice

*The questions a judge, a CPSE's IT department or a ministry officer asks
before the technical ones: where it runs, who uses it, how the CPSEs and the
registry see each other, how a catalogue comes in and how codes go back.
Everything here describes what is built unless it says "planned"; what is
planned is also in `REFINEMENT_PLAN.md` and `KNOWN_GAPS.md`.*

---

## 1. Offline first: what that means here

The software needs **no internet to do its job**. It runs on a machine inside
a CPSE's own network, or the ministry's, keeps everything in a local database
(`data/app.db`), ships its own fonts, OCR engine and matching engines, and
never calls out on its own.

Three things *can* leave the machine. Each is off until an operator turns it
on, and each is labelled on screen while it is on:

| What | Why someone would turn it on | How it shows |
|---|---|---|
| a remote language model (`SAMAN_LLM_URL`) | a demo without a laptop that can run one | the health chip reads *remote · host* |
| an SMTP relay | to e-mail the weekly reports | otherwise reports are written to `data/outbox/` as `.eml` files |
| a tunnel or a public host | to show the platform to someone outside the network | the demo site is this shape |

The demo at `saman-wymm.onrender.com` is the single-container shape on the
public internet so that judges can open it; a CPSE would run the same image
on its intranet.

The phone **Scan** screen goes one step further: it installs as an app and
keeps working in a store with no signal. Recent scans, nameplate reading and
stock counts work on the device; counts queue and post in order when the
signal returns. A lookup needs the server, and the screen says so rather than
pretending.

## 2. Who the users are

| Role | Who, in real life | What they do in SAMAN |
|---|---|---|
| **Steward** (one per CPSE, or several) | the codification cell or materials officer at IOCL, ONGC, GAIL, CPCL, BPCL | uploads the catalogue, works the review queue for their rows, uses Smart-Create before raising a code, teaches house abbreviations, reads the weekly report |
| **Approver** (per CPSE) | a senior materials manager | confirms merges, approves substitutes, decides what a steward held back, can decide a whole page at once |
| **Engineer** (per CPSE) | a technical authority (mechanical, electrical, instrumentation) | approves an interchangeable part with a reason before it may be fitted |
| **Registrar** (ministry or registry) | the national codification authority | issues CNMCs, sets thresholds and the auto-issue policy, sees every CPSE attributed, runs the ministry roll-up |
| **Admin** | the IT owner of the installation | accounts and roles, engines, snapshots and restore, sovereign mode |
| **Auditor** | CAG or internal audit | reads everything, changes nothing, verifies the hash chain |
| **Viewer** | anyone else in the ministry | the public dashboards, no prices attributed |

Accounts are created by the admin on the Admin page and belong to people. The
"pick an account, the password is demo" screen is a demo setting
(`SAMAN_DEMO_LOGIN=false` in a real install turns it off). Sign-in with the
government directory (Parichay or the CPSE's own SSO) is **planned**.

## 3. How CPSEs and the registry see each other

There is no messaging between people. The shared thing is the **registry**:
one database holding every CPSE's catalogue rows, the golden records the
pipeline built across them, and the CNMC codes. Everyone signs into the same
system; what differs is **what each role can see**, enforced in one place
(`app/visibility.py`) so that the dashboards, the reports and the Copilot
cannot disagree with each other.

- A steward sees their own CPSE's rows in full, and the **shared golden
  layer**: that ONGC also stocks the same bearing under another name, what its
  standard description is, what its code is. What they do *not* see is
  another CPSE's price attributed: those appear as an anonymised range
  ("₹18–₹62 across 4 CPSEs"), enough to act on without exposing a
  competitor's contract.
- The registrar and the auditor see everything attributed. The ministry
  roll-up is theirs.
- The **review queue** is routed by role. A grey-band pair between an IOCL row
  and an ONGC row shows up for the stewards of both; an identity conflict
  goes to an approver; a substitute goes to an engineer. Whoever decides,
  the reason is recorded, and a decision can be taken back within a window.
- The **weekly report** per CPSE is how the registry speaks to a CPSE: one
  document computed from the database, redacted as that CPSE's own steward
  would see it, sent by e-mail or written to the outbox, with the concrete
  next actions and the count behind each.
- The **audit trail** is shared: every mutation by anyone, hash-chained, and
  an auditor verifies it with one click.
- **Restricted mode** is for two CPSEs that will not hand each other a
  catalogue at all. Each side encodes its descriptions locally (Bloom filters
  under a key the two exchange out of band); only the encodings are
  compared; the result is "you have N materials in common", never the rows.

### The two deployment shapes

**Today's, and the demo's: one registry node.** Hosted by the ministry or NIC
on the government intranet; every CPSE signs into it. This is the shape a
pilot with four or five CPSEs takes, and everything in this document runs on
it.

**Planned: federated nodes.** Each CPSE runs its own node with its own data;
signed, versioned bundles of golden records and codes travel between the
nodes and the registry (Stage 3 of the plan). The software is the same
either way; Restricted mode is the first piece of this shape that exists.

## 4. How a CPSE's data comes in

1. The CPSE exports its material master from SAP (MARA/MAKT: the material
   number, the forty-character description, the unit, the plant; long texts
   often on a second sheet) as CSV or Excel. **No change to SAP is needed for
   this step.**
2. The steward drops the file on the **Onboard** wizard. It reads the headers,
   proposes how each column maps (a table of aliases covers the SAP names and
   the common English ones), shows a **dry run** (rows accepted, rows rejected
   and why, with a CSV of the rejections and their original columns), then
   ingests.
3. The **pipeline** runs: normalise (house abbreviations the steward taught,
   Hindi tokens, units), classify into a material family, extract attributes,
   block, match across every catalogue in the registry, veto on
   identity-critical attributes, cluster, draft a golden record, and queue the
   uncertain pairs for people. On the demo estate of 12,000 rows this is about
   a minute.
4. A few hundred rows later, an **incremental** run scores only the new rows
   and their neighbours; nothing anyone has decided is asked again, and
   attachments and bin bindings follow their rows into the rebuilt clusters.
5. **Codes go back.** The Migration screen writes the CNMC cross-reference into
   the CPSE's material master (a mock SAP today; the RFC adapter and the BAdI
   hook exist for a real one and need a sandbox client to prove). The legacy
   code is **never deleted**: a superseded material is blocked, not gone, and
   every batch is journaled with its before-image so it can be rolled back.
6. From then on **Smart-Create** sits in front of "raise a new material code".
   The description is checked against the whole registry first, with the
   same matcher and veto layer the pipeline uses; the outcome, prevented or
   created anyway, is on the ledger either way. A scanned barcode, a
   photographed nameplate or a BAdI call from SAP all arrive at the same check.

## 5. Questions a judge will ask

**Who hosts it, and on what?** A CPSE's IT on a small server (2 cores and
4 GB is enough for the demo estate; `INSTALL.md` has the sizing), or NIC for
the registry node. Docker Compose with HTTPS in front. Backups are one
command; a restore drill takes seconds.

**What if two CPSEs disagree about a merge?** Nothing merges on its own in
the grey band. A person approves with a reason, the reason is on the chain,
and the decision can be undone within a window. A dispute above that is a
governance question, which is Stage 4 of the plan and not software.

**Can the numbers be trusted?** Every figure carries its provenance: computed
when, from how many rows, which run. Precision and recall are measured on a
held-out split the thresholds never saw. The audit ledger is a hash chain
that covers its own sequence numbers, so reordering is caught as well as
tampering.

**What does the language model do?** It words sentences and answers questions
from the project's own documents, and every figure it emits is checked
against its sources. It never decides a match. Sovereign mode turns it off
entirely and every screen still works.

**What is synthetic?** All the data, with full ground truth, which is what
makes the metrics honest. No real extract has been run yet; that is the first
external input the plan asks for.

**What is not built?** SSO, PostgreSQL for a multi-node registry, the
federation bundles, a live SAP connection, realised-savings tracking. Each is
named in `KNOWN_GAPS.md` and in the plan, with its finish line.

**What does a CPSE give up?** Nothing it did not already have to give the
ministry: its catalogue rows and the prices it paid, seen attributed only by
the registrar and the auditor. Restricted mode exists for the case where even
that is too much.

**How does a new CPSE join?** An admin registers it on the Onboard screen (a
code and a name), creates its steward's account, and the steward uploads the
first extract. There is no other step.
