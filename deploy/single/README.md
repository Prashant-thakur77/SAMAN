# SAMAN without the laptop

`deploy/docker-compose.prod.yml` runs SAMAN properly: separate web and API
containers, a mounted `data/` that survives restarts, and the local language
model beside the API. It runs wherever you run it, which for most of this
project has meant a laptop and a tunnel — and the link dies when the lid closes.

This directory is the other shape: **one image, one port, no volume**. The
frontend is built into it and served by the API process itself, and the
demo estate is generated during the build, so the container answers the moment
it starts. That is what a free host can keep running.

```bash
make image                 # build it
make image-run             # look at it on http://localhost:7860
make image-run MEM=512m    # rehearse a free plan's memory before trusting one
make image EXTRAS=voice    # with local speech recognition, synthesis and OCR
```

## What it gives up

| Kept | Given up |
|---|---|
| Every screen, the whole pipeline, the dashboards, the audit chain | The local language model. The assistant answers from the project's documents and says so on `/api/health`. |
| Search, review, CNMC issue, onboarding, Smart-Create, substitutes, migration | Anything written after the build. Decisions and uploads live until the container restarts, then the demo is fresh again. |
| The mock ERP and the SAP load files | The SAP RFC adapter, which needs a real system to talk to. |
| Voice and OCR, with `EXTRAS=voice` and enough memory | Voice and OCR on a 512 MB plan. |

## Where to put it

**Render** — a blueprint is already in the repository root as `render.yaml`.
On render.com choose New → Blueprint and pick this repository; it builds and
serves at `https://<name>.onrender.com`. The free plan is 512 MB and a tenth of
a CPU, and it sleeps after 15 minutes idle and takes about a minute to wake, so
open the link yourself before handing it to anyone.

**Koyeb** — the same image, a free web service of the same size. No blueprint
file: point it at this repository and set the Dockerfile path to
`deploy/single/Dockerfile`.

**A virtual machine** (Oracle Cloud's Always Free tier, or any other) — the
honest answer for a demo that must be quick and always awake. Two cores and
12 GB run the whole thing, `EXTRAS=voice` included, and with that much memory
the compose stack in the parent directory is the better fit anyway, local
language model and all.

**Hugging Face Spaces** — `huggingface/` holds the Space card and a script that
publishes and waits. Docker Spaces need a PRO subscription; on a free account
the API refuses with `402 Payment Required` and only static Spaces are allowed.

## What to set on any of them

`SAMAN_SECRET_KEY` to a long random string, which signs the session cookie —
`render.yaml` generates one. `SAMAN_SECURE_COOKIES=true` behind HTTPS, which
every host above terminates for you. `SAMAN_DEMO_LOGIN=false` if you would
rather the login page did not offer the accounts and print the shared password.
`SAMAN_LLM_URL`, `SAMAN_LLM_KEY` and `SAMAN_LLM_MODEL` to give the link a
language model through a free OpenAI-compatible API (Groq, Gemini); the health
page then says the model is remote. Without them the assistant answers from
the documents in template mode and says so.

A free host has no mail relay, so the per-CPSE catalogue report's Send button
writes an `.eml` into the container's `data/outbox/` (gone at the next
restart) and says so in its reply. Set `SAMAN_SMTP_HOST`, `SAMAN_SMTP_USER`,
`SAMAN_SMTP_PASSWORD` and `SAMAN_SMTP_FROM` to a relay you have and the same
button mails it.
