"""Class-schema registry — loads and validates `data/classes.yaml` (§2A, §2D).

Schemas are data. This module is the only place that reads the YAML, so the
extractor, the veto layer and the description renderer all see one definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SCHEMA_PATH = Path(__file__).parent / "data" / "classes.yaml"

UNCLASSIFIED = "unclassified"

ROLES = {"identity_critical", "performance", "cosmetic"}
TYPES = {"numeric", "enum", "categorical"}


@dataclass(frozen=True)
class AttrSpec:
    name: str
    type: str
    role: str
    unit: str | None = None
    tolerance: float | None = None
    tolerance_pct: float | None = None
    direction: str | None = None  # higher_ok — B may substitute A if B >= A
    values: tuple[str, ...] = ()

    @property
    def vetoes(self) -> bool:
        """identity_critical attributes can refuse a match outright (§2A)."""
        return self.role == "identity_critical"


@dataclass(frozen=True)
class ClassSchema:
    code: str
    label: str
    noun: str
    keywords: tuple[str, ...]
    template: str
    block_on: str | None
    attributes: dict[str, AttrSpec]

    def by_role(self, role: str) -> list[AttrSpec]:
        return [a for a in self.attributes.values() if a.role == role]

    @property
    def identity_critical(self) -> list[AttrSpec]:
        return self.by_role("identity_critical")

    @property
    def performance(self) -> list[AttrSpec]:
        return self.by_role("performance")


def _parse_attr(name: str, raw: dict[str, Any]) -> AttrSpec:
    role = raw.get("role")
    if role not in ROLES:
        raise ValueError(f"attribute {name!r}: role {role!r} not in {sorted(ROLES)}")
    typ = raw.get("type")
    if typ not in TYPES:
        raise ValueError(f"attribute {name!r}: type {typ!r} not in {sorted(TYPES)}")
    return AttrSpec(
        name=name,
        type=typ,
        role=role,
        unit=raw.get("unit"),
        tolerance=raw.get("tolerance"),
        tolerance_pct=raw.get("tolerance_pct"),
        direction=raw.get("direction"),
        values=tuple(str(v) for v in raw.get("values", []) or []),
    )


@lru_cache
def load_schemas() -> dict[str, ClassSchema]:
    doc = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
    out: dict[str, ClassSchema] = {}
    for code, raw in doc["classes"].items():
        attrs = {n: _parse_attr(n, a) for n, a in (raw.get("attributes") or {}).items()}
        block_on = raw.get("block_on")
        if block_on and block_on not in attrs:
            raise ValueError(f"class {code!r}: block_on {block_on!r} is not one of its attributes")
        out[code] = ClassSchema(
            code=code,
            label=raw["label"],
            noun=raw["noun"],
            keywords=tuple(raw.get("keywords") or []),
            template=raw["template"],
            block_on=block_on,
            attributes=attrs,
        )
    if UNCLASSIFIED not in out:
        raise ValueError("classes.yaml must define an 'unclassified' fallback class")
    return out


def get_schema(class_code: str) -> ClassSchema:
    """Never raises: an unknown class falls back to the schema-less pool (§2A.1)."""
    return load_schemas().get(class_code, load_schemas()[UNCLASSIFIED])


def real_classes() -> list[ClassSchema]:
    """Every class except the unclassified fallback."""
    return [s for c, s in load_schemas().items() if c != UNCLASSIFIED]
