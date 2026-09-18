---
title: SAMAN
emoji: 🏛️
colorFrom: gray
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: One Nation, One Material Code — CPSE material harmonisation
---

# SAMAN on a free host

**Standardised Asset & Material Analysis Network** — an offline-first prototype
for SIH 2026 problem SIH26099: one national material code across CPSE
catalogues, with the matching pipeline, the review workbench, the analytics and
the audit ledger all running here in one container.

Source and documentation: <https://github.com/Prashant-thakur77/SAMAN>.

Sign in with any account on the login page; the shared demo password is shown
there. The data is a synthetic estate of four CPSE catalogues generated at build
time — every figure on every screen is computed from it, none is typed in.

## What runs here, and what does not

| Works | Not on this host |
|---|---|
| Search, item pages, clusters, the review Workbench, CNMC issue | The local language model (the assistant answers from the documents instead, and says so) |
| Executive and Opportunity dashboards, quality scorecard, metrics | Anything written here survives only until the container restarts |
| Onboarding a CSV, Smart-Create, substitutes, migration plans, audit chain | The SAP RFC adapter (the mock ERP is used) |
| Voice in and out, OCR on the camera input | |

## Publishing this Space

1. Create a Space at <https://huggingface.co/new-space>: **Docker**, blank template, free CPU.
2. Upload two files from the repository's `deploy/hf/` directory into the Space:
   `Dockerfile` and this `README.md`. Nothing else.
3. The build clones the GitHub repository, builds the frontend, generates the
   demo data and starts. It takes about ten minutes the first time.
4. Open the Space's own address, `https://<user>-<space>.hf.space`, rather than
   the framed page on huggingface.co: the sign-in cookie is first-party there.

After a push to GitHub, **Settings → Factory rebuild** on the Space rebuilds
from the new code; a plain rebuild may reuse the cached clone.

Optional, in the Space's *Settings → Variables and secrets*:
`SAMAN_SECRET_KEY` (a long random string) signs the session cookie;
`SAMAN_DEMO_LOGIN=false` hides the account picker.
