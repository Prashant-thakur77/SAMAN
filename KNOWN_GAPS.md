# Known gaps

Per spec §10, anything scoped in the build spec but not yet built is recorded
here with a one-line reason. An honest gaps list is worth more than a hidden
hole. This file is updated at the end of every milestone.

## Status: end of M1

M1 covers scaffolding only — tokens, theme, shell, routing and transitions.
Everything below is *scheduled*, not dropped; the milestone that closes each
item is named.

| Gap | Reason | Closes in |
|---|---|---|
| No data model, auth or seed data | M1 is scaffolding; models and seeding are the M2 scope | M2 |
| All 12 in-shell routes render empty states, not data | Nothing may be faked (§10); screens fill as their engines land | M3–M7.5 |
| Login form posts to an endpoint that does not exist yet | Auth layer is M2; the form and its 4px shake are wired against the real call | M2 |
| `make seed` / `seed-large` / `demo` / `demo-restore` / `licenses` exit non-zero | Placeholders fail loudly rather than pretending to succeed | M2, M3, M8, M8B |
| Tables are not virtualized | Needed only once 150k-row datasets exist | M8B |
| No `THIRD_PARTY_LICENSES.md` or CI license check | License tooling is the M8 scope | M8 |
| No screenshots or README demo script | Requires working screens | M9 |
| `splink` and `sentence-transformers` are not installed by default | Keeps base install light and makes the §0.4 degraded paths the default-tested path; `make deps-optional` installs them | by design |
