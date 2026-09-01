"""Synthetic catalogue generator with ground truth — spec §7.

The corruption model follows the FEBRL / GeCo pattern referenced in §9: build
clean ground-truth products first, then render each one through per-CPSE style
profiles that abbreviate, reorder, mis-spell and occasionally switch language.
The truth tables are written from the generator's own knowledge, so metrics are
measured against what was actually generated rather than against a guess.

Three truth tables come out of this:
  truth_group        which real product each raw row is (duplicate ground truth)
  truth_trap         planted near-misses the veto layer must refuse (§2A)
  truth_equivalence  directed substitution ground truth (§2B)

Everything is driven by a seeded RNG, so `make seed` is reproducible — which is
what makes the §2D determinism test meaningful.

A note on the two item counts in §7: 2,200 ground-truth products rendered into
1-4 variants each cannot by itself reach 3,000 rows per CPSE. Both numbers are
honoured by treating the 2,200 as the cross-CPSE *shared* products (the ones
with duplicates to find) and filling the remainder with singleton products
unique to one CPSE — which is also how a real material master looks.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from .auth import hash_password
from .data.bearings import DEEP_GROOVE_DIMS
from .db import reset_db
from .models import (
    Cpse,
    Crossref,
    Item,
    PurchaseHistory,
    RawItem,
    Stock,
    SubstitutionRule,
    TruthEquivalence,
    TruthGroup,
    TruthTrap,
    User,
)
from .pipeline import build_items

SEED = 20260101

# --------------------------------------------------------------------------
# CPSE style profiles — the corruption model (§7)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StyleProfile:
    code: str
    name: str
    plants: tuple[str, ...]
    #: expansion -> this CPSE's preferred abbreviation
    contract: dict[str, str]
    sep: str
    order: str  # noun_first | attrs_first | brand_first
    uom_words: dict[str, str]
    hindi_rate: float
    typo_rate: float


_TERSE = {
    "BEARING": "BRG", "VALVE": "VLV", "GASKET": "GSKT", "PIPE": "PIPE",
    "BOLT": "BLT", "CABLE": "CBL", "HELMET": "HLMT", "CHEMICAL": "CHEM",
    "STAINLESS STEEL": "SS", "CARBON STEEL": "CS", "THICKNESS": "THK",
    "NOMINAL BORE": "NB", "OUTER DIAMETER": "OD", "LENGTH": "LG",
    "FLANGED": "FLGD", "THREADED": "THRD", "SCHEDULE": "SCH", "GRADE": "GR",
    "CLASS": "CL", "SEAMLESS": "SMLS", "SPIRAL WOUND": "SW",
}
_MEDIUM = {
    "BEARING": "BEARING", "VALVE": "VALVE", "GASKET": "GASKET",
    "STAINLESS STEEL": "S.S.", "CARBON STEEL": "C.S.", "THICKNESS": "THK",
    "NOMINAL BORE": "NB", "OUTER DIAMETER": "O.D.", "LENGTH": "LG",
    "FLANGED": "FLANGED", "SCHEDULE": "SCH", "CLASS": "CLASS", "GRADE": "GRADE",
}
_VERBOSE: dict[str, str] = {}  # spells everything out

CPSE_PROFILES: tuple[StyleProfile, ...] = (
    StyleProfile(
        code="CPCL", name="Chennai Petroleum Corporation Limited",
        plants=("MANALI", "CAUVERY"), contract=_TERSE, sep=",", order="noun_first",
        uom_words={"EA": "NOS", "M": "MTR", "KG": "KG", "L": "LTR"},
        hindi_rate=0.10, typo_rate=0.08,
    ),
    StyleProfile(
        code="IOCL", name="Indian Oil Corporation Limited",
        plants=("PANIPAT", "MATHURA", "HALDIA"), contract=_VERBOSE, sep=" ",
        order="noun_first",
        uom_words={"EA": "EA", "M": "METRE", "KG": "KG", "L": "LITRE"},
        hindi_rate=0.10, typo_rate=0.08,
    ),
    StyleProfile(
        code="GAIL", name="GAIL (India) Limited",
        plants=("VIJAIPUR", "PATA"), contract=_MEDIUM, sep=" - ", order="brand_first",
        uom_words={"EA": "PC", "M": "M", "KG": "KGS", "L": "LTR"},
        hindi_rate=0.10, typo_rate=0.08,
    ),
    StyleProfile(
        code="ONGC", name="Oil and Natural Gas Corporation",
        plants=("URAN", "HAZIRA", "ANKLESHWAR"), contract=_TERSE, sep=" ",
        order="attrs_first",
        uom_words={"EA": "NOS", "M": "MTRS", "KG": "KG", "L": "LTR"},
        hindi_rate=0.10, typo_rate=0.08,
    ),
    StyleProfile(
        code="HPCL", name="Hindustan Petroleum Corporation Limited",
        plants=("VISAKH", "MUMBAI"), contract=_MEDIUM, sep=",", order="noun_first",
        uom_words={"EA": "PCS", "M": "MTR", "KG": "KG", "L": "LTR"},
        hindi_rate=0.10, typo_rate=0.08,
    ),
    StyleProfile(
        code="SAIL", name="Steel Authority of India Limited",
        plants=("BHILAI", "ROURKELA", "BOKARO"), contract=_TERSE, sep=" ",
        order="attrs_first",
        uom_words={"EA": "NO", "M": "MTR", "KG": "KGS", "L": "LTR"},
        hindi_rate=0.10, typo_rate=0.08,
    ),
)

#: Hindi swaps used for the 10% language mix (§7).
HINDI_NOUNS = {
    "BEARING": "बेयरिंग", "VALVE": "वाल्व", "GASKET": "गैसकेट", "PIPE": "पाइप",
    "BOLT": "बोल्ट", "CABLE": "केबल", "HELMET": "हेलमेट",
}

SEED_USERS = (
    ("registrar@min.gov.in", "R. Krishnan", "registrar", None),
    ("admin@saman.gov.in", "System Administrator", "admin", None),
    ("approver@min.gov.in", "S. Iyer", "approver", None),
    ("steward@cpcl.in", "A. Ramesh", "steward", "CPCL"),
    ("steward@iocl.in", "P. Nair", "steward", "IOCL"),
    ("auditor@cag.gov.in", "M. Banerjee", "auditor", None),
    ("viewer@min.gov.in", "Public Viewer", "viewer", None),
)

VENDORS = {
    "bearing.ball.deep_groove": ("BEARING HOUSE", "NATIONAL ENGG", "SOUTH INDIA BEARINGS"),
    "valve.gate": ("VALVE TECH", "PRECISION FLOW", "INDUSTRIAL VALVES CO"),
    "gasket.spiral_wound": ("SEALTECH", "GASKET INDIA", "PACKING SOLUTIONS"),
    "pipe.seamless": ("STEEL TUBES LTD", "PIPE TRADERS", "METAL SUPPLY CO"),
    "fastener.bolt.hex": ("FASTENER MART", "BOLT INDIA", "PRECISION FASTENERS"),
    "cable.power": ("CABLE CORP", "WIRE HOUSE", "POWER LINK"),
    "chemical.reagent": ("CHEM SUPPLY", "LAB SOURCE", "PROCESS CHEMICALS"),
    "ppe.helmet": ("SAFETY FIRST", "PROTECT INDIA", "INDUSTRIAL SAFETY CO"),
}


# --------------------------------------------------------------------------
# Ground-truth products
# --------------------------------------------------------------------------


@dataclass
class Product:
    group_id: str
    class_code: str
    attrs: dict[str, object]
    brand: str
    mpn: str | None
    base_price: float
    #: Not every catalogue item carries a barcode; roughly a third here do.
    gtin: str | None = None
    #: how many CPSEs carry it; 1 = singleton
    spread: int = 1
    tags: list[str] = field(default_factory=list)


_BEARING_BRAND_SUFFIX = {
    "SKF": "-2Z", "FAG": "-2ZR", "NSK": "ZZ", "NTN": "ZZ", "TIMKEN": "-2Z", "KOYO": "ZZ",
}
_SEAL_FOR_SUFFIX = {"-2Z": "ZZ", "-2ZR": "ZZ", "ZZ": "ZZ", "-2RS": "2RS", "2RS": "2RS"}

VALVE_SIZES = (15, 25, 40, 50, 80, 100, 150, 200)
VALVE_CLASS_BAR = {"150": 19.6, "300": 51.1, "600": 102.1, "900": 153.2}
PIPE_SIZES = (15, 25, 50, 80, 100, 150, 200, 250, 300)
CABLE_CSA = (1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95)
SUBSTANCES = (
    "SODIUM HYDROXIDE", "HYDROCHLORIC ACID", "SULPHURIC ACID", "NITRIC ACID",
    "CALCIUM CHLORIDE", "METHANOL", "ISOPROPYL ALCOHOL",
)


#: Per-class attribute spaces. Every key here is an identity_critical or
#: performance attribute that the description actually renders, so two distinct
#: products always differ on something a comparator can see. Cosmetic
#: attributes (brand, colour, finish) are deliberately absent: two items that
#: differ only cosmetically ARE duplicates, and using them to separate products
#: would build a ground truth that contradicts the veto layer.
#:
#: Value ladders are spaced wider than the tolerance band declared in
#: classes.yaml, so no two distinct products ever sit inside each other's band.
CLASS_SPACES: dict[str, dict[str, tuple]] = {
    "bearing.ball.deep_groove": {
        "designation": tuple(sorted(DEEP_GROOVE_DIMS)),
        "seal_type": ("ZZ", "2RS", "OPEN"),
        "temp_max_c": (100, 120, 150),
        "load_class": ("STD", "HIGH", "XHIGH"),  # 1.0x / 1.6x / 2.4x base rating
    },
    "valve.gate": {
        "size_nb_mm": (15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300),
        "pressure_class": ("150", "300", "600", "900"),
        "body_material": ("WCB", "CS", "SS316", "SS304", "CI"),
        "end_connection": ("FLANGED", "THREADED", "BUTTWELD", "SOCKETWELD"),
        "temp_max_c": (150, 200, 250, 400),
    },
    "gasket.spiral_wound": {
        "size_nb_mm": (15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300),
        "pressure_class": ("150", "300", "600", "900"),
        "material": ("SS316-GRAPHITE", "SS304-PTFE", "SS316-PTFE", "CAF"),
        "thickness_mm": (3.0, 4.5, 6.0, 7.5),
        "temp_max_c": (450, 550, 650),
    },
    "pipe.seamless": {
        "nps_mm": (15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300),
        "schedule": ("SCH20", "SCH40", "SCH80", "SCH160", "XS"),
        "material": ("CS-A106B", "SS316", "SS304", "CS-A53"),
        "pressure_bar": (20.0, 40.0, 60.0, 100.0, 160.0),
    },
    "fastener.bolt.hex": {
        "nominal_mm": (6, 8, 10, 12, 16, 20, 24, 30),
        "length_mm": (20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 180, 200),
        "grade": ("4.6", "8.8", "10.9", "12.9"),
        "material": ("CS", "SS316", "SS304"),
    },
    "cable.power": {
        "cores": (1, 2, 3, 4, 5),
        "csa_mm2": (1.5, 2.5, 4.0, 6.0, 10.0, 16.0, 25.0, 35.0, 50.0, 70.0, 95.0, 120.0, 150.0),
        "conductor": ("CU", "AL"),
        "insulation": ("PVC", "XLPE"),
        "voltage_v": (650.0, 1100.0, 3300.0, 11000.0),
        "temp_max_c": (70, 90),
    },
    "chemical.reagent": {
        "substance": (
            "SODIUM HYDROXIDE", "HYDROCHLORIC ACID", "SULPHURIC ACID", "NITRIC ACID",
            "PHOSPHORIC ACID", "ACETIC ACID", "CALCIUM CHLORIDE", "SODIUM CHLORIDE",
            "SODIUM CARBONATE", "POTASSIUM HYDROXIDE", "METHANOL", "ETHANOL",
            "ISOPROPYL ALCOHOL", "ACETONE", "TOLUENE", "XYLENE", "HEXANE",
            "AMMONIUM CHLORIDE", "SODIUM SULPHATE", "POTASSIUM PERMANGANATE",
            "HYDROGEN PEROXIDE", "CITRIC ACID", "OXALIC ACID", "BORIC ACID",
        ),
        "grade": ("LR", "AR", "GR", "TECH"),
        "concentration_pct": (10.0, 20.0, 30.0, 40.0, 50.0, 70.0, 85.0, 99.0),
    },
    "ppe.helmet": {
        "helmet_class": ("A", "B", "C", "E"),
        "standard": ("IS2925", "EN397"),
        "shell_material": ("HDPE", "ABS", "FRP"),
        "harness_type": ("RATCHET", "PINLOCK"),
        "chin_strap": ("2-POINT", "4-POINT"),
        "ventilation": ("VENTED", "NON-VENTED"),
        "brim": ("FULL BRIM", "PEAK"),
    },
}

BRANDS_FOR = {
    "bearing.ball.deep_groove": ("SKF", "FAG", "NSK", "NTN", "TIMKEN", "KOYO"),
    "valve.gate": ("KITZ", "AUDCO", "BDK", "KSB", "FLOWSERVE", "LT"),
    "gasket.spiral_wound": ("LEADER", "CHAMPION", "GARLOCK", "FLEXITALLIC"),
    "pipe.seamless": ("JINDAL", "TATA", "MSL", "ISMT"),
    "fastener.bolt.hex": ("UNBRAKO", "TVS", "SUNDRAM", "APL"),
    "cable.power": ("POLYCAB", "HAVELLS", "FINOLEX", "KEI"),
    "chemical.reagent": ("MERCK", "RANKEM", "FISHER", "THERMO"),
    "ppe.helmet": ("KARAM", "VENUS", "3M", "HONEYWELL"),
}

#: Cosmetic-only variation. Free to differ between duplicates.
FINISHES = ("ZINC", "PLAIN", "HDG")
COLOURS = ("WHITE", "YELLOW", "BLUE", "RED", "GREEN", "ORANGE")

_THREAD_PITCH = {6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 16: 2.0, 20: 2.5, 24: 3.0, 30: 3.5}
_LOAD_MULTIPLIER = {"STD": 1.0, "HIGH": 1.6, "XHIGH": 2.4}


def class_capacity(class_code: str) -> int:
    """How many distinct products this class can express."""
    space = CLASS_SPACES[class_code]
    total = 1
    for values in space.values():
        total *= len(values)
    return total


def _decode(class_code: str, index: int) -> dict[str, object]:
    """Mixed-radix decode of a combination index into concrete attribute values.

    Enumerating by index means uniqueness is guaranteed by construction rather
    than by rejection sampling, which saturates long before the space is full.
    """
    combo: dict[str, object] = {}
    for key, values in CLASS_SPACES[class_code].items():
        index, position = divmod(index, len(values))
        combo[key] = values[position]
    return combo


#: Catalogue-number family prefix per class.
_MPN_FAMILY = {
    "valve.gate": "GV", "gasket.spiral_wound": "SW", "pipe.seamless": "SP",
    "fastener.bolt.hex": "HB", "cable.power": "PW", "chemical.reagent": "CH",
    "ppe.helmet": "HL",
}


def bearing_mpn(designation: str, seal: str, brand: str, load_class: str, temp: int) -> str:
    """A bearing part number that identifies exactly one product.

    Manufacturers do this with variant suffixes (6205-2Z/C3), so two bearings
    sharing a designation but rated differently carry different numbers. An MPN
    that mapped to several products would be a false anchor key: same number,
    conflicting specifications, which the matcher would rightly raise as a
    data-quality conflict.
    """
    suffix = (
        "-2RS" if seal == "2RS"
        else "" if seal == "OPEN"
        else _BEARING_BRAND_SUFFIX.get(brand, "-2Z")
    )
    variant = "" if (load_class == "STD" and temp == 120) else f"/{load_class[0]}{temp}"
    return f"{designation}{suffix}{variant}"


def make_gtin(rng: random.Random) -> str:
    """A GTIN-13 with a correct GS1 check digit (890 = the Indian prefix)."""
    from .normalize import gtin_check_digit

    body = "890" + "".join(str(rng.randrange(10)) for _ in range(9))
    return body + str(gtin_check_digit(body))


def _finalize(
    class_code: str, combo: dict, rng: random.Random, gid: str, index: int = 0
) -> Product:
    """Turn a decoded combination into a Product, deriving dependent attributes."""
    brand = rng.choice(BRANDS_FOR[class_code])
    # Opaque catalogue number keyed to the exact combination, so no two
    # distinct products can ever share an anchor key.
    catalogue = f"{brand[:3]}-{_MPN_FAMILY.get(class_code, 'XX')}{index:05d}"
    gtin = make_gtin(rng) if rng.random() < 0.35 else None

    if class_code == "bearing.ball.deep_groove":
        designation = str(combo["designation"])
        bore, od, width = DEEP_GROOVE_DIMS[designation]
        base_rating = round(bore * 20 / 50) * 50
        attrs = {
            "designation": designation,
            "bore_mm": bore, "outer_dia_mm": od, "width_mm": width,
            "seal_type": combo["seal_type"],
            "load_rating_kg": float(base_rating * _LOAD_MULTIPLIER[str(combo["load_class"])]),
            "temp_max_c": combo["temp_max_c"],
        }
        return Product(
            gid, class_code, attrs, brand,
            bearing_mpn(designation, str(combo["seal_type"]), brand,
                        str(combo["load_class"]), int(combo["temp_max_c"])),
            round(bore * rng.uniform(18, 45), 2), gtin=gtin,
        )

    if class_code == "valve.gate":
        size = int(combo["size_nb_mm"])
        pclass = str(combo["pressure_class"])
        attrs = {
            "size_nb_mm": float(size), "pressure_class": pclass,
            "body_material": combo["body_material"],
            "end_connection": combo["end_connection"],
            "pressure_bar": VALVE_CLASS_BAR[pclass],
            "temp_max_c": combo["temp_max_c"],
        }
        return Product(gid, class_code, attrs, brand, catalogue,
                       round(size * float(pclass) * rng.uniform(0.9, 1.6), 2), gtin=gtin)

    if class_code == "gasket.spiral_wound":
        size = int(combo["size_nb_mm"])
        attrs = {
            "size_nb_mm": float(size), "pressure_class": combo["pressure_class"],
            "material": combo["material"], "thickness_mm": combo["thickness_mm"],
            "temp_max_c": combo["temp_max_c"],
        }
        return Product(gid, class_code, attrs, brand,
                       catalogue,
                       round(size * rng.uniform(3, 9), 2), gtin=gtin)

    if class_code == "pipe.seamless":
        size = int(combo["nps_mm"])
        attrs = {
            "nps_mm": float(size), "schedule": combo["schedule"],
            "material": combo["material"], "pressure_bar": combo["pressure_bar"],
            "length_m": 6.0,
        }
        return Product(gid, class_code, attrs, brand, catalogue,
                       round(size * rng.uniform(9, 22), 2), gtin=gtin)

    if class_code == "fastener.bolt.hex":
        nominal = int(combo["nominal_mm"])
        length = int(combo["length_mm"])
        attrs = {
            "thread": f"M{nominal}X{_THREAD_PITCH[nominal]}",
            "length_mm": float(length), "grade": combo["grade"],
            "material": combo["material"], "finish": rng.choice(FINISHES),
        }
        return Product(gid, class_code, attrs, brand, catalogue,
                       round(nominal * length * rng.uniform(0.02, 0.08), 2), gtin=gtin)

    if class_code == "cable.power":
        cores = int(combo["cores"])
        csa = float(combo["csa_mm2"])
        attrs = {
            "cores": float(cores), "csa_mm2": csa,
            "voltage_v": combo["voltage_v"], "conductor": combo["conductor"],
            "insulation": combo["insulation"], "temp_max_c": combo["temp_max_c"],
        }
        return Product(gid, class_code, attrs, brand, catalogue,
                       round(cores * csa * rng.uniform(9, 20), 2), gtin=gtin)

    if class_code == "chemical.reagent":
        attrs = {
            "substance": combo["substance"], "grade": combo["grade"],
            "concentration_pct": combo["concentration_pct"],
        }
        return Product(gid, class_code, attrs, brand, catalogue,
                       round(rng.uniform(400, 4500), 2), gtin=gtin)

    if class_code == "ppe.helmet":
        attrs = {
            "helmet_class": combo["helmet_class"], "standard": combo["standard"],
            "shell_material": combo["shell_material"],
            "harness_type": combo["harness_type"],
            "chin_strap": combo["chin_strap"], "ventilation": combo["ventilation"],
            "brim": combo["brim"], "colour": rng.choice(COLOURS),
        }
        return Product(gid, class_code, attrs, brand,
                       catalogue,
                       round(rng.uniform(180, 900), 2), gtin=gtin)

    raise ValueError(f"no finalizer for class {class_code!r}")


# --------------------------------------------------------------------------
# Rendering: one product -> one CPSE's catalogue description
# --------------------------------------------------------------------------


def _phrases(product: Product, rng: random.Random) -> tuple[str, list[str]]:
    """Class-specific (noun, attribute phrases) before styling."""
    a = product.attrs
    cls = product.class_code

    if cls == "bearing.ball.deep_groove":
        # Two genuinely different catalogue conventions for the same bearing:
        # the ISO designation, or the dimensions spelled out. Both must match.
        # Performance ratings are carried in the text on purpose: the §2A
        # traps (200 kg vs 500 kg on the same designation) are only decidable
        # if the rating is recoverable from the description.
        rating = [f"{int(a['load_rating_kg'])} KG", f"{int(a['temp_max_c'])} C"]
        if rng.random() < 0.55:
            return "BEARING", ["BALL", str(a["designation"]), str(a["seal_type"]), *rating]
        return "BEARING", [
            "BALL",
            f"{int(a['bore_mm'])}MM BORE",
            f"{int(a['outer_dia_mm'])}MM OD",
            f"{int(a['width_mm'])}MM W",
            str(a["seal_type"]),
            *rating,
        ]

    if cls == "valve.gate":
        return "VALVE", [
            "GATE",
            f"{int(a['size_nb_mm'])}NB",
            f"CLASS {a['pressure_class']}",
            str(a["body_material"]),
            str(a["end_connection"]),
            f"{a['pressure_bar']} BAR",
            f"{int(a['temp_max_c'])} C",
        ]

    if cls == "gasket.spiral_wound":
        return "GASKET", [
            "SPIRAL WOUND",
            f"{int(a['size_nb_mm'])}NB",
            f"CLASS {a['pressure_class']}",
            str(a["material"]),
            f"{a['thickness_mm']}MM THK",
            f"{int(a['temp_max_c'])} C",
        ]

    if cls == "pipe.seamless":
        return "PIPE", [
            "SEAMLESS",
            f"{int(a['nps_mm'])}NB",
            str(a["schedule"]),
            str(a["material"]),
            f"{a['pressure_bar']} BAR",
        ]

    if cls == "fastener.bolt.hex":
        return "BOLT", [
            "HEX",
            str(a["thread"]),
            f"{int(a['length_mm'])}MM LG",
            f"GRADE {a['grade']}",
            str(a["material"]),
            str(a["finish"]),
        ]

    if cls == "cable.power":
        conductor = "COPPER" if a["conductor"] == "CU" else "ALUMINIUM"
        return "CABLE", [
            "POWER",
            f"{int(a['cores'])}C X {a['csa_mm2']} SQMM",
            conductor,
            str(a["insulation"]),
            f"{int(a['voltage_v'])}V",
            f"{int(a['temp_max_c'])} C",
        ]

    if cls == "chemical.reagent":
        return "CHEMICAL", [
            str(a["substance"]),
            f"{a['grade']} GRADE",
            f"{int(a['concentration_pct'])} PCT",
        ]

    if cls == "ppe.helmet":
        return "HELMET", [
            "SAFETY",
            f"CLASS {a['helmet_class']}",
            str(a["shell_material"]),
            str(a["harness_type"]),
            str(a["chin_strap"]),
            str(a["ventilation"]),
            str(a["brim"]),
            str(a["standard"]),
            str(a["colour"]),
        ]

    return "ITEM", []


def _contract(text: str, table: dict[str, str]) -> str:
    """Apply a CPSE's abbreviation style, longest phrase first."""
    for expansion in sorted(table, key=len, reverse=True):
        text = text.replace(expansion, table[expansion])
    return text


def _typo(word: str, rng: random.Random) -> str:
    """One character-level corruption: transpose, drop or double."""
    if len(word) < 4:
        return word
    i = rng.randrange(len(word) - 1)
    kind = rng.random()
    if kind < 0.4:
        return word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    if kind < 0.7:
        return word[:i] + word[i + 1 :]
    return word[:i] + word[i] + word[i:]


def _malform_mpn(mpn: str, rng: random.Random) -> str:
    """Realistic MPN damage: lost separator, stray space, transposition."""
    choice = rng.random()
    if choice < 0.4:
        return mpn.replace("-", "")
    if choice < 0.7:
        return mpn.replace("-", " ", 1)
    return _typo(mpn, rng)


_RATING_TOKEN = re.compile(r"(\d+(?:\.\d+)?)(\s*)(BAR|KG)\b")


def _perturb_rating(description: str, factor: float) -> str:
    """Restate the first performance rating at a slightly different rounding."""

    def bump(m: re.Match) -> str:
        value = round(float(m.group(1)) * factor, 1)
        return f"{value}{m.group(2)}{m.group(3)}"

    return _RATING_TOKEN.sub(bump, description, count=1)


def render(product: Product, style: StyleProfile, rng: random.Random) -> str:
    """Render one product the way `style`'s CPSE would have catalogued it."""
    noun, phrases = _phrases(product, rng)

    # ~60% of items carry an MPN in their description (spec §7).
    mpn_text: str | None = None
    if product.mpn and rng.random() < 0.60:
        mpn_text = _malform_mpn(product.mpn, rng) if rng.random() < 0.08 else product.mpn

    if style.order == "attrs_first":
        parts = [*phrases, noun, product.brand]
    elif style.order == "brand_first":
        parts = [product.brand, noun, *phrases]
    else:
        parts = [noun, *phrases, product.brand]
    if mpn_text:
        parts.append(mpn_text)
    # A barcode is printed on some catalogue rows but not all, and the label
    # varies between CPSEs — which is what makes it a realistic Tier-0 anchor.
    if product.gtin and rng.random() < 0.55:
        parts.append(
            f"{rng.choice(('EAN', 'GTIN', 'BARCODE'))} {product.gtin}"
            if rng.random() < 0.7
            else product.gtin
        )

    text = style.sep.join(p for p in parts if p)
    text = _contract(text, style.contract)

    # 10% language mix: swap the noun for its Hindi term (§7).
    if rng.random() < style.hindi_rate:
        contracted_noun = style.contract.get(noun, noun)
        hindi = HINDI_NOUNS.get(noun)
        if hindi and contracted_noun in text:
            text = text.replace(contracted_noun, hindi, 1)

    # 8% typo rate, never inside the MPN (that damage is modelled separately).
    if rng.random() < style.typo_rate:
        words = text.split(" ")
        candidates = [i for i, w in enumerate(words) if len(w) >= 4 and w != mpn_text]
        if candidates:
            i = rng.choice(candidates)
            words[i] = _typo(words[i], rng)
            text = " ".join(words)

    return text.strip()


# --------------------------------------------------------------------------
# Planted traps and equivalence truth (§7)
# --------------------------------------------------------------------------


@dataclass
class TrapSpec:
    product_a: Product
    product_b: Product
    kind: str
    attr: str
    value_a: str
    value_b: str
    expect_duplicate: bool
    equivalence: tuple[str, str] | None = None  # (direction, basis)


def _encode(class_code: str, combo: dict) -> int:
    """Inverse of _decode: attribute values -> combination index."""
    index = 0
    for key, values in reversed(list(CLASS_SPACES[class_code].items())):
        index = index * len(values) + values.index(combo[key])
    return index


def _vary(class_code: str, index: int, key: str, rng: random.Random) -> int | None:
    """Index of the same combination with exactly one attribute changed."""
    combo = _decode(class_code, index)
    options = [v for v in CLASS_SPACES[class_code][key] if v != combo[key]]
    if not options:
        return None
    combo[key] = rng.choice(options)
    return _encode(class_code, combo)


def _vary_to(class_code: str, index: int, key: str, value) -> int:
    combo = _decode(class_code, index)
    combo[key] = value
    return _encode(class_code, combo)


def _plant_traps(
    rng: random.Random,
    used: dict[str, set[int]],
    gid_start: int = 0,
) -> tuple[list[Product], list[TrapSpec]]:
    """Build the near-miss pairs the veto layer is graded on (§2A acceptance).

    Every trap product is drawn from the same enumeration space as the normal
    population, reserving indices as it goes. That is what keeps traps from
    colliding with each other or with ordinary products — an earlier version
    constructed them ad hoc and produced textually identical items in different
    truth groups, which no matcher could ever get right.
    """
    products: list[Product] = []
    traps: list[TrapSpec] = []
    counter = gid_start

    def gid() -> str:
        nonlocal counter
        counter += 1
        return f"TRAP{counter:05d}"

    # Draw from the actual free set rather than probing at random: the large
    # profile consumes ~96% of the space, where random probing finds nothing
    # and traps silently vanish.
    free: dict[str, list[int]] = {}
    for class_code in CLASS_SPACES:
        remaining = [i for i in range(class_capacity(class_code)) if i not in used[class_code]]
        rng.shuffle(remaining)
        free[class_code] = remaining

    def take(class_code: str) -> int | None:
        """Reserve an unused combination index for this class."""
        while free[class_code]:
            index = free[class_code].pop()
            if index not in used[class_code]:
                used[class_code].add(index)
                return index
        return None

    def pair(class_code: str, key: str, value_b=None) -> tuple[Product, Product, str, str] | None:
        """Two products differing on exactly one attribute."""
        index_a = index_b = None
        for _ in range(60):
            candidate = take(class_code)
            if candidate is None:
                return None
            varied = (
                _vary_to(class_code, candidate, key, value_b)
                if value_b is not None
                else _vary(class_code, candidate, key, rng)
            )
            if varied is not None and varied not in used[class_code]:
                index_a, index_b = candidate, varied
                break
        if index_a is None or index_b is None:
            return None
        used[class_code].add(index_b)

        combo_a, combo_b = _decode(class_code, index_a), _decode(class_code, index_b)
        a = _finalize(class_code, combo_a, rng, gid(), index_a)
        b = _finalize(class_code, combo_b, rng, gid(), index_b)
        # A trap only works if both sides reach at least two catalogues.
        a.spread = b.spread = 2
        a.tags.append("trap")
        b.tags.append("trap")
        # Same brand on both sides, so brand cannot be the giveaway.
        b.brand = a.brand
        b.mpn = None
        a.mpn = None
        return a, b, str(combo_a[key]), str(combo_b[key])

    # 1. Identity-critical near miss: one size or thickness apart, everything
    #    else word-for-word identical. Similarity says duplicate; the veto layer
    #    must refuse. This is the headline demo moment in §2A.
    for class_code, key in (
        *[("valve.gate", "size_nb_mm")] * 40,
        *[("gasket.spiral_wound", "thickness_mm")] * 25,
        *[("cable.power", "csa_mm2")] * 20,
    ):
        made = pair(class_code, key)
        if not made:
            continue
        a, b, va, vb = made
        products += [a, b]
        traps.append(TrapSpec(a, b, "identity_critical", key, va, vb, expect_duplicate=False))

    # 2. Same designation, load rating far outside the 5% band (spec's 200 vs
    #    500 case). Not a duplicate, but a directed substitute: the higher-rated
    #    bearing can replace the lower-rated one, never the reverse.
    for _ in range(40):
        cls = "bearing.ball.deep_groove"
        index_a = index_b = None
        for _ in range(60):
            candidate = take(cls)
            if candidate is None:
                break
            lo = _vary_to(cls, candidate, "load_class", "STD")
            hi = _vary_to(cls, candidate, "load_class", "XHIGH")
            if (lo not in used[cls] or lo == candidate) and hi not in used[cls]:
                index_a, index_b = lo, hi
                break
        if index_a is None or index_b is None:
            continue
        used["bearing.ball.deep_groove"].update({index_a, index_b})
        a = _finalize("bearing.ball.deep_groove",
                      _decode("bearing.ball.deep_groove", index_a), rng, gid(), index_a)
        b = _finalize("bearing.ball.deep_groove",
                      _decode("bearing.ball.deep_groove", index_b), rng, gid(), index_b)
        a.spread = b.spread = 2
        b.brand = a.brand
        a.tags.append("trap")
        b.tags.append("trap")
        products += [a, b]
        traps.append(
            TrapSpec(a, b, "performance_out_of_band", "load_rating_kg",
                     str(a.attrs["load_rating_kg"]), str(b.attrs["load_rating_kg"]),
                     expect_duplicate=False, equivalence=("a_to_b", "rule"))
        )

    # 3. Cross-brand equivalents: the same ISO designation from three
    #    manufacturers. Distinct material records that are interchangeable —
    #    they must NOT be merged into one CNMC (§2B).
    for _ in range(30):
        index = take("bearing.ball.deep_groove")
        if index is None:
            break
        combo = _decode("bearing.ball.deep_groove", index)
        if combo["seal_type"] == "OPEN":
            combo["seal_type"] = "ZZ"
        trio = []
        for brand in ("SKF", "FAG", "NSK"):
            product = _finalize("bearing.ball.deep_groove", dict(combo), rng, gid(), index)
            product.brand = brand
            # Same physical bearing, three manufacturers' numbers: the
            # interchangeability case (§2B), not a duplicate.
            product.mpn = bearing_mpn(
                str(combo["designation"]), str(combo["seal_type"]), brand,
                str(combo["load_class"]), int(combo["temp_max_c"]),
            )
            product.spread = 2
            product.tags.append("crossbrand")
            trio.append(product)
        products += trio
        for i in range(len(trio)):
            for j in range(i + 1, len(trio)):
                traps.append(
                    TrapSpec(trio[i], trio[j], "cross_brand_equivalent", "brand",
                             trio[i].brand, trio[j].brand, expect_duplicate=False,
                             equivalence=("bidirectional", "designation"))
                )

    # 4. Directed substitute: a higher pressure class replaces a lower one, but
    #    never the reverse. Direction is the whole point (§2B).
    for _ in range(30):
        cls = "valve.gate"
        index_a = index_b = None
        for _ in range(60):
            candidate = take(cls)
            if candidate is None:
                break
            lo = _vary_to(cls, candidate, "pressure_class", "300")
            hi = _vary_to(cls, candidate, "pressure_class", "600")
            if (lo not in used[cls] or lo == candidate) and hi not in used[cls]:
                index_a, index_b = lo, hi
                break
        if index_a is None or index_b is None:
            continue
        used["valve.gate"].update({index_a, index_b})
        a = _finalize("valve.gate", _decode("valve.gate", index_a), rng, gid(), index_a)
        b = _finalize("valve.gate", _decode("valve.gate", index_b), rng, gid(), index_b)
        a.spread = b.spread = 2
        b.brand = a.brand
        a.tags.append("trap")
        b.tags.append("trap")
        products += [a, b]
        traps.append(
            TrapSpec(a, b, "directed_substitute", "pressure_class", "300", "600",
                     expect_duplicate=False, equivalence=("a_to_b", "rule"))
        )

    return products, traps


# --------------------------------------------------------------------------
# Equivalence ground truth (§2B)
# --------------------------------------------------------------------------


def _within_tolerance(spec, a: float, b: float) -> bool:
    if spec.tolerance_pct:
        return abs(a - b) <= spec.tolerance_pct / 100.0 * max(abs(a), abs(b))
    return abs(a - b) <= abs(spec.tolerance or 0.0)


def truth_relation(a: Product, b: Product, schema) -> tuple[str, str] | None:
    """The relation two products genuinely have, from the generator's knowledge.

    Called only for products that already agree on every identity_critical
    attribute. What separates "interchangeable" from "substitutes for" is the
    performance ratings: equal within tolerance means either can replace the
    other, whereas one dominating means the substitution runs one way only.
    """
    b_covers_a = a_covers_b = True
    differs = False

    for spec in schema.performance:
        left, right = a.attrs.get(spec.name), b.attrs.get(spec.name)
        if left is None or right is None:
            continue
        left, right = float(left), float(right)
        if _within_tolerance(spec, left, right):
            continue
        differs = True
        if spec.direction != "higher_ok":
            # An out-of-band difference on an undirected attribute means the
            # two are simply not interchangeable.
            return None
        if right < left:
            b_covers_a = False
        if left < right:
            a_covers_b = False

    if not differs:
        return ("equivalent", "bidirectional")
    if b_covers_a and not a_covers_b:
        return ("supersedes", "a_to_b")
    if a_covers_b and not b_covers_a:
        return ("supersedes", "b_to_a")
    return None


def build_equivalence_truth(products: list[Product]) -> list[tuple[Product, Product, str, str]]:
    """Every genuinely equivalent or substitutable product pair.

    Recording only the planted traps would make equivalence precision
    meaningless: the generator also produces many naturally equivalent pairs —
    two valves alike but for their temperature rating, say — and counting a
    correct call on those as a false positive would misreport the engine.

    Grouping by identity signature keeps this linear in the population rather
    than quadratic: only products that already agree on every identity_critical
    attribute can possibly be related.
    """
    from itertools import combinations

    from .taxonomy import get_schema

    by_identity: dict[tuple, list[Product]] = {}
    for product in products:
        schema = get_schema(product.class_code)
        signature = (
            product.class_code,
            tuple(str(product.attrs.get(spec.name)) for spec in schema.identity_critical),
        )
        by_identity.setdefault(signature, []).append(product)

    out: list[tuple[Product, Product, str, str]] = []
    for (class_code, _), group in by_identity.items():
        if len(group) < 2:
            continue
        schema = get_schema(class_code)
        for a, b in combinations(group, 2):
            relation = truth_relation(a, b, schema)
            if relation:
                out.append((a, b, relation[0], relation[1]))
    return out


# --------------------------------------------------------------------------
# Product population
# --------------------------------------------------------------------------


def allocate(demand: int, caps: dict[str, int] | None = None) -> dict[str, int]:
    """Split demand across classes in proportion to each class's free capacity.

    PPE and chemicals genuinely have fewer distinct variants than valves or
    cables, so an even split would exhaust them and silently under-generate.
    """
    caps = dict(caps) if caps else {cls: class_capacity(cls) for cls in CLASS_SPACES}
    total_cap = sum(caps.values())
    # A floor per class: §0.6 requires a per-class metric breakdown, and a class
    # with 40 rows produces a number too noisy to act on.
    floor = demand // (2 * len(caps))
    alloc = {
        cls: min(cap, max(floor, round(demand * cap / total_cap)))
        for cls, cap in caps.items()
    }
    # Trim proportionally if the floors pushed us over demand.
    while sum(alloc.values()) > demand:
        biggest = max(alloc, key=lambda c: alloc[c])
        if alloc[biggest] <= 0:
            break
        alloc[biggest] -= 1

    # Hand any rounding shortfall to whichever classes still have headroom.
    shortfall = demand - sum(alloc.values())
    for cls in sorted(caps, key=lambda c: caps[c] - alloc[c], reverse=True):
        if shortfall <= 0:
            break
        headroom = caps[cls] - alloc[cls]
        take = min(headroom, shortfall)
        alloc[cls] += take
        shortfall -= take
    return alloc


def build_products(
    rng: random.Random,
    n_shared: int,
    n_singleton: int,
    spread: tuple[int, int] = (2, 4),
    used: dict[str, set[int]] | None = None,
) -> list[Product]:
    """Enumerate distinct ground-truth products across the eight classes.

    Combination indices are sampled without replacement, so every product is
    unique on its rendered attributes by construction — no rejection loop, and
    no silent under-generation when a class saturates.
    """
    demand = n_shared + n_singleton
    taken = used or {cls: set() for cls in CLASS_SPACES}
    free = {
        cls: [i for i in range(class_capacity(cls)) if i not in taken[cls]] for cls in CLASS_SPACES
    }
    alloc = allocate(demand, {cls: len(v) for cls, v in free.items()})

    products: list[Product] = []
    counter = 0
    for cls, want in alloc.items():
        if want <= 0:
            continue
        indices = rng.sample(free[cls], min(want, len(free[cls])))
        taken[cls].update(indices)
        for index in indices:
            counter += 1
            products.append(_finalize(cls, _decode(cls, index), rng, f"G{counter:06d}", index))

    # Interleave classes so the shared/singleton cut is not one class deep.
    rng.shuffle(products)
    for i, product in enumerate(products):
        product.spread = rng.randint(*spread) if i < n_shared else 1
    return products


# --------------------------------------------------------------------------
# Substitution rules (§2B) — seeded as data, editable by stewards
# --------------------------------------------------------------------------

SUBSTITUTION_RULES: dict[str, str] = {
    "bearing.ball.deep_groove": """
- class: bearing.ball.deep_groove
  equivalent_if: [bore_mm ==, outer_dia_mm ==, width_mm ==, seal_type ==]
  substitutable_if: [load_rating_kg >=, temp_max_c >=]
  never_if: [seal_type !=]
""".strip(),
    "valve.gate": """
- class: valve.gate
  equivalent_if: [size_nb_mm ==, pressure_class ==, body_material ==, end_connection ==]
  substitutable_if: [pressure_bar >=, temp_max_c >=]
  never_if: [body_material !=, end_connection !=]
""".strip(),
    "gasket.spiral_wound": """
- class: gasket.spiral_wound
  equivalent_if: [size_nb_mm ==, pressure_class ==, material ==, thickness_mm ==]
  substitutable_if: [temp_max_c >=]
  never_if: [material !=]
""".strip(),
    "pipe.seamless": """
- class: pipe.seamless
  equivalent_if: [nps_mm ==, schedule ==, material ==]
  substitutable_if: [pressure_bar >=]
  never_if: [material !=]
""".strip(),
    "cable.power": """
- class: cable.power
  equivalent_if: [cores ==, csa_mm2 ==, conductor ==, insulation ==, voltage_v ==]
  substitutable_if: [temp_max_c >=]
  never_if: [conductor !=]
""".strip(),
}


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------

PROFILES = {
    # The demo profile keeps §7's shape exactly: each product is rendered into
    # 1-4 CPSE-specific descriptions. Every demo flow and metric gate uses it.
    "demo": {
        "cpses": 4, "per_cpse": 3000, "spread": (2, 4),
        "shared": 2200, "fill_singletons": True, "same_cpse_twice": False,
    },
    # Small, fast profile for the test suite — same machinery, fewer rows.
    "test": {
        "cpses": 2, "per_cpse": 400, "spread": (2, 2),
        "shared": 250, "fill_singletons": True, "same_cpse_twice": False,
    },
    # The benchmark profile exists only for the §8A performance run. The
    # attribute space cannot express 150k distinct products, so it raises the
    # multiplicity instead and allows the same product to appear twice inside
    # one CPSE — which is itself a real phenomenon in CPSE material masters.
    "large": {
        "cpses": 6, "per_cpse": 25000, "spread": (6, 16),
        "shared": None, "fill_singletons": False, "same_cpse_twice": True,
    },
}

HOLDOUT_FRACTION = 0.40  # §0.6: 60% tuning / 40% held out
TUNING, HOLDOUT = "tuning", "holdout"

#: Combination indices held back for planted traps, so they never collide with
#: the ordinary population.
TRAP_BUDGET = 500

#: How many shared products get a rating-rounding difference between two
#: catalogues — the in-band case that must still resolve to a duplicate.
INBAND_TRAPS = 40
_INSERT_BATCH = 2000


def _bulk(db: Session, model, rows: list[dict]) -> None:
    for i in range(0, len(rows), _INSERT_BATCH):
        db.execute(insert(model), rows[i : i + _INSERT_BATCH])
    db.commit()


def seed_database(db: Session, profile: str = "demo", reset: bool = True) -> dict:
    """Generate a full synthetic estate with ground truth. Reproducible."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {sorted(PROFILES)}")
    conf = PROFILES[profile]
    rng = random.Random(SEED)

    if reset:
        reset_db()

    # --- organisations and users ---
    styles = CPSE_PROFILES[: conf["cpses"]]
    db.execute(insert(Cpse), [{"code": s.code, "name": s.name} for s in styles])
    db.commit()
    cpse_ids = {c.code: c.id for c in db.execute(select(Cpse)).scalars()}

    db.execute(
        insert(User),
        [
            {
                "email": email, "name": name, "role": role,
                "password_hash": hash_password("demo"),
                "cpse_id": cpse_ids.get(cpse_code) if cpse_code else None,
                "active": True,
            }
            for email, name, role, cpse_code in SEED_USERS
        ],
    )
    db.commit()

    # --- ground-truth products ---
    total_target = conf["cpses"] * conf["per_cpse"]
    capacity = sum(class_capacity(cls) for cls in CLASS_SPACES)
    spread = tuple(conf["spread"])
    avg_spread = sum(spread) / 2

    # Combination indices are reserved across the whole run, so a trap product
    # can never coincide with an ordinary one.
    used: dict[str, set[int]] = {cls: set() for cls in CLASS_SPACES}

    if conf["shared"] is None:
        n_shared, n_singleton = max(capacity - TRAP_BUDGET, 1), 0
    else:
        n_shared = min(int(conf["shared"]), capacity)
        n_singleton = (
            min(max(total_target - round(avg_spread * n_shared) - TRAP_BUDGET * 2, 0),
                capacity - n_shared - TRAP_BUDGET)
            if conf["fill_singletons"]
            else 0
        )

    # Traps are planted BEFORE the general population. Planted afterwards they
    # compete for the last few free combinations and quietly fail to appear,
    # which would leave veto precision measured against almost nothing.
    trap_products, traps = _plant_traps(rng, used)
    products = build_products(rng, n_shared, n_singleton, spread, used)

    # Evaluation split, assigned per product and forced to agree across a
    # trap pair so a trap is never split across tuning and held-out.
    splits: dict[str, str] = {
        p.group_id: (HOLDOUT if rng.random() < HOLDOUT_FRACTION else TUNING)
        for p in products
    }
    for trap in traps:
        split = HOLDOUT if rng.random() < HOLDOUT_FRACTION else TUNING
        splits[trap.product_a.group_id] = split
        splits[trap.product_b.group_id] = split
    for p in trap_products:
        splits.setdefault(p.group_id, TUNING)

    all_products = products + trap_products

    # --- in-band rating differences (still the same material) ---
    # Two catalogues rounding the same rating differently is the realistic
    # source of a sub-tolerance difference. These pairs stay in one truth group
    # and assert that the tolerance band resolves them as duplicates.
    inband_candidates = [
        p for p in products
        if p.spread >= 2 and p.class_code in ("valve.gate", "bearing.ball.deep_groove")
    ]
    inband = set(
        p.group_id for p in rng.sample(inband_candidates, min(INBAND_TRAPS, len(inband_candidates)))
    )

    # --- render catalogue rows ---
    raw_rows: list[dict] = []
    renderings: dict[str, list[str]] = {}  # group_id -> legacy codes
    counters = {s.code: 0 for s in styles}

    for product in all_products:
        want = product.spread
        if conf["same_cpse_twice"]:
            chosen = rng.choices(styles, k=want)
        else:
            chosen = rng.sample(styles, min(want, len(styles)))
        codes: list[str] = []
        for style in chosen:
            counters[style.code] += 1
            legacy = f"{style.code}{counters[style.code]:06d}"
            description = render(product, style, rng)
            unit_price = round(product.base_price * rng.uniform(0.85, 1.25), 2)
            uom_word = style.uom_words.get("EA", "EA")

            # Pack basis quirk: a minority of rows are catalogued by the box,
            # which is what exercises the §2A.1 pack-size normalization.
            pack = 1
            if rng.random() < 0.08:
                pack = rng.choice((10, 25, 50, 100))
                description = f"{description}, BOX OF {pack}"
                uom_word = "BOX"

            # Second catalogue states the rating 3% differently — inside the
            # 5% performance band, so still the same material.
            if product.group_id in inband and codes:
                description = _perturb_rating(description, 1.03)

            raw_rows.append(
                {
                    "cpse_id": cpse_ids[style.code],
                    "legacy_code": legacy,
                    "description": description,
                    "uom": uom_word,
                    "plant": rng.choice(style.plants),
                    "price": round(unit_price * pack, 2),
                    "qty_on_hand": float(rng.randint(0, 800)),
                }
            )
            codes.append(legacy)
        renderings[product.group_id] = codes

    _bulk(db, RawItem, raw_rows)

    raw_id_by_code = {
        code: rid for rid, code in db.execute(select(RawItem.id, RawItem.legacy_code)).all()
    }

    # --- ground truth ---
    _bulk(
        db,
        TruthGroup,
        [
            {
                "raw_item_id": raw_id_by_code[code],
                "group_id": product.group_id,
                "split": splits.get(product.group_id, "tuning"),
            }
            for product in all_products
            for code in renderings[product.group_id]
        ],
    )

    trap_rows: list[dict] = []
    equiv_rows: list[dict] = []
    for trap in traps:
        split = splits.get(trap.product_a.group_id, "tuning")
        for code_a in renderings.get(trap.product_a.group_id, []):
            for code_b in renderings.get(trap.product_b.group_id, []):
                a_id, b_id = raw_id_by_code[code_a], raw_id_by_code[code_b]
                trap_rows.append(
                    {
                        "raw_item_a": a_id, "raw_item_b": b_id,
                        "trap_kind": trap.kind, "offending_attr": trap.attr,
                        "value_a": trap.value_a, "value_b": trap.value_b,
                        "expect_duplicate": trap.expect_duplicate, "split": split,
                    }
                )

    for product in products:
        if product.group_id not in inband:
            continue
        codes = renderings.get(product.group_id, [])
        if len(codes) < 2:
            continue
        trap_rows.append(
            {
                "raw_item_a": raw_id_by_code[codes[0]],
                "raw_item_b": raw_id_by_code[codes[1]],
                "trap_kind": "performance_in_band",
                "offending_attr": "rating",
                "value_a": "stated",
                "value_b": "stated +3%",
                "expect_duplicate": True,
                "split": splits.get(product.group_id, "tuning"),
            }
        )

    _bulk(db, TruthTrap, trap_rows)

    # §2B ground truth, computed exhaustively over the product population and
    # recorded once per product pair. Metrics expand it across renderings via
    # truth_group, which keeps this table small and the measurement complete.
    for a, b, rel_type, direction in build_equivalence_truth(all_products):
        codes_a = renderings.get(a.group_id, [])
        codes_b = renderings.get(b.group_id, [])
        if not codes_a or not codes_b:
            continue
        # A pair is held out if either side is: measuring it otherwise would
        # let a tuning-set product influence a held-out number.
        split = (
            HOLDOUT
            if HOLDOUT in (splits.get(a.group_id), splits.get(b.group_id))
            else TUNING
        )
        equiv_rows.append(
            {
                "raw_item_a": raw_id_by_code[codes_a[0]],
                "raw_item_b": raw_id_by_code[codes_b[0]],
                "rel_type": rel_type,
                "direction": direction,
                "basis": "designation" if a.brand != b.brand else "rule",
                "split": split,
            }
        )
    _bulk(db, TruthEquivalence, equiv_rows)

    # --- cross-reference table (§2B evidence source 2) ---
    crossrefs: list[dict] = []
    for designation in sorted(DEEP_GROOVE_DIMS):
        brands = ("SKF", "FAG", "NSK")
        for i in range(len(brands)):
            for j in range(i + 1, len(brands)):
                crossrefs.append(
                    {
                        "mpn_a": f"{designation}{_BEARING_BRAND_SUFFIX[brands[i]]}",
                        "brand_a": brands[i],
                        "mpn_b": f"{designation}{_BEARING_BRAND_SUFFIX[brands[j]]}",
                        "brand_b": brands[j],
                        "source": "seed",
                    }
                )
    _bulk(db, Crossref, crossrefs)

    _bulk(
        db,
        SubstitutionRule,
        [
            {"class_code": cls, "rule_yaml": yaml_text, "author": "seed", "active": True}
            for cls, yaml_text in SUBSTITUTION_RULES.items()
        ],
    )

    # --- normalize + extract so downstream facts can reference `item` ---
    item_count = build_items(db)

    # --- commercial and inventory facts ---
    item_rows = db.execute(
        select(RawItem.id, RawItem.cpse_id, RawItem.price, RawItem.plant)
    ).all()
    price_by_raw = {rid: (cpse_id, price, plant) for rid, cpse_id, price, plant in item_rows}
    id_pairs = db.execute(select(Item.id, Item.raw_item_id, Item.pack_qty)).all()
    plants_by_cpse = {cpse_ids[s.code]: s.plants for s in styles}
    today = date.today()

    po_rows: list[dict] = []
    stock_rows: list[dict] = []
    for item_id, raw_id, pack_qty in id_pairs:
        cpse_id, price, plant = price_by_raw[raw_id]
        unit_price = (price or 0.0) / max(pack_qty or 1.0, 1.0)
        vendors = VENDORS.get("bearing.ball.deep_groove")

        for _ in range(rng.choices((0, 1, 2, 3, 4), weights=(15, 30, 25, 20, 10))[0]):
            po_rows.append(
                {
                    "item_id": item_id,
                    "cpse_id": cpse_id,
                    "po_date": today - timedelta(days=rng.randint(1, 540)),
                    "qty": float(rng.randint(1, 250)),
                    "unit_price": round(unit_price * rng.uniform(0.92, 1.08), 2),
                    "vendor": rng.choice(
                        vendors if vendors else ("GENERAL SUPPLIES",)
                    ),
                }
            )

        qty = float(rng.randint(0, 800))
        # 20% of rows have not moved in over a year — the dead-stock population.
        days_since_movement = rng.randint(400, 900) if rng.random() < 0.20 else rng.randint(1, 360)
        stock_rows.append(
            {
                "item_id": item_id,
                "cpse_id": cpse_id,
                "plant": rng.choice(plants_by_cpse.get(cpse_id, (plant or "MAIN",))),
                "qty_on_hand": qty,
                "reserved_qty": round(qty * rng.uniform(0, 0.2), 1),
                "last_movement_date": today - timedelta(days=days_since_movement),
                "unit_value": round(unit_price, 2),
            }
        )

    _bulk(db, PurchaseHistory, po_rows)
    _bulk(db, Stock, stock_rows)

    return {
        "profile": profile,
        "cpses": len(styles),
        "raw_items": len(raw_rows),
        "items": item_count,
        "products": len(all_products),
        "shared_products": n_shared,
        "singleton_products": n_singleton,
        "trap_products": len(trap_products),
        "truth_traps": len(trap_rows),
        "truth_equivalences": len(equiv_rows),
        "crossrefs": len(crossrefs),
        "purchase_history": len(po_rows),
        "stock": len(stock_rows),
        "users": len(SEED_USERS),
        "holdout_fraction": HOLDOUT_FRACTION,
    }
