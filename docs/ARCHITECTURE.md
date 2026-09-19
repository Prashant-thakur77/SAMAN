# SAMAN architecture

*The system in six diagrams: who touches it, what it is made of, how a
catalogue row becomes a code, how a request is scoped, how it is deployed,
and how the ledger holds. Diagrams are Mermaid and render on GitHub; every
name in them is a real module, table or route in this repository.*

---

## 1. System context

```mermaid
flowchart LR
    subgraph People
        S[Steward · per CPSE]
        A[Approver / Engineer · per CPSE]
        R[Registrar · ministry]
        AU[Auditor]
        ST[Storekeeper · phone]
    end

    subgraph SAMAN["SAMAN registry node (offline)"]
        UI[React UI]
        API[FastAPI]
        DB[(SQLite · WAL)]
        UI --> API --> DB
    end

    subgraph Systems["A CPSE's systems"]
        SAP[(SAP MM · MARA/MAKT)]
        FILES[CSV / Excel extracts]
    end

    S -->|onboard, review, Smart-Create| UI
    A -->|decide, approve substitutes| UI
    R -->|issue CNMCs, policy, roll-up| UI
    AU -->|verify the chain| UI
    ST -->|scan, count, bind bins| UI

    FILES -->|upload| API
    SAP -.->|RFC adapter · BAdI hook · load files| API
    API -.->|CNMC cross-reference, reversible| SAP

    OPT[Optional, labelled: remote LLM · SMTP]
    API -.-> OPT
```

Nothing leaves the node unless an operator configures it; the dotted lines
are the optional or planned integrations, and each is named on screen when
it is in use (`docs/HOW_IT_WORKS.md` §1).

## 2. Components

```mermaid
flowchart TB
    subgraph Frontend["frontend/ · React 18 + Vite + TypeScript"]
        Routes["19 routes<br/>Search · Workbench · Substitutes · Cluster · Compare<br/>Executive · Opportunity · Copilot · Audit<br/>Onboard · Migration · Smart-Create · Scan · Label<br/>Restricted mode · Admin · Home · Landing · Login"]
        Assist["Ask SAMAN assistant<br/>navigate · explain · query · voice"]
        SW["Service worker<br/>Scan works offline"]
    end

    subgraph Backend["backend/app · FastAPI + SQLAlchemy 2"]
        subgraph Routers["26 routers under /api"]
            r1[auth · admin · health]
            r2[ingest · pipeline · search · clusters]
            r3[workbench · substitutes · relations]
            r4[dashboard · metrics · reports · autoissue]
            r5[copilot · assistant · scan · smart_create]
            r6[migration · pprl · learn · abbreviations · cnmc]
        end
        subgraph Engines["Engines (pure modules)"]
            e1[normalize · extract · taxonomy · units · numeric]
            e2[blocking · embed · linkage · match · compare · equivalence]
            e3[cluster · standardize · cnmc · adjudicate · learn]
            e4[analytics · opportunity · inventory · quality · reports]
            e5[knowledge · llm · copilot · ocr · stt · tts]
        end
        Cross["visibility · audit · cache · capabilities · config"]
        Routers --> Engines
        Routers --> Cross
    end

    subgraph Storage["data/"]
        DB[(app.db · 35 tables)]
        ERP[(erp_mock.db · MARA/MAKT/EKPO/MARD/MBEW)]
        Files[uploads · attachments · models · outbox · eval]
    end

    Frontend -->|JSON over /api, session cookie| Backend
    Backend --> Storage
```

Every engine is importable and testable without the web layer; the routers
are thin. The three cross-cutting modules are the ones that must never be
bypassed: `visibility` (who sees which price), `audit` (every mutation on the
chain), `cache` (dashboards memoised on the estate's version).

## 3. From a catalogue row to a code

```mermaid
flowchart LR
    RAW[(raw_items<br/>CSV/xlsx rows)] --> N

    subgraph P["Pipeline · app/pipeline.py"]
        N["normalize + extract<br/>house abbreviations, Hindi tokens,<br/>class, attributes with units"]
        E["embed<br/>TF-IDF char n-grams + SVD<br/>(MiniLM optional)"]
        B["blocking · 7 passes<br/>mpn · gtin · text · class+band<br/>token · identity · ANN"]
        M["match · tiered<br/>T0 anchors → T1 rapidfuzz/splink<br/>→ T2 semantic → veto layer"]
        C["cluster<br/>connected components,<br/>golden record drafted"]
        Q["relations<br/>equivalents, substitutes,<br/>equipment context"]
        N --> E --> B --> M --> C --> Q
    end

    M -->|"high ≥ 0.86: merge"| C
    M -->|"grey 0.45–0.86"| W["Review queue<br/>Tier 3 recommendation,<br/>a person decides"]
    M -->|"low < 0.45: distinct"| X[kept as evidence]
    W -->|approve / reject / undo| C
    C --> G[(golden_records)]
    G -->|registrar, or auto-issue under policy| K[(cnmc · CNMC issued)]
    K --> MIG["Migration<br/>cross-reference into SAP,<br/>journaled, reversible"]
    K --> SC["Smart-Create<br/>checked before a new code"]
    L["Learned pairwise model<br/>orders the queue, never decides"] -.-> W
```

Thresholds come from `make tune` on the 60% tuning split and are frozen in
`match.py`; every number reported is measured on the 40% held-out split.
The veto layer is rules over identity-critical attributes and overrides any
score. The language model, where present, words the Tier-3 sentence and
never decides.

## 4. A request, scoped

```mermaid
sequenceDiagram
    participant U as Steward (CPCL)
    participant UI as React
    participant API as FastAPI
    participant V as visibility.Scope
    participant M as cache.memo
    participant DB as SQLite

    U->>UI: open Opportunity
    UI->>API: GET /api/dashboard/opportunity (session cookie)
    API->>V: scope_for(user) → role=steward, cpse=CPCL
    API->>M: memo(("opportunity", *scope.view_key, …), compute)
    alt estate unchanged since last compute
        M-->>API: cached figures
    else something on the ledger changed a figure
        M->>DB: 30-odd queries
        DB-->>M: rows
        M-->>API: figures, stamped with provenance
    end
    API->>V: redact: other CPSEs' prices → anonymised band
    API-->>UI: JSON + visibility note
    UI-->>U: page, every figure with "computed at · rows · run"
```

The same `Scope` gates the Copilot's reviewed queries and the weekly
reports, so no screen can become a bypass. The memo key is the estate's
version (ledger head of estate-changing events, latest run, row counts, the
day), so a stale figure cannot be served and a sign-in does not recompute
anything.

## 5. Deployment shapes

```mermaid
flowchart TB
    subgraph L["Laptop · pilot or demo"]
        l1["make demo && make dev<br/>API :8000 · UI :5173 · SQLite"]
    end

    subgraph C["CPSE server · docker compose"]
        c0[Caddy · HTTPS]
        c1[API container · serves nothing external]
        c2[(../data mounted)]
        c3["Ollama beside it (PROFILE=llm), optional"]
        c0 --> c1 --> c2
        c1 -.-> c3
    end

    subgraph S["Single container · a free cloud plan"]
        s1["deploy/single/Dockerfile<br/>API serves the built UI,<br/>demo database baked in"]
    end

    subgraph F["Planned · federated"]
        f1[CPSE node A] <-->|"signed bundles of<br/>golden records + codes"| f0[Registry]
        f2[CPSE node B] <--> f0
        f1 <-.->|"Restricted mode today:<br/>Bloom encodings only"| f2
    end
```

Today's registry is one node that every CPSE signs into, with row-level
visibility doing the separating. Restricted mode is the first piece of the
federated shape that exists; the bundles are Stage 3 of the plan.

## 6. The ledger

```mermaid
flowchart LR
    G["genesis<br/>seq 1"] --> E1["seq 2 · ingest<br/>hash = H(seq, ts, user, action, entity, payload, prev)"] --> E2["seq 3 · cluster.merge"] --> E3["seq 4 · cnmc.issue"] --> En["… seq n"]
    En --> V{"GET /api/audit/verify<br/>re-walks the chain"}
    V -->|every link holds| OK[intact]
    V -->|a hash or a sequence differs| BAD["first break at seq k"]
```

Each hash covers its own sequence number, so reordering is detected as well
as tampering. Every mutation goes through `audit.record`; a decision, a
merge, an issued code, a migration batch and its rollback, a policy change
and a sign-in are all events. Reads are not. Sign-ins are folded on the
Audit page by default and are excluded from the memo key because they change
no figure.

## 7. Where things live

```
backend/
  app/               engines and routers (see §2); main.py wires them
  tests/             1,320 tests; conftest seeds and runs the pipeline once
  scripts/           e2e_demo.py (five demo moves in a browser), screenshots, licences
frontend/
  src/routes/        one file per screen
  src/components/    Shell, Assistant, primitives (Table, Chip, Field…), charts
  src/lib/           api.ts (typed client), session, i18n, csv, motion, hooks
  public/            manifest, service worker, icons, the OCR engine
deploy/              docker compose, Caddy, the single-container image
data/                the databases, uploads, models, outbox (git-ignored)
docs/                INSTALL · HOW_IT_WORKS · ARCHITECTURE · PROJECT_BRIEF ·
                     REFINEMENT_PLAN · ROADMAP · sap-integration · screenshots
```
