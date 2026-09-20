# SAMAN in four minutes: the demo script

*A story with a storekeeper in it, told in Indian English, timed to 3½–4
minutes with the clicks written in. Every number is what a freshly seeded
`make demo` shows on screen. The five moves in it are the ones `make e2e`
checks in a browser, so run that first; take `make demo-snapshot` too, so a
wrong turn costs a second and not the demo.*

**Before they arrive:** `make demo`, `make dev`, sign in as **R. Krishnan ·
registrar**, leave the browser on **Search** with the box empty. Phone on the
table, signed in, on **Scan**. Dark theme off; the projector prefers light.

---

## 0:00 — The bearing that was bought three times (30 s)

*Stand still for this one. No clicks yet.*

> Good morning. Let me start with a storekeeper. Sharma-ji sits in the
> mechanical store at a refinery in Tamil Nadu. Last month a pump tripped and
> the maintenance team asked him for a 6205 bearing. He checked the system,
> found nothing, and raised an indent. It came in three weeks. Meanwhile the
> same bearing was sitting in his own store under another name, and eleven
> hundred kilometres away, in a sister company's store, under a third name.
>
> This is not a Sharma-ji problem. Every public-sector company writes its
> own catalogue in its own style. The same physical item has a different code
> and a different description in every one of them, so nothing joins up:
> not the stock, not the price, not the buying.
>
> SAMAN joins them. One national code for every real item. Let me show you
> how, in four minutes.

## 0:30 — Four companies, four spellings (35 s)

*Type `6205` in Search. Press Enter.*

> Here is Sharma-ji's bearing. Eight rows, four companies. Look at the
> spellings: `BRG,BALL,6205,ZZ` from one company, `NSK - BEARING - BALL -
> 6205 - ZZ` from another, and this one, `बेयरिंग 6205 ZZ`, written in Hindi.
> Same bearing. Today nobody can see that these are the same, because no
> system reads across companies.

*Click the first row. The item page opens.*

> SAMAN read them and put them together. This is the raw record on the
> left, exactly as the company wrote it, and on the right the golden record
> it now belongs to, with its national code. Below that, the stock: three
> companies, three plants, one tied-up value. Sharma-ji's bearing was in
> stock the whole time; he just could not see it.

## 1:05 — The machine shows its working (40 s)

*Go to Workbench. The Grey tab is open by default.*

> Now the honest part. Of the pairs the platform scored, 99.4 per cent it
> decided on its own, and every one of those is inspectable. The rest come
> here, to a person. This is one of them.

*Point at the two records, then the attribute comparison.*

> Two records side by side. The scores from each tier. And this table: the
> attributes it read, with the identity-critical ones marked — bore,
> outer diameter, width, seal. All four agree. The recommendation says
> "probably the same material" and tells you why, in a sentence.

*Press `A`. The toast says "approved". Press `U`.*

> I approve with one key. And if I was wrong, I take it back with one key.
> Nothing here is decided by the machine; the machine recommends, the
> person decides, and the ledger keeps both.

*Click the Auto-low tab, point at one card's "refused because" line.*

> This tab matters more. These are the pairs it *refused*. A 25-millimetre
> bore is not a 30-millimetre bore, however similar the words look. In
> SAMAN, similarity never overrides a specification. That rule is code, not a
> model, and it was right on every one of the 380 traps we planted.

## 1:45 — Stopping the next duplicate (40 s)

*Go to Smart-Create. Paste into the description:*
`वाल्व GATE 32NB CL 300 CS FLGD 51.1 BAR KITZ`
*Click "Check before creating".*

> Cleaning up the past is half the job. The other half is stopping the
> next one. Here is a request as an engineer would actually type it:
> abbreviated, reordered, one word in Hindi.

*Wait for the result: "Already in the catalogue", 99.8%.*

> Ninety-nine point eight per cent: this valve already has a national
> code. Look what it read from the text: the size, the class, the material,
> the end connection, the brand. And down here, a near miss it ruled out:
> "close, but the size is 25, not 32." The indent never gets raised. That is
> where the money is.

*If a phone is to hand: tap "Photograph the marking" and shoot the nameplate
on the table. One sentence: "It reads the marking, not the part."*

## 2:25 — What it is worth, with the assumption on the table (35 s)

*Go to Executive dashboard. Point at "Decided without a human", then at the
provenance line under the figures.*

> Every figure on this page is computed from the database, and every one
> carries where it came from: computed at, from how many rows, from which
> run. Nothing is typed in.

*Go to Opportunity. Point at the savings figure, then drag the discount
slider.*

> Two hundred and eleven crore identified across joint tenders, price
> variance and idle stock. Watch the assumption: it says sixty per cent of
> the price spread is capturable, and if you disagree, move it. The number
> moves with it. We show the assumption because a number without one is a
> claim, not a measurement.

*Click the Price variance tab. Point at a flagged row.*

> And here: one company paying two and a half times the median of the
> others for the same gasket, per base unit, pack sizes normalised. Flagged
> as a place to look, not a verdict; the rule that flagged it is printed
> right above the table.

## 3:00 — The audit trail, and the phone (30 s)

*Go to Audit. Click "Verify chain".*

> Everything anyone did, mine included, is on this ledger: a hash chain,
> where every entry covers its own sequence number, so a tampered or
> reordered record breaks the chain. Verified, just now, in front of you.

*Pick up the phone. Scan the bin label on the table. The result appears.*

> And back to Sharma-ji. He scans the bin label, and the phone tells him
> what this is, what it is called in every company, how much is held where,
> and its national code. It works in a store with no signal. This is the
> whole platform, at the shelf, in his hand.

## 3:30 — Close (20 s)

*Return to Home. Stop clicking.*

> Everything you saw runs on this laptop, offline, no cloud, no keys. The
> matcher measured 99.7 per cent precision and 96 per cent recall on a
> held-out split it never trained on. The data today is synthetic, and every
> screen says so; the first thing we want is a real extract. One nation, one
> material code. Thank you.

---

## If something goes wrong

| What | Do |
|---|---|
| A screen will not load | `make demo-restore` (one second), reload; keep talking about the ledger while it comes back |
| Smart-Create takes long | it is the language model wording the sentence; say so ("the wording is the model's; the decision is not"), the result is already on screen |
| The phone has no network | Scan still opens and shows recent scans; say that is the point, then do the lookup on the laptop's Scan page |
| Someone asks "is this real data?" | "Synthetic, with full ground truth, which is what makes the numbers honest. Every screen says so. Real extracts are the first thing we need." |
| Someone asks "does the AI decide?" | "No. Rules veto, people decide, the model recommends and words the reason. Sovereign mode turns the model off and every screen still works." |

## Questions they will ask, with the one-line answers

- **How does it work offline?** Everything is local: database, engines,
  fonts, OCR. Nothing leaves the machine unless an operator configures it,
  and then it is labelled on screen.
- **Who owns the code?** The registrar at the ministry issues it; the
  company keeps its legacy code, cross-referenced, never deleted.
- **What about SAP?** Export from SAP today, no change needed; the RFC
  adapter and the BAdI hook exist for a live connection and need a sandbox.
- **Can a company see another's prices?** No. A steward sees an anonymised
  range; only the registrar and the auditor see prices attributed. Restricted
  mode compares two catalogues without either handing one over.
- **How long to onboard a company?** An upload, a column mapping, a dry run,
  and about a minute of pipeline for twelve thousand rows.
