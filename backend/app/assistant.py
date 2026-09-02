"""The site assistant — the floating "Ask SAMAN" widget on every screen.

Three kinds of question, tried in this order:

1. **Navigation.** "Take me to the workbench", "open cluster 268", "audit
   kholo", "search 6205". Matched against a route catalogue that carries
   English and Hindi aliases, and answered with an *action* the interface
   performs rather than a sentence about where to click.
2. **About the system.** What a CNMC is, why 25 mm is not 30 mm, how to sign
   in, whether any of this is machine learning. A small knowledge base, each
   entry with the keywords that select it and the screen that shows it.
3. **About the data.** Anything else goes to the Copilot, which already owns
   the guards, the row-level visibility and the citations. The assistant adds
   nothing to that path and cannot get around it (§0.9b).

Everything here is deterministic and offline. The fuzzy matching is
`rapidfuzz`, the same library Tier 1 falls back to, and Devanagari input goes
through the same transliterator the matcher uses, so "वर्कबेंच खोलो" reaches
the workbench for the same reason "BEARING 6205" reaches "बेयरिंग 6205".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from . import copilot
from .normalize import apply_hindi_terms, has_devanagari, transliterate_devanagari
from .visibility import Scope

#: Below this the assistant does not pretend it understood a destination.
ROUTE_MATCH_THRESHOLD = 82
#: Words that turn a screen name into an instruction to go there.
_GO_WORDS = re.compile(
    r"\b(open|go\s+to|goto|take\s+me|bring\s+up|show\s+me|show|navigate|jump|"
    r"switch\s+to|visit|launch|start|kholo|khol|le\s+chalo|chalo|jao|dikhao|dikha|"
    r"dekho|dekhna|par\s+jao|pe\s+jao)\b",
    re.IGNORECASE,
)
#: Words that make the same screen name a question *about* it instead.
_ASK_WORDS = re.compile(
    r"\b(what|why|how|explain|meaning|means|is\s+a|is\s+the|does|kya|kaise|kyon|kyun|"
    r"matlab|samjhao|batao)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Route:
    path: str
    label: str
    aliases: tuple[str, ...]
    blurb: str


#: One entry per screen. Aliases are what people say, in the two languages the
#: catalogues themselves arrive in; the label is what the sidebar says.
ROUTES: tuple[Route, ...] = (
    Route("/", "Home", ("home", "start page", "dashboard home", "ghar", "shuru", "mukhya"),
          "Your queue if you are a steward; the national picture if you are a registrar."),
    Route("/search", "Search",
          ("search", "find", "look up", "lookup", "catalogue search", "khoj", "khojo",
           "dhundo", "dhoondo", "talash"),
          "One field across every organisation's catalogue."),
    Route("/workbench", "Workbench",
          ("workbench", "review queue", "review", "queue", "approve", "reject", "grey band",
           "adjudicate", "adjudication", "decisions", "samiksha", "manzoori",
           "varkabencha", "varkabench", "varkbench"),
          "Keyboard-first review of candidate matches, with the evidence beside them."),
    Route("/dashboard/executive", "Executive dashboard",
          ("executive", "executive dashboard", "kpi", "kpis", "progress", "analytics",
           "heatmap", "national picture", "pragati"),
          "Harmonisation progress across organisations."),
    Route("/dashboard/opportunity", "Opportunity dashboard",
          ("opportunity", "savings", "saving", "joint tender", "joint tenders", "price variance",
           "dead stock", "idle stock", "slow moving", "transfer suggestions", "overpay",
           "bachat", "kharcha"),
          "Joint tenders, price variance, idle stock and transfers."),
    Route("/smart-create", "Smart-Create",
          ("smart create", "smart-create", "smartcreate", "create material", "new material",
           "new code", "raise a code", "duplicate check", "check before creating", "camera",
           "scan", "photo", "nameplate", "naya material", "naya code"),
          "The duplicate check before a code is raised, camera input included."),
    Route("/pprl", "Restricted mode",
          ("restricted mode", "restricted", "pprl", "privacy", "private matching", "bloom",
           "encodings", "overlap", "compare catalogues", "without sharing", "gupt"),
          "Measure two organisations' overlap from encodings alone."),
    Route("/copilot", "Copilot",
          ("copilot", "co-pilot", "chat", "assistant screen", "ask a question", "sawal"),
          "Questions about the data, answered with citations and the query behind them."),
    Route("/onboard", "Onboard",
          ("onboard", "onboarding", "upload", "upload csv", "csv", "ingest", "import",
           "import catalogue", "add a cpse", "new cpse", "wizard", "catalogue upload"),
          "Upload a catalogue, map its columns, read the dry run, ingest."),
    Route("/migration", "Migration",
          ("migration", "migrate", "erp", "sap", "dry run", "dryrun", "rollback", "roll back",
           "apply batch", "journal", "legacy codes", "cross reference"),
          "Plan, dry run, impact, apply, verify, roll back against the ERP."),
    Route("/audit", "Audit",
          ("audit", "audit trail", "ledger", "hash chain", "verify chain", "events", "log",
           "history", "tamper", "lekha", "jaanch", "odita", "audita"),
          "Every mutation as a hash-chained event, verifiable from the page."),
    Route("/admin", "Admin",
          ("admin", "administration", "users", "roles", "user management", "engine health",
           "health", "sovereign mode", "settings", "prabandhan"),
          "Users, roles, engine health, the sovereign-mode toggle."),
    Route("/welcome", "Front page",
          ("front page", "landing", "landing page", "welcome", "about page", "homepage",
           "website home"),
          "The public page that explains how the system decides."),
    Route("/login", "Sign in",
          ("login", "log in", "sign in", "signin", "sign out", "logout", "switch user",
           "switch account", "change user"),
          "Pick a seeded account. Every one uses the password demo."),
)

#: Deep links the catalogue cannot express: an item, a cluster, a search term.
_ITEM = re.compile(r"\b(?:item|material|row)\s*(?:#|no\.?|number)?\s*(\d{1,7})\b", re.IGNORECASE)
_CLUSTER = re.compile(r"\bcluster\s*(?:#|no\.?|number)?\s*(\d{1,7})\b", re.IGNORECASE)
_CNMC = re.compile(r"\b([A-Z]{4}-\d{3}-\d{6}-\d)\b")
_SEARCH = re.compile(
    r"\b(?:search|find|look\s*up|lookup|khoj\w*|dhund\w*|dhoond\w*|talash)\s+(?:for\s+)?(.+?)\s*[?.!]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Topic:
    key: str
    keywords: tuple[str, ...]
    answer: str
    link: str | None = None
    link_label: str | None = None


#: What the assistant knows about the system itself. Kept short on purpose:
#: the answer is a paragraph and a place to go, not a manual.
TOPICS: tuple[Topic, ...] = (
    Topic(
        "what_is_saman",
        ("what is saman", "what does saman do", "about saman", "saman kya hai", "purpose",
         "what is this", "what is this site", "what is this website", "yeh kya hai"),
        "SAMAN reads the material catalogues of several public sector undertakings, works "
        "out which rows describe the same material, drafts one clean record for each, and "
        "issues a Common National Material Code, the CNMC. Anything uncertain goes to a "
        "person with the evidence beside it.",
        "/welcome", "Read the front page",
    ),
    Topic(
        "cnmc",
        ("cnmc", "what is the code", "national code", "check digit", "damm", "code format",
         "code kya hai"),
        "The CNMC is the code SAMAN issues: CCCC-SSS-NNNNNN-K. Four letters for the family, "
        "a three-digit segment, a six-digit serial issued once and never reissued, and a "
        "Damm check digit that catches every single-digit error and every adjacent swap. "
        "Issuing one is registrar-only and a code is immutable once issued.",
        "/welcome#code", "See a code taken apart",
    ),
    Topic(
        "how_it_decides",
        ("how does it work", "how does matching work", "how it decides", "how does it decide",
         "tiers", "pipeline", "matching engine", "how are duplicates found", "kaise kaam",
         "kaise karta"),
        "Five questions in order of cost. Exact anchors first, a part number or barcode "
        "settles it. Then field-by-field agreement weighted by how surprising it is. Then "
        "meaning, so SS316 lands beside STAINLESS STEEL 316. Then the veto: identity "
        "attributes compared in real units, and any mismatch refuses the pair. What is left "
        "goes to a person.",
        "/welcome#how", "See the five stages",
    ),
    Topic(
        "veto",
        ("veto", "refuse", "refusal", "25 mm", "look-alike", "lookalike", "identity critical",
         "identity-critical", "why not merged", "false merge", "trust"),
        "Two rows can read almost identically and still be different parts. Identity "
        "attributes such as bore, seal type and pressure class are compared in real units, "
        "and a disagreement on any of them refuses the match outright. No similarity score "
        "can overrule it, and the refusal is recorded with its reason.",
        "/workbench", "See refusals on the workbench",
    ),
    Topic(
        "equivalence",
        ("equivalent", "equivalence", "substitute", "substitution", "interchangeable",
         "cross reference", "crossref", "directed"),
        "Equivalence is a separate, directed relation. A 500 kg bearing can stand in for a "
        "200 kg requirement and not the other way round, so substitutes keep their own "
        "codes and carry a link that records the safe direction. Duplicates merge; "
        "equivalents do not.",
        "/search", "Find an item and open its equivalents",
    ),
    Topic(
        "golden_record",
        ("golden record", "standardization", "standardisation", "canonical description",
         "provenance", "template", "fused", "fusion", "where did this description come from"),
        "Each class has a description template. The golden record is rendered from it and "
        "the normalised attributes, deterministically, so the same cluster always yields the "
        "same bytes. Every fused field records which member it came from and which rule "
        "chose it, and the cluster page shows that provenance.",
        "/search", "Open a cluster from search",
    ),
    Topic(
        "migration_topic",
        ("how does migration work", "what is migration", "rollback", "roll back", "open po",
         "open purchase order", "held", "block", "never deleted", "sap"),
        "Plan, dry run, impact, apply, verify, roll back, against the ERP's MARA, MAKT, EKPO, "
        "MARD and MBEW. Records with open purchase orders are held automatically. A "
        "superseded material is blocked, never deleted, and rollback restores the ERP "
        "byte for byte.",
        "/migration", "Open Migration",
    ),
    Topic(
        "smart_create_topic",
        ("what is smart create", "prevent duplicates", "before creating", "point of creation",
         "ocr", "read a nameplate", "photograph", "camera input"),
        "Smart-Create runs the same matcher and the same veto layer before a new code is "
        "raised. The requester sees existing candidates ranked with confidence; creating "
        "anyway needs a reason, and the reason is audited. The camera input reads a "
        "material's own marking offline and feeds the reading into the same check.",
        "/smart-create", "Open Smart-Create",
    ),
    Topic(
        "restricted_topic",
        ("what is restricted mode", "how does pprl work", "bloom filter", "bloom filters",
         "dice", "without handing over", "privacy preserving"),
        "Two organisations encode their catalogues locally into keyed Bloom filters and only "
        "the encodings are compared, by Dice coefficient. Neither side learns a description "
        "it did not already hold. The cost is measured against the same ground truth as the "
        "main engine and shown on the screen.",
        "/pprl", "Open Restricted mode",
    ),
    Topic(
        "audit_topic",
        ("how is it audited", "audit chain", "hash chain", "tamper", "tampering", "reorder",
         "who changed", "verify the ledger"),
        "Every mutation is one event in a hash chain, and each hash covers its own sequence "
        "number as well as the previous hash, so reordering breaks the chain as visibly as "
        "editing. Verification re-walks from the genesis event and names the first broken "
        "sequence.",
        "/audit", "Open the audit trail",
    ),
    Topic(
        "roles",
        ("roles", "who can", "permissions", "registrar", "steward", "approver", "auditor",
         "viewer", "separation of duties", "kaun kar sakta"),
        "Six roles: registrar, admin, approver, steward, auditor, viewer. The API enforces "
        "them; the interface only hides what you cannot do. Whoever proposes or edits a "
        "golden record cannot approve it, and issuing a CNMC is registrar-only. A steward "
        "sees other organisations' prices as an anonymised band, never attributed.",
        "/admin", "Open Admin",
    ),
    Topic(
        "passwords",
        ("password", "passwords", "sign in", "login details", "credentials", "which account",
         "accounts", "demo account", "how do i log in", "kaise login"),
        "Every seeded account uses the password demo. The sign-in screen lists them: "
        "steward@cpcl.in, registrar@min.gov.in, approver@min.gov.in, auditor@cag.gov.in and "
        "admin@saman.gov.in. Pick one and type demo.",
        "/login", "Go to sign in",
    ),
    Topic(
        "metrics",
        ("metrics", "precision", "recall", "accuracy", "how good", "how accurate", "f1",
         "b-cubed", "results", "evaluation", "kitna sahi"),
        "Measured on a 40% held-out split that the thresholds never saw. Duplicate precision "
        "0.997 and recall 0.960; blocking recall 0.994; every planted trap refused. The full "
        "report, including the naive baseline and the weakest class named, is at "
        "/api/metrics and on the executive dashboard.",
        "/dashboard/executive", "Open the Executive dashboard",
    ),
    Topic(
        "offline",
        ("offline", "internet", "network", "cloud", "sovereign", "on premise", "on-premise",
         "air gap", "air-gapped", "data leave"),
        "Nothing here calls the network at runtime. Fonts are bundled, the models are local "
        "and optional, and each optional component falls back to a bundled one rather than "
        "failing. Whichever is active is stated at /api/health and on the Admin screen.",
        "/admin", "See engine health",
    ),
    Topic(
        "ml",
        ("machine learning", "ml", "nlp", "ai", "model", "models", "llm", "neural", "embedding",
         "embeddings", "is it ai", "does it use ai", "artificial intelligence", "deep learning"),
        "Yes, and deliberately in the places where it is checkable. Probabilistic record "
        "linkage (Fellegi-Sunter via splink, or rapidfuzz), character n-gram TF-IDF with "
        "SVD or sentence-transformer embeddings for meaning, rule-based extraction with a "
        "confidence gate, deep-learning OCR for the camera, Bloom-filter linkage for "
        "restricted mode, and thresholds tuned on a held-out split. A local language model "
        "may rephrase a sentence; it never decides which materials are the same.",
        "/admin", "See which engine is live",
    ),
    Topic(
        "run",
        ("how to run", "run it", "install", "setup", "set up", "make demo", "make dev",
         "docker", "start the app", "kaise chalaye", "kaise chalu"),
        "make setup, then make demo, then make dev. The API is on :8000 and the interface on "
        ":5173, or docker compose up for both. The first setup fetches packages; after that "
        "it runs with the cable out.",
        "/welcome", "Read the front page",
    ),
    Topic(
        "voice",
        ("voice", "microphone", "mic", "speak", "speech", "talk to you", "listen", "bol",
         "bolo", "awaaz"),
        "Press the microphone in this panel and speak; the browser transcribes and I answer. "
        "Turn the speaker on and I read replies aloud. Both use the browser's own speech "
        "engines, which on some browsers reach the vendor's servers, so an air-gapped "
        "deployment should keep to typing.",
        None, None,
    ),
)

#: What the panel offers before anyone has typed.
SUGGESTIONS = (
    "Take me to the workbench",
    "What is a CNMC?",
    "Which CPSE overpays for gaskets?",
    "How does it decide two rows are the same?",
    "Open cluster 268",
    "Where is idle stock of bearings?",
)


@dataclass
class Reply:
    kind: str
    answer: str
    action: dict[str, Any] | None = None
    citations: list[dict] = field(default_factory=list)
    sql: str | None = None
    rows: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    mode: str = "deterministic"
    matched: dict[str, Any] | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "answer": self.answer,
            "action": self.action,
            "citations": self.citations,
            "sql": self.sql,
            "rows": self.rows[:25],
            "suggestions": self.suggestions,
            "mode": self.mode,
            "matched": self.matched,
        }


def _navigate(route_or_path: Route | str, label: str | None = None) -> dict[str, Any]:
    if isinstance(route_or_path, Route):
        return {
            "type": "navigate",
            "to": route_or_path.path,
            "label": f"Open {route_or_path.label}",
        }
    return {"type": "navigate", "to": route_or_path, "label": label or "Open"}


def normalise(question: str) -> str:
    """Lower-case, transliterate Devanagari, map Hindi domain terms, squeeze space."""
    text = question or ""
    if has_devanagari(text):
        text = transliterate_devanagari(text)
    text = apply_hindi_terms(text)
    text = re.sub(r"[^\w\s#?.\-/]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def match_route(question: str) -> tuple[Route | None, int]:
    """The best-matching screen and its score, alias by alias.

    Longer aliases win ties, so "review queue" beats "review" and "smart create"
    beats "create" — the more specific phrase is the more informative one.
    """
    text = _GO_WORDS.sub(" ", normalise(question))
    text = re.sub(r"\b(the|a|an|to|me|please|page|screen|tab)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    best: tuple[Route | None, int, int] = (None, 0, 0)
    for route in ROUTES:
        for alias in route.aliases:
            # Whole-word containment is exact; fuzzy handles typos and case,
            # and only for aliases long enough that a near miss means something.
            if re.search(rf"\b{re.escape(alias)}\b", text):
                score = 100
            else:
                score = int(fuzz.partial_ratio(alias, text)) if len(alias) >= 6 else 0
            if score > best[1] or (score == best[1] and len(alias) > best[2]):
                best = (route, score, len(alias))
    return best[0], best[1]


def match_topic(question: str) -> Topic | None:
    text = normalise(question)
    best: tuple[Topic | None, int] = (None, 0)
    for topic in TOPICS:
        score = 0
        for keyword in topic.keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                # A multi-word keyword is far stronger evidence than a single one.
                score += 10 * len(keyword.split())
        if score > best[1]:
            best = (topic, score)
    return best[0]


def deep_link(question: str) -> dict[str, Any] | None:
    """An item, a cluster, a code or a search term named outright."""
    if m := _CLUSTER.search(question):
        return _navigate(f"/clusters/{m.group(1)}", f"Open cluster {m.group(1)}")
    if m := _ITEM.search(question):
        return _navigate(f"/items/{m.group(1)}", f"Open item {m.group(1)}")
    if m := _CNMC.search(question.upper()):
        return _navigate(f"/search?q={m.group(1)}", f"Search for {m.group(1)}")
    if m := _SEARCH.search(question):
        term = m.group(1).strip()
        # "search the catalogue" / "find bearings" name a place or a class, not a
        # query; leave those to the route matcher and the copilot.
        route, score = match_route(term)
        if term and score < ROUTE_MATCH_THRESHOLD and len(term) <= 60:
            return _navigate(f"/search?q={term}", f"Search for {term}")
    return None


def _looks_like_data_question(text: str) -> bool:
    return bool(
        copilot.match_template(text)
        or re.search(r"\b(how many|count|which cpse|top|list|show me the|price|stock|spend|"
                     r"vendor|tender|kitne|kitna|kaun sa)\b", text, re.IGNORECASE)
    )


def answer(db: Session, question: str, scope: Scope, current_path: str | None = None) -> Reply:
    """Route one utterance. The order is navigation, knowledge, then the Copilot."""
    question = (question or "").strip()
    if not question:
        return Reply("answer", "Ask me where to go, what something means, or a question "
                     "about the data.", suggestions=list(SUGGESTIONS))

    text = normalise(question)
    topic = match_topic(text)

    # The Copilot's guard is the assistant's guard. One set of rules, with one
    # reading: "what is the password" is the sign-in question the login screen
    # itself answers, not a request to read a credential from the database. The
    # credentials refusal yields to that topic; the injection refusals never do.
    refusal = copilot.guard(question)
    if refusal and not (
        topic is not None
        and topic.key == "passwords"
        and refusal.startswith("Credentials")
        and not re.search(r"\b(hash|secret|api|key|table|select|from)\b", text)
    ):
        return Reply("refusal", refusal, mode="refusal")

    wants_to_go = bool(_GO_WORDS.search(text))
    is_asking = bool(_ASK_WORDS.search(text))

    # 1. A place named outright, with a number or a term.
    if (link := deep_link(question)) and not is_asking:
        return Reply("navigate", f"Taking you there: {link['label'].lower()}.", action=link,
                     matched={"deep_link": link["to"]})

    route, score = match_route(text)

    # 2. "Open the workbench" / "workbench" / "वर्कबेंच खोलो".
    if route and score >= ROUTE_MATCH_THRESHOLD and (wants_to_go or not is_asking) and not (
        topic and is_asking
    ):
        # A bare data question that happens to contain a screen word, such as
        # "how many CNMCs have been issued", belongs to the Copilot.
        if not wants_to_go and _looks_like_data_question(text) and not (
            text == route.label.lower() or text in route.aliases
        ):
            pass
        else:
            already_here = current_path is not None and current_path == route.path
            line = (
                f"You are already on {route.label}. {route.blurb}"
                if already_here
                else f"Opening {route.label}. {route.blurb}"
            )
            return Reply("navigate", line, action=None if already_here else _navigate(route),
                         matched={"route": route.path, "score": score})

    # 3. Something about the system itself.
    if topic:
        action = _navigate(topic.link, topic.link_label) if topic.link else None
        return Reply("answer", topic.answer, action=action, matched={"topic": topic.key})

    # 4. Everything else is a question about the data: the Copilot's job.
    result = copilot.answer(db, question, scope)
    if result.refused:
        return Reply("refusal", result.text, mode="refusal")
    kind = "copilot"
    action = _navigate("/copilot", "Continue in the Copilot")
    useful = bool(result.rows or result.citations or result.template)
    if not useful and route and score >= ROUTE_MATCH_THRESHOLD:
        # Not a data question after all; the nearest screen is the best help.
        return Reply(
            "navigate",
            f"I could not answer that directly. {route.label} is the nearest place: {route.blurb}",
            action=_navigate(route), matched={"route": route.path, "score": score},
        )
    return Reply(
        kind,
        result.text,
        action=action,
        citations=result.citations,
        sql=result.sql,
        rows=result.rows,
        mode=result.mode,
        matched={"template": result.template} if result.template else None,
    )
