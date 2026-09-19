# Contributing to SAMAN

*How the repository is worked on. Short, because the rules are few and the
checks enforce most of them.*

## Setting up

```bash
make setup      # backend/.venv on Python 3.12 (uv if present) + frontend deps; needs the internet once
make demo       # synthetic estate, pipeline, held-out metrics; exits non-zero if the gate fails
make dev        # API on :8000 with reload, UI on :5173
make help       # every target with a one-line description
```

Python 3.12 and Node 22 or newer. Nothing else is required; the optional
engines (`make deps-optional`, `deps-ocr`, `deps-stt`, `deps-tts`) are exactly
that, and the application says on `/api/health` which ones it found.

## The rules

1. **Nothing decides unaccountably.** The veto layer stays rules; the language
   model words sentences and never decides a match; every grey-band pair is a
   person's decision; every mutation goes through `audit.record`.
2. **Every figure is computed and carries its provenance.** No constant that
   looks like a measurement. A number on a screen says when it was computed
   and from what.
3. **Offline by design.** No runtime network call unless an operator
   configured it, and then it is labelled on screen. Fonts, models and
   engines are self-hosted.
4. **Permissive licences only.** `make licenses` regenerates
   `THIRD_PARTY_LICENSES.md` and fails on GPL/AGPL in the required set; CI
   runs it.
5. **Say "synthetic".** Every chart and report over the demo estate says the
   data is synthetic. When real data arrives, the same captions must name the
   source and the date.
6. **Gaps are public.** A limitation goes in `KNOWN_GAPS.md` with what was
   found and what was done, not in a comment.

## Before a commit

```bash
make check      # ruff · 1,320 backend tests · type-check · 141 frontend tests · production build · licence gate
make e2e        # the five demo moves in a real browser, with the app running (before a demo)
```

`make check` is what CI runs on every push. A change that moves a measured
number updates the README's Results table in the same commit, with the
command that produced it.

Commit messages are one plain sentence saying what changed and why it
matters, in the voice of the rest of the log (`git log --oneline` shows it).
No attribution trailers.

## Where to put things

| Change | Goes in |
|---|---|
| an engine (matching, extraction, analytics…) | `backend/app/<module>.py`, pure, tested in `backend/tests/test_<module>.py` |
| an endpoint | `backend/app/routers/<area>.py`, thin; the engine does the work |
| a screen | `frontend/src/routes/<Screen>.tsx`; shared pieces in `components/`; the typed client in `lib/api.ts` |
| a setting | `backend/app/config.py`, then the table in `docs/INSTALL.md` |
| a measured result | the README's Results section, with the command |
| a limitation | `KNOWN_GAPS.md` |
| a decision about what to build next | `docs/REFINEMENT_PLAN.md` |

## Verifying a screen

Playwright against the built UI is how screens are checked here: `make
screenshots` regenerates every image in `docs/screenshots/` from the demo
database, and `backend/scripts/e2e_demo.py` is the pattern for driving a
flow and asserting on what the screen says rather than on the API. Chromium
is looked for under `~/.cache/ms-playwright`.

## Reporting a problem

Open an issue with the screen or command, what you expected, what you saw,
and the line from `/api/health` that names the engines in use. If a number
looks wrong, include the provenance line under it (computed at · rows · run).
