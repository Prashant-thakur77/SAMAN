"""Classification and attribute extraction — spec §2 (M2) and §2A.1.

Two jobs, in order:

1. **Classify** the normalized text into one of the taxonomy classes, with a
   confidence score. Below `CLASS_CONFIDENCE_MIN` the item lands in the
   `unclassified` pool. That gate matters: an item with the wrong class gets
   the wrong identity_critical fields, which silently disables the veto layer.
   §2A.1 requires that we never allow a schema-less silent match, so
   unclassified items are restricted to exact anchor-key matching downstream.

2. **Extract attributes** with per-class regex rules, plus a standard-designation
   parser for bearings. When a parsed designation and the free text disagree
   (6205 implies a 25 mm bore but the text says 30 mm), that is recorded as a
   conflict for review rather than resolved by silently trusting one source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .data.bearings import DEEP_GROOVE_DIMS, SEAL_SUFFIXES, bore_from_code
from .data.brands import ALL_BRANDS, BRAND_ALIASES, BRANDS_BY_CLASS
from .numeric import parse_number
from .taxonomy import UNCLASSIFIED, get_schema, real_classes

#: Below this, an item goes to the unclassified pool (§2A.1).
CLASS_CONFIDENCE_MIN = 0.45


# --------------------------------------------------------------------------
# Standard designation parsing (§2B evidence source 1)
# --------------------------------------------------------------------------

_BEARING_DESIGNATION = re.compile(
    r"\b(6[0123]\d{2})\s*[-/]?\s*(2ZR|2RSR|2RS1|2RS|2ZN|DDU|ZZ|2Z|RS|Z|C3)?\b"
)


@dataclass
class Designation:
    raw: str
    kind: str
    attrs: dict[str, object] = field(default_factory=dict)


def parse_bearing_designation(text: str) -> Designation | None:
    """`6205-2Z` -> bore 25 mm, OD 52 mm, width 15 mm, seal ZZ."""
    m = _BEARING_DESIGNATION.search(text)
    if not m:
        return None

    number, suffix = m.group(1), (m.group(2) or "").upper()
    dims = DEEP_GROOVE_DIMS.get(number)
    bore = dims[0] if dims else bore_from_code(number[2:])
    if bore is None:
        return None

    attrs: dict[str, object] = {"bore_mm": bore, "seal_type": SEAL_SUFFIXES.get(suffix, "OPEN")}
    if dims:
        attrs["outer_dia_mm"] = dims[1]
        attrs["width_mm"] = dims[2]
    return Designation(raw=m.group(0).strip(), kind="iso_bearing", attrs=attrs)


_THREAD = re.compile(r"\bM(\d{1,3})(?:\s*[Xx*]\s*(\d+(?:\.\d+)?))?\b")


def parse_metric_thread(text: str) -> Designation | None:
    """`M12x1.75` -> nominal 12 mm, pitch 1.75 mm."""
    m = _THREAD.search(text)
    if not m:
        return None
    nominal = float(m.group(1))
    pitch = float(m.group(2)) if m.group(2) else None
    label = f"M{m.group(1)}" + (f"X{m.group(2)}" if m.group(2) else "")
    return Designation(
        raw=m.group(0),
        kind="metric_thread",
        attrs={"thread": label, "thread_nominal_mm": nominal, "thread_pitch_mm": pitch},
    )


# --------------------------------------------------------------------------
# Shared field patterns
# --------------------------------------------------------------------------

_P = {
    "size_nb": re.compile(r"\b(\d{1,4}(?:\.\d+)?)\s*(?:NB|DN|NOMINAL BORE)\b|\bDN\s*(\d{1,4})\b"),
    "pressure_class": re.compile(r"\b(?:CLASS|CL)\s*(150|300|600|900)\b|\b(150|300|600|900)\s*(?:#|LB)\b|\bCL(150|300|600|900)\b"),
    "schedule": re.compile(r"\bSCH(?:EDULE)?\s*[-]?\s*(20|40|80|160)\b|\bSCH(20|40|80|160)\b|\b(XS|XXS)\b"),
    "thickness": re.compile(r"\b(\d+(?:\.\d+)?)\s*MM\s*(?:THK|THICK|THICKNESS)\b|\b(?:THK|THICKNESS)\s*(\d+(?:\.\d+)?)\s*MM\b"),
    # Both orders occur: "GRADE 8.8" and "8.8 GRADE", "AR GRADE" and "GRADE AR".
    "grade": re.compile(
        r"\bGRADE\s*(4\.6|8\.8|10\.9|12\.9)\b|\b(4\.6|8\.8|10\.9|12\.9)\s*GRADE\b"
        r"|\bGRADE\s*(LR|AR|GR|TECH)\b|\b(LR|AR|GR|TECH)\s*GRADE\b"
    ),
    "length_mm": re.compile(r"\b(\d{1,4}(?:\.\d+)?)\s*MM\s*(?:LG|LONG|LENGTH)\b|\b(?:LG|LENGTH)\s*(\d{1,4}(?:\.\d+)?)\s*MM\b"),
    "cores_csa": re.compile(r"\b(\d{1,2})\s*(?:C|CORE|CORES)?\s*[Xx*]\s*(\d+(?:\.\d+)?)\s*(?:SQMM|SQUARE MILLIMETRE|MM2)\b"),
    "csa": re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:SQMM|SQUARE MILLIMETRE|MM2)\b"),
    "voltage": re.compile(r"\b(\d+(?:\.\d+)?)\s*(KV|KILOVOLT|V|VOLT)\b"),
    # Two digits minimum: a single digit before C is a cable core count
    # ("3C X 25 SQMM"), not a temperature.
    "temp_max": re.compile(r"\b(-?\d{2,4})\s*(?:DEG\s*)?C\b(?!\w)"),
    "pressure_bar": re.compile(r"\b(\d+(?:\.\d+)?)\s*BAR\b"),
    "load_kg": re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:KG|KILOGRAM)\b"),
    "concentration": re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:PCT|%|PERCENT)\b"),
    "bore_mm": re.compile(r"\b(\d{1,4}(?:\.\d+)?)\s*MM\s*(?:BORE|ID|INNER DIAMETER)\b|\bBORE\s*(\d{1,4}(?:\.\d+)?)\s*MM\b"),
    "od_mm": re.compile(r"\b(\d{1,4}(?:\.\d+)?)\s*MM\s*(?:OD|OUTER DIAMETER)\b|\bOUTER DIAMETER\s*(\d{1,4}(?:\.\d+)?)\s*MM\b"),
    "width_mm": re.compile(r"\b(\d{1,4}(?:\.\d+)?)\s*MM\s*(?:W|WIDTH|WD)\b|\bWIDTH\s*(\d{1,4}(?:\.\d+)?)\s*MM\b"),
    "length_m": re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:M|METRE)\s*(?:LG|LENGTH)?\b"),
}

_ENUM_TOKENS = {
    "seal_type": {"ZZ": "ZZ", "2Z": "ZZ", "2RS": "2RS", "RS": "2RS", "OPEN": "OPEN"},
    "body_material": {
        "WCB": "WCB", "SS316": "SS316", "SS304": "SS304",
        "CARBON STEEL": "CS", "CAST IRON": "CI",
    },
    "end_connection": {
        "FLANGED": "FLANGED", "THREADED": "THREADED",
        "BUTTWELD": "BUTTWELD", "SOCKETWELD": "SOCKETWELD",
    },
    "material": {
        "SS316-GRAPHITE": "SS316-GRAPHITE", "SS304-PTFE": "SS304-PTFE",
        "SS316-PTFE": "SS316-PTFE", "COMPRESSED ASBESTOS FIBRE": "CAF",
        "CS-A106B": "CS-A106B", "CS-A53": "CS-A53", "SS316": "SS316", "SS304": "SS304",
        "CARBON STEEL": "CS",
    },
    "conductor": {"COPPER": "CU", "ALUMINIUM": "AL"},
    "insulation": {"XLPE": "XLPE", "PVC": "PVC"},
    "finish": {"ZINC": "ZINC", "PLAIN": "PLAIN", "HDG": "HDG", "HOT DIP GALVANISED": "HDG"},
    "helmet_class": {"CLASS A": "A", "CLASS B": "B", "CLASS C": "C", "CLASS E": "E"},
    "standard": {"IS2925": "IS2925", "EN397": "EN397"},
    "shell_material": {"HDPE": "HDPE", "ABS": "ABS", "FRP": "FRP"},
    "harness_type": {"RATCHET": "RATCHET", "PINLOCK": "PINLOCK"},
    "chin_strap": {"2-POINT": "2-POINT", "4-POINT": "4-POINT"},
    "ventilation": {"NON-VENTED": "NON-VENTED", "VENTED": "VENTED"},
    "brim": {"FULL BRIM": "FULL BRIM", "PEAK": "PEAK"},
    "grade": {"LABORATORY REAGENT": "LR", "ANALYTICAL REAGENT": "AR", "TECHNICAL": "TECH"},
    # Every substance the seed generator can emit must be recoverable, or the
    # class loses its identity_critical attribute and the veto layer goes blind.
    "substance": {
        s: s
        for s in (
            "SODIUM HYDROXIDE", "HYDROCHLORIC ACID", "SULPHURIC ACID", "NITRIC ACID",
            "PHOSPHORIC ACID", "ACETIC ACID", "CALCIUM CHLORIDE", "SODIUM CHLORIDE",
            "SODIUM CARBONATE", "POTASSIUM HYDROXIDE", "METHANOL", "ETHANOL",
            "ISOPROPYL ALCOHOL", "ACETONE", "TOLUENE", "XYLENE", "HEXANE",
            "AMMONIUM CHLORIDE", "SODIUM SULPHATE", "POTASSIUM PERMANGANATE",
            "HYDROGEN PEROXIDE", "CITRIC ACID", "OXALIC ACID", "BORIC ACID",
        )
    },
}


def _first_group(m: re.Match | None) -> str | None:
    """Our patterns use alternatives, so take whichever group actually matched."""
    if not m:
        return None
    return next((g for g in m.groups() if g is not None), None)


def _num(text: str, key: str) -> float | None:
    g = _first_group(_P[key].search(text))
    if g is None:
        return None
    parsed = parse_number(g)
    return parsed.value if parsed else None


def _enum(text: str, field_name: str) -> str | None:
    """Longest token first so 'SS316-GRAPHITE' wins over 'SS316'."""
    table = _ENUM_TOKENS.get(field_name, {})
    for token in sorted(table, key=len, reverse=True):
        if re.search(rf"\b{re.escape(token)}\b", text):
            return table[token]
    return None


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassGuess:
    class_code: str
    confidence: float
    scores: dict[str, float]

    @property
    def is_confident(self) -> bool:
        return self.class_code != UNCLASSIFIED


def classify(norm_text: str) -> ClassGuess:
    """Keyword-and-pattern scoring with a confidence gate.

    Confidence is the winning class's share of total evidence, so two classes
    scoring equally produce ~0.5 and fall below the gate rather than picking one
    arbitrarily.
    """
    text = (norm_text or "").upper()
    scores: dict[str, float] = {}

    for schema in real_classes():
        score = 0.0
        for kw in schema.keywords:
            if re.search(rf"\b{re.escape(kw.upper())}\b", text):
                # A longer keyword is more specific evidence than a short one.
                score += 1.0 + min(len(kw), 12) / 12.0
        # The class noun appearing verbatim is strong evidence.
        if re.search(rf"\b{re.escape(schema.noun)}\b", text):
            score += 1.5
        if score:
            scores[schema.code] = score

    # A parsed standard designation is decisive: it is self-describing.
    if parse_bearing_designation(text):
        scores["bearing.ball.deep_groove"] = scores.get("bearing.ball.deep_groove", 0.0) + 3.0

    if not scores:
        return ClassGuess(UNCLASSIFIED, 0.0, {})

    total = sum(scores.values())
    best_code = max(scores, key=lambda c: scores[c])
    confidence = scores[best_code] / total if total else 0.0

    if confidence < CLASS_CONFIDENCE_MIN:
        return ClassGuess(UNCLASSIFIED, confidence, scores)
    return ClassGuess(best_code, confidence, scores)


# --------------------------------------------------------------------------
# Brand / MPN
# --------------------------------------------------------------------------

_MPN_CANDIDATE = re.compile(r"\b(?=[A-Z0-9-]{4,24}\b)(?=[A-Z0-9-]*\d)[A-Z0-9]+(?:-[A-Z0-9]+)*\b")

#: Tokens that look like part numbers but are specification vocabulary. Letting
#: any of these through would create a false Tier-0 anchor key, which merges
#: unrelated items and destroys precision far more cheaply than it earns recall.
_SPEC_TOKEN = re.compile(
    r"^(?:"
    r"SCH\d+|CL\d+|CLASS\d+"                       # schedules, pressure classes
    r"|IS\d+|EN\d+|BS\d+|DIN\d+|ANSI\d+|API\d+"     # standards
    r"|ASTM[A-Z0-9]*|ASME[A-Z0-9]*"
    r"|M\d+(?:X\d+(?:\.\d+)?)?"                     # metric threads
    r"|\d+(?:\.\d+)?(?:MM|CM|KG|BAR|V|KV|C|NB|DN|SQMM|MM2|PCT|M|W)?"  # dimensions
    r"|\d+C"                                        # cable core counts
    r")$"
)

#: An explicit marker is the most reliable signal a part number follows.
_MPN_MARKER = re.compile(
    r"\b(?:PART NUMBER|PART NO|PN|MPN|CAT NO|CATALOGUE NO|MODEL|ORDER CODE)\s*[:\-]?\s*"
    r"([A-Z0-9][A-Z0-9./-]{3,23})\b"
)


def _spec_vocabulary(attrs: dict[str, object], class_code: str) -> set[str]:
    """Every token that is a known specification value for this item."""
    stop: set[str] = {b.upper() for b in ALL_BRANDS}
    stop |= {a.upper() for a in BRAND_ALIASES}
    for spec in get_schema(class_code).attributes.values():
        stop |= {v.upper() for v in spec.values}
    for value in attrs.values():
        if isinstance(value, str):
            stop.add(value.upper())
        elif isinstance(value, (int, float)):
            stop.add(str(value))
            stop.add(str(int(value)) if float(value).is_integer() else str(value))
    return stop


def extract_brand(text: str, class_code: str | None = None) -> str | None:
    """Prefer a brand known to the class; fall back to any known brand."""
    for alias, canonical in BRAND_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return canonical
    preferred = BRANDS_BY_CLASS.get(class_code or "", ())
    for brand in (*preferred, *ALL_BRANDS):
        if re.search(rf"\b{re.escape(brand)}\b", text):
            return brand
    return None


def extract_mpn(
    text: str,
    designation: Designation | None = None,
    attrs: dict[str, object] | None = None,
    class_code: str = UNCLASSIFIED,
) -> str | None:
    """Best manufacturer part-number candidate in the text.

    Precision over recall by design. A wrong MPN becomes a Tier-0 anchor key
    and merges unrelated items outright, whereas a missing one merely falls
    through to the similarity tiers. So we accept a candidate only when it is
    positively identified, never as a leftover.

    In order of trust:
      1. a parsed standard designation (self-describing and verifiable)
      2. a token introduced by an explicit marker ("PART NO ...")
      3. a mixed letter+digit token that is not specification vocabulary
    """
    if designation and designation.kind == "iso_bearing":
        return designation.raw.replace(" ", "")

    stop = _spec_vocabulary(attrs or {}, class_code)

    if m := _MPN_MARKER.search(text):
        token = m.group(1)
        if token.upper() not in stop and not _SPEC_TOKEN.match(token):
            return token

    best: str | None = None
    for m in _MPN_CANDIDATE.finditer(text):
        token = m.group(0)
        if token in stop or _SPEC_TOKEN.match(token):
            continue
        has_alpha = any(c.isalpha() for c in token)
        has_digit = any(c.isdigit() for c in token)
        if not (has_alpha and has_digit) or len(token) < 5:
            continue
        # Prefer the longest; hyphenated codes break ties as part numbers
        # are conventionally segmented.
        if best is None or (len(token), "-" in token) > (len(best), "-" in best):
            best = token
    return best


# --------------------------------------------------------------------------
# Attribute extraction
# --------------------------------------------------------------------------


@dataclass
class Extraction:
    class_code: str
    class_confidence: float
    attrs: dict[str, object]
    mpn: str | None
    designation: str | None
    conflicts: list[dict[str, object]]


def _extract_for_class(text: str, class_code: str) -> dict[str, object]:
    """Per-class regex rules. Only attributes declared in the schema are kept."""
    schema = get_schema(class_code)
    out: dict[str, object] = {}

    if class_code == "bearing.ball.deep_groove":
        out["bore_mm"] = _num(text, "bore_mm")
        out["outer_dia_mm"] = _num(text, "od_mm")
        out["width_mm"] = _num(text, "width_mm")
        out["seal_type"] = _enum(text, "seal_type")
        out["load_rating_kg"] = _num(text, "load_kg")
        out["temp_max_c"] = _num(text, "temp_max")

    elif class_code == "valve.gate":
        out["size_nb_mm"] = _num(text, "size_nb")
        pc = _first_group(_P["pressure_class"].search(text))
        out["pressure_class"] = pc
        out["body_material"] = _enum(text, "body_material")
        out["end_connection"] = _enum(text, "end_connection")
        out["pressure_bar"] = _num(text, "pressure_bar")
        out["temp_max_c"] = _num(text, "temp_max")

    elif class_code == "gasket.spiral_wound":
        out["size_nb_mm"] = _num(text, "size_nb")
        out["pressure_class"] = _first_group(_P["pressure_class"].search(text))
        out["material"] = _enum(text, "material")
        out["thickness_mm"] = _num(text, "thickness")
        out["temp_max_c"] = _num(text, "temp_max")

    elif class_code == "pipe.seamless":
        out["nps_mm"] = _num(text, "size_nb")
        sch = _first_group(_P["schedule"].search(text))
        out["schedule"] = (sch if sch in ("XS", "XXS") else f"SCH{sch}") if sch else None
        out["material"] = _enum(text, "material")
        out["pressure_bar"] = _num(text, "pressure_bar")
        out["length_m"] = _num(text, "length_m")

    elif class_code == "fastener.bolt.hex":
        thread = parse_metric_thread(text)
        out["thread"] = thread.attrs.get("thread") if thread else None
        out["length_mm"] = _num(text, "length_mm")
        out["grade"] = _first_group(_P["grade"].search(text))
        out["material"] = _enum(text, "material")
        out["finish"] = _enum(text, "finish")

    elif class_code == "cable.power":
        if m := _P["cores_csa"].search(text):
            out["cores"] = float(m.group(1))
            out["csa_mm2"] = float(m.group(2))
        else:
            out["csa_mm2"] = _num(text, "csa")
        if vm := _P["voltage"].search(text):
            value = float(vm.group(1))
            unit = vm.group(2)
            out["voltage_v"] = value * 1000 if unit in ("KV", "KILOVOLT") else value
        out["conductor"] = _enum(text, "conductor")
        out["insulation"] = _enum(text, "insulation")
        out["temp_max_c"] = _num(text, "temp_max")

    elif class_code == "chemical.reagent":
        out["substance"] = _enum(text, "substance")
        out["grade"] = _first_group(_P["grade"].search(text)) or _enum(text, "grade")
        out["concentration_pct"] = _num(text, "concentration")

    elif class_code == "ppe.helmet":
        out["helmet_class"] = _enum(text, "helmet_class")
        out["standard"] = _enum(text, "standard")
        out["shell_material"] = _enum(text, "shell_material")
        out["harness_type"] = _enum(text, "harness_type")
        out["chin_strap"] = _enum(text, "chin_strap")
        out["ventilation"] = _enum(text, "ventilation")
        out["brim"] = _enum(text, "brim")

    out["brand"] = extract_brand(text, class_code)

    # Drop anything the schema does not declare, and anything we failed to find.
    return {k: v for k, v in out.items() if v is not None and k in schema.attributes}


def extract(norm_text: str) -> Extraction:
    """Classify then extract. Never raises — an unparseable row is unclassified."""
    text = (norm_text or "").upper()
    guess = classify(text)

    designation = parse_bearing_designation(text)
    attrs = _extract_for_class(text, guess.class_code)
    conflicts: list[dict[str, object]] = []

    if designation:
        # §2A.1: a designation and the free text can disagree. Record it as a
        # conflict for review instead of silently trusting either source.
        for key, value in designation.attrs.items():
            if key not in get_schema(guess.class_code).attributes:
                continue
            existing = attrs.get(key)
            if existing is None:
                attrs[key] = value
            elif isinstance(value, (int, float)) and isinstance(existing, (int, float)):
                if abs(float(existing) - float(value)) > 1e-6:
                    conflicts.append(
                        {
                            "attr": key,
                            "from_designation": value,
                            "from_text": existing,
                            "designation": designation.raw,
                        }
                    )
            elif existing != value:
                conflicts.append(
                    {
                        "attr": key,
                        "from_designation": value,
                        "from_text": existing,
                        "designation": designation.raw,
                    }
                )

    return Extraction(
        class_code=guess.class_code,
        class_confidence=round(guess.confidence, 4),
        attrs=attrs,
        mpn=extract_mpn(text, designation, attrs, guess.class_code),
        designation=designation.raw if designation else None,
        conflicts=conflicts,
    )
