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
one national material code across CPSE
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

**Docker Spaces are not free.** Hugging Face allows only static Spaces on a free
account; creating this one answers `402 Payment Required` unless the account has
a PRO subscription. `deploy/single/README.md` lists the hosts that do run it for
nothing. With PRO, `make space SPACE=<user>/saman` does all of the below.

1. Create a Space at <https://huggingface.co/new-space>: **Docker**, blank template, CPU basic.
2. Push the whole repository to the Space (`git remote add space
   https://huggingface.co/spaces/<user>/saman && git push space main`), with
   `deploy/single/Dockerfile` copied to the root as `Dockerfile` and this file
   as the root `README.md`. The build wants the repository as its context.
3. The build installs the API, builds the frontend, generates the demo data
   and starts. It takes about ten minutes the first time.
4. Open the Space's own address, `https://<user>-<space>.hf.space`, rather than
   the framed page on huggingface.co: the sign-in cookie is first-party there.

After a push to GitHub, **Settings → Factory rebuild** on the Space rebuilds
from the new code; a plain rebuild may reuse the cached clone.

Optional, in the Space's *Settings → Variables and secrets*:
`SAMAN_SECRET_KEY` (a long random string) signs the session cookie;
`SAMAN_DEMO_LOGIN=false` hides the account picker.
