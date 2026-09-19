# Installing SAMAN in a CPSE

*The two shapes an installation takes, what each engine needs, every setting,
and how to size the optional language model. Nothing here needs the internet
after the install; that is the point.*

---

## 1. Two shapes

| | **Laptop** (a pilot, a steward's desk, a demo) | **Server** (one CPSE, or the registrar's node) |
|---|---|---|
| How it runs | `make setup && make demo && make dev` | `docker compose` from `deploy/`: Caddy in front (HTTPS on a hostname), the API behind it, `../data` mounted |
| Users | a handful, same building | a CPSE's stewards and approvers over the intranet |
| Database | SQLite at `data/app.db` (WAL) | the same file; SAMAN is single-process by design (login throttling and the memo live in the process) |
| Model | none, or Ollama on the same machine | none, Ollama beside the API (`PROFILE=llm`), or a remote endpoint the operator chooses |
| Backups | `make demo-snapshot` (VACUUM INTO both databases) | the same, on a cron; copy `data/` |

The single container in `deploy/single/` is a third shape for a host that
has no laptop behind it (a free cloud plan): the API serves the built UI and a
demo database baked at build time. It is for showing the platform, not for a
CPSE's data.

## 2. What the machine needs

| Component | Minimum | Comfortable | Notes |
|---|---|---|---|
| CPU / RAM for the core | 2 cores, 2 GB | 4 cores, 4 GB | the demo estate (12k rows) runs the full pipeline in ~60 s and peaks at 0.6 GB; the 156k-row benchmark took 19 min and 8.1 GB |
| Disk | 2 GB | 10 GB | the demo database is 161 MB; the benchmark 5.9 GB; uploads and reports grow with use |
| Python | 3.12 | 3.12 | `make venv` uses `uv` when present |
| Node | 22 | 22 | build only; the server never runs Node |
| Browser | Chromium- or Firefox-based, current | Chrome on Android for the phone scanner (camera, torch, install) | iOS Safari installs the Scan screen but shows no torch |

Everything optional degrades to a working fallback and says so on
`/api/health` and the Admin page's *What runs where* table.

## 3. Engines, and what each one costs

| Engine | Installs with | Runs | Needs | Without it |
|---|---|---|---|---|
| rapidfuzz, scikit-learn, pint | `make deps` (required) | local | nothing | — |
| splink (Tier 1 probabilistic linkage, DuckDB) | required set | local | ~300 MB RAM extra during a run | rapidfuzz-only scoring; both meet the gate |
| sentence-transformers (Tier 2) | `make deps-optional` | local | ~500 MB, a one-time model download | TF-IDF char n-grams + SVD, which is what every number in the README was measured with |
| rapidocr (nameplate OCR on the server) | `make deps-ocr` | local | ~40 MB weights | the browser's tesseract.js still reads on the phone |
| faster-whisper (speech in) | `make deps-stt` | local, CPU | ~140 MB weights, ~1 s per utterance | the browser's own recogniser where it has one |
| piper (speech out) | `make deps-tts` | local, CPU | ~75 MB voice | the browser's voices where it has any |
| tesseract.js, zxing | shipped in the frontend | browser | nothing on the server | — |
| Ollama (language model) | separate install, `ollama pull <model>` | local | see §4 | the deterministic adjudicator; every screen works |

## 4. Sizing the language model

The model never decides anything. It rephrases the Tier-3 sentence, answers
questions from the project's own documents, and wordsmiths Copilot prose;
every figure it emits is checked against its sources and refused otherwise.
So the size question is a latency and a hardware question, not a correctness
one. `make llm-eval` measures whichever model is configured on sixteen
questions (acceptance, correctness against expected words, seconds); run it
on the machine that will serve and read the numbers before choosing.

| Model | Quantisation | RAM while loaded | Typical answer, CPU only | When |
|---|---|---|---|---|
| `qwen2.5:3b` (default) | Q4_K_M (Ollama's default pull) | ~2.5 GB | 5–8 s for a two-sentence answer on a 4-core laptop CPU; ~1.2 s on a 6 GB laptop GPU (measured: 15/16 accepted, 9/16 correct on the harness) | a 4–8 GB machine; a pilot |
| `qwen2.5:7b` | Q4_K_M | ~5 GB | 12–20 s CPU; ~2.5 s on a 6 GB laptop GPU (measured: 16/16 accepted, 10/16 correct) | a workstation or server with 16 GB, or a GPU |
| remote endpoint (`SAMAN_LLM_URL`) | — | none locally | under a second | a demo without a laptop; **questions and retrieved passages leave the machine**, and the health chip says so |
| none | — | — | — | sovereign mode, or any machine where the above do not fit |

Streaming and the answer memo make the small model feel faster than it is:
the first sentence appears as soon as it is complete and checked, and the
demo's questions are answered once at start (`SAMAN_WARM_ANSWERS`). Prefer
the larger model only when the machine has it: `SAMAN_OLLAMA_PREFER=
qwen2.5:7b,qwen2.5:3b` picks the first one present. Nothing here is
fine-tuned; the model reads the documents at question time.

## 5. Settings

All are environment variables (`deploy/.env` for compose; the shell for
`make dev`). Defaults are the safe ones.

| Variable | Default | What it does |
|---|---|---|
| `SAMAN_DB_PATH` | `data/app.db` | the SQLite file; the mock ERP sits beside it as `erp_mock.db` |
| `SAMAN_SECRET_KEY` | a development value | signs sessions; **set it** on any machine that is not yours |
| `SAMAN_SECURE_COOKIES` | `false` | `true` behind HTTPS (compose sets it); adds HSTS |
| `SAMAN_DEMO_LOGIN` | `true` | the account picker with the shared password `demo`; **`false` in a CPSE**, where accounts are created on the Admin page |
| `SAMAN_SOVEREIGN_MODE` | `false` | ignore any configured model; the Copilot answers from reviewed queries alone |
| `SAMAN_TIER1_ENGINE` | `auto` | `splink` or `rapidfuzz` to pin Tier 1 |
| `SAMAN_DISABLE_OPTIONAL` | `false` | run with the required set only |
| `OLLAMA_URL`, `OLLAMA_MODEL` | auto-detect on `localhost:11434`, `qwen2.5:3b` | the local model; `SAMAN_OLLAMA_AUTODETECT=false` to stop looking |
| `SAMAN_OLLAMA_PREFER` | empty | comma list; the first model present is used |
| `SAMAN_LLM_URL`, `SAMAN_LLM_KEY`, `SAMAN_LLM_MODEL` | unset | an OpenAI-compatible remote endpoint; labelled remote everywhere it is used |
| `SAMAN_ERP_ADAPTER` | `mock` | `rfc` for the pyrfc adapter (see `docs/sap-integration.md`) |
| `SAMAN_API_KEYS` | empty | keys a BAdI or a script may call Smart-Create with |
| `SAMAN_STATIC_DIR` | empty | the built frontend for the API to serve itself (the single container) |
| `SAMAN_WARM_DASHBOARDS` | `false` | compute the dashboards, reports and the roll-up at start (deployments turn it on) |
| `SAMAN_WARM_ANSWERS` | `true` | answer the demo's document questions into the memo at start when a model is configured |
| `SAMAN_ANSWER_LOG` | `eval/assistant-answers.jsonl` | every model answer and refusal; empty turns it off |
| `SAMAN_AUTO_RETRAIN`, `SAMAN_RETRAIN_EVERY` | `true`, `25` | the champion/challenger loop on reviewer labels |
| `SAMAN_UNDO_WINDOW_S` | `300` | how long a Workbench decision can be taken back |
| `SAMAN_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM`, `_STARTTLS` | unset | report delivery; without a host, reports go to `data/outbox/` as `.eml` |
| `SAMAN_OUTBOX_DIR` | `data/outbox` | where those `.eml` files go |

## 6. The routine

```
# first day
make setup            # venv + frontend deps (needs the internet once)
make deps-ocr deps-stt deps-tts   # optional engines, downloaded once into data/models
make demo             # synthetic estate + pipeline + metrics; or `make seed` then onboard real extracts
make demo-snapshot    # the restore point

# every night (cron), after the day's uploads
30 2 * * *  cd /opt/saman/backend && .venv/bin/python -m app.cli pipeline --incremental \
            && .venv/bin/python -m app.cli evaluate \
            && .venv/bin/python -m app.cli autoissue --apply >> /var/log/saman-nightly.log 2>&1

# every Monday
0 7 * * 1   cd /opt/saman/backend && .venv/bin/python -m app.cli report --all --send >> /var/log/saman-report.log 2>&1

# before a demo
make e2e              # the five demo moves in a real browser
make demo-restore     # back to the restore point in a second
```

An upload of a few hundred rows through the Onboard screen runs the pipeline
incrementally on its own; the nightly line exists for extracts dropped by
other means. Decided pairs, attachments and bin bindings survive any rerun.

## 7. What leaves the machine

Nothing, unless the operator configures it: a remote model endpoint (the
health chip says *remote · host* while it is in use), SMTP for reports, or a
tunnel for a demo. Fonts, OCR models and the frontend are self-hosted; the
service worker caches nothing under `/api/`. Restricted mode exchanges Bloom
fingerprints between two CPSE nodes, never plaintext. The Admin page's *What
runs where* table lists every engine with its version and whether it is
local, in the browser, or remote.
