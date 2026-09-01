# Known gaps

Per spec §10, anything scoped in the build spec but not yet built is recorded
here with a one-line reason. An honest gaps list is worth more than a hidden
hole. This file is updated at the end of every milestone.

## Status: end of M2

M1 delivered the scaffold; M2 delivers the data model, auth, the synthetic
estate with ground truth, ingest, normalization and extraction. Everything
below is *scheduled*, not dropped; the milestone that closes each item is named.

### Not built yet

| Gap | Reason | Closes in |
|---|---|---|
| No embeddings, matching, clustering or CNMC issuance | M3 scope; the pipeline currently ends after normalize + extract | M3 |
| `/api/metrics` does not exist | Needs a matcher before there is anything to measure | M3 |
| All 12 in-shell routes still render empty states | Nothing may be faked (§10); screens fill as their engines land | M3–M7.5 |
| `make demo` / `demo-restore` / `licenses` exit non-zero | Placeholders fail loudly rather than pretending to succeed | M3, M8, M8B |
| Tables are not virtualized; search is not paginated | Needed only once the UI renders large result sets | M8B |
| No `THIRD_PARTY_LICENSES.md` or CI license check | License tooling is the M8 scope | M8 |
| No screenshots or README demo script | Requires working screens | M9 |
| UI route guards by role | The API is the boundary that counts and it enforces roles today; UI guards land with the workbench | M4 |

### Deliberate deviations from the spec

Recorded rather than silently substituted, per the "how to use this spec" note.

| Item | What the spec says | What was built, and why |
|---|---|---|
| Seed volume | §7 asks for "~2,200 ground-truth products" rendered into "1–4 CPSE-specific descriptions" **and** "~3,000 raw items per CPSE" | Both cannot hold at once: 2,200 x up to 4 caps at 8,800, short of 12,000. Both numbers are honoured by reading the 2,200 as the cross-CPSE *shared* products — the ones with duplicates to find — and filling the remainder with singleton products unique to one CPSE, which is also how a real material master looks. Result: 2,200 shared products, ~11,800 rows across 4 CPSEs. |
| Benchmark profile multiplicity | §7 implies the same 1–4 renderings for `seed-large` | Eight equipment classes cannot express 150k *distinct* products (attribute-space capacity is ~14,200). The benchmark profile raises multiplicity instead, and allows one product to appear twice within a CPSE — itself a real phenomenon in CPSE masters. This profile is only ever used for the §8A performance run, never for metrics. |
| Optional dependencies | §0.4 names `splink` and `sentence-transformers` | Both sit in `requirements-optional.txt` rather than the base install, so the §0.4 degraded paths are what CI and the demo exercise by default. `make deps-optional` installs them and `/api/health` reports the change. |

### Watch items carried into M3

- **Cross-brand pairs are equivalents, not duplicates.** SKF 6205-2Z and FAG
  6205-2ZR share every identity_critical attribute and differ only on `brand`,
  which §2A defines as cosmetic — so the veto layer alone will not separate
  them. The matcher needs an explicit rule: two items each carrying a distinct
  manufacturer part number from different manufacturers are interchangeable,
  not the same material record. 360 such pairs are planted as ground truth.
- **Precision ceiling.** 2 pairs out of ~7,600 positives are textually identical
  across different truth groups, capping achievable precision at ~0.9997. Not
  material to the 0.92 gate.
