"""ERP connector interface and a mock SAP — spec §2C.

Exporting a mapping file is a report. Migration means the CPSE's own material
master starts pointing at the CNMC, which needs a connector that can *write*.
The interface here is the whole contract a real adapter would implement; the
mock behind it is a small SQLite database shaped like the SAP tables a
consolidation actually touches:

    MARA   material master        (MATNR, material type, base UoM, deletion flag)
    MAKT   material descriptions  (MATNR, language, text)
    EKPO   purchase order items   (open quantity — the reason a record is held)
    MARD   plant stock            (unrestricted quantity)
    MBEW   material valuation     (moving average price, total value)

Two rules are baked into the mock because they are what real consolidations get
wrong: a superseded material is **blocked, never deleted** (SAP sets a deletion
flag; the row and its history stay), and any material carrying open
transactions is held back rather than changed underneath them.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import get_settings

MARA_DDL = """
CREATE TABLE IF NOT EXISTS mara (
    matnr TEXT PRIMARY KEY,
    mtart TEXT NOT NULL,
    meins TEXT,
    werks TEXT,
    lvorm TEXT DEFAULT '',        -- deletion/blocked flag, SAP-style
    zz_cnmc TEXT DEFAULT '',      -- customer field holding the national code
    zz_supersedes TEXT DEFAULT '' -- the surviving master this defers to
)
"""
MAKT_DDL = """
CREATE TABLE IF NOT EXISTS makt (
    matnr TEXT NOT NULL,
    spras TEXT NOT NULL DEFAULT 'EN',
    maktx TEXT NOT NULL,
    PRIMARY KEY (matnr, spras)
)
"""
EKPO_DDL = """
CREATE TABLE IF NOT EXISTS ekpo (
    ebeln TEXT NOT NULL,
    ebelp INTEGER NOT NULL,
    matnr TEXT NOT NULL,
    menge REAL NOT NULL,
    open_qty REAL NOT NULL,
    netpr REAL NOT NULL,
    PRIMARY KEY (ebeln, ebelp)
)
"""
MARD_DDL = """
CREATE TABLE IF NOT EXISTS mard (
    matnr TEXT NOT NULL,
    werks TEXT NOT NULL,
    labst REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (matnr, werks)
)
"""
MBEW_DDL = """
CREATE TABLE IF NOT EXISTS mbew (
    matnr TEXT NOT NULL,
    bwkey TEXT NOT NULL,
    verpr REAL NOT NULL DEFAULT 0,
    salk3 REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (matnr, bwkey)
)
"""

TABLES = ("mara", "makt", "ekpo", "mard", "mbew")


def erp_path() -> Path:
    """The mock ERP lives beside the app database, as a separate system would."""
    return get_settings().db_file.with_name("erp_mock.db")


def connect(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(path or erp_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialise(path: Path | None = None) -> None:
    with connect(path) as conn:
        for ddl in (MARA_DDL, MAKT_DDL, EKPO_DDL, MARD_DDL, MBEW_DDL):
            conn.execute(ddl)


def fingerprint(path: Path | None = None) -> str:
    """A hash of the ERP's entire contents.

    §2C asks that a rollback restore the mock ERP to a byte-identical prior
    state. Hashing every row in a stable order is how that is asserted rather
    than assumed.
    """
    digest = hashlib.sha256()
    with connect(path) as conn:
        for table in TABLES:
            digest.update(table.encode())
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for row in sorted(tuple(str(value) for value in r) for r in rows):
                digest.update("\x1f".join(row).encode())
    return digest.hexdigest()


@dataclass
class OpenTransactions:
    matnr: str
    open_po_lines: int
    open_qty: float
    stock_qty: float
    total_value: float

    @property
    def blocks_change(self) -> bool:
        """Open purchase orders are the reason to hold a record back (§2C)."""
        return self.open_po_lines > 0

    def as_dict(self) -> dict:
        return {
            "matnr": self.matnr,
            "open_po_lines": self.open_po_lines,
            "open_qty": round(self.open_qty, 1),
            "stock_qty": round(self.stock_qty, 1),
            "total_value": round(self.total_value, 2),
            "blocks_change": self.blocks_change,
        }


class ErpAdapter(Protocol):
    """What a real SAP connector would have to provide (§2C).

    A production adapter would implement these over a BAPI/IDoc batch or an
    LSMW/LTMC load file; the shape of the contract is the same either way, which
    is the point of naming it here rather than only in prose.
    """

    def read_masters(self, matnrs: list[str]) -> dict[str, dict]: ...

    def read_open_transactions(self, matnrs: list[str]) -> dict[str, OpenTransactions]: ...

    def write_crossref(self, matnr: str, cnmc: str) -> dict: ...

    def block_material(self, matnr: str, supersedes: str) -> dict: ...

    def restore(self, matnr: str, before: dict) -> None: ...

    # Bulk forms. A rollout writes thousands of rows at once and a real
    # connector would batch them into one BAPI call for exactly the reason the
    # mock does: a round trip per material does not scale.
    def write_crossref_many(self, pairs: list[tuple[str, str]]) -> int: ...

    def block_material_many(self, pairs: list[tuple[str, str]]) -> int: ...

    def restore_many(self, rows: list[tuple[str, dict]]) -> int: ...


class MockErpAdapter:
    """The in-repo SAP stand-in. Every write is reversible from its before-image."""

    def __init__(self, path: Path | None = None):
        self.path = path or erp_path()
        initialise(self.path)

    # -- reads ------------------------------------------------------------

    def read_masters(self, matnrs: list[str]) -> dict[str, dict]:
        if not matnrs:
            return {}
        placeholders = ",".join("?" * len(matnrs))
        with connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT * FROM mara WHERE matnr IN ({placeholders})",
                matnrs,
            ).fetchall()
        return {row["matnr"]: dict(row) for row in rows}

    def read_open_transactions(self, matnrs: list[str]) -> dict[str, OpenTransactions]:
        if not matnrs:
            return {}
        placeholders = ",".join("?" * len(matnrs))
        with connect(self.path) as conn:
            pos = {
                row["matnr"]: (row["lines"], row["qty"])
                for row in conn.execute(
                    f"SELECT matnr, COUNT(*) AS lines, COALESCE(SUM(open_qty),0) AS qty "
                    f"FROM ekpo WHERE open_qty > 0 AND matnr IN ({placeholders}) GROUP BY matnr",
                    matnrs,
                )
            }
            stock = {
                row["matnr"]: row["qty"]
                for row in conn.execute(
                    f"SELECT matnr, COALESCE(SUM(labst),0) AS qty FROM mard "
                    f"WHERE matnr IN ({placeholders}) GROUP BY matnr",
                    matnrs,
                )
            }
            value = {
                row["matnr"]: row["val"]
                for row in conn.execute(
                    f"SELECT matnr, COALESCE(SUM(salk3),0) AS val FROM mbew "
                    f"WHERE matnr IN ({placeholders}) GROUP BY matnr",
                    matnrs,
                )
            }
        return {
            matnr: OpenTransactions(
                matnr=matnr,
                open_po_lines=pos.get(matnr, (0, 0.0))[0],
                open_qty=pos.get(matnr, (0, 0.0))[1],
                stock_qty=stock.get(matnr, 0.0),
                total_value=value.get(matnr, 0.0),
            )
            for matnr in matnrs
        }

    # -- writes -----------------------------------------------------------

    def write_crossref(self, matnr: str, cnmc: str) -> dict:
        """Point a surviving master at its national code."""
        with connect(self.path) as conn:
            conn.execute("UPDATE mara SET zz_cnmc = ? WHERE matnr = ?", (cnmc, matnr))
            row = conn.execute("SELECT * FROM mara WHERE matnr = ?", (matnr,)).fetchone()
        return dict(row) if row else {}

    def block_material(self, matnr: str, supersedes: str) -> dict:
        """Block a superseded material. Never a delete — the row and its history stay."""
        with connect(self.path) as conn:
            conn.execute(
                "UPDATE mara SET lvorm = 'X', zz_supersedes = ? WHERE matnr = ?",
                (supersedes, matnr),
            )
            row = conn.execute("SELECT * FROM mara WHERE matnr = ?", (matnr,)).fetchone()
        return dict(row) if row else {}

    def restore(self, matnr: str, before: dict) -> None:
        """Put a row back exactly as it was, from its before-image."""
        self.restore_many([(matnr, before)])

    # -- bulk writes ------------------------------------------------------
    #
    # A national rollout writes thousands of rows in one batch. Row-at-a-time
    # meant a connection and a commit — an fsync — per material, which cost 14
    # seconds for 2,109 rows and would have been a blocking HTTP request of the
    # same length. One transaction, one executemany. A real SAP adapter would
    # batch for the same reason; the Protocol says so.

    def write_crossref_many(self, pairs: list[tuple[str, str]]) -> int:
        if not pairs:
            return 0
        with connect(self.path) as conn:
            conn.executemany(
                "UPDATE mara SET zz_cnmc = ? WHERE matnr = ?",
                [(cnmc, matnr) for matnr, cnmc in pairs],
            )
        return len(pairs)

    def block_material_many(self, pairs: list[tuple[str, str]]) -> int:
        if not pairs:
            return 0
        with connect(self.path) as conn:
            conn.executemany(
                "UPDATE mara SET lvorm = 'X', zz_supersedes = ? WHERE matnr = ?",
                [(supersedes, matnr) for matnr, supersedes in pairs],
            )
        return len(pairs)

    def restore_many(self, rows: list[tuple[str, dict]]) -> int:
        if not rows:
            return 0
        with connect(self.path) as conn:
            conn.executemany(
                "UPDATE mara SET lvorm = ?, zz_cnmc = ?, zz_supersedes = ? WHERE matnr = ?",
                [
                    (
                        before.get("lvorm", ""),
                        before.get("zz_cnmc", ""),
                        before.get("zz_supersedes", ""),
                        matnr,
                    )
                    for matnr, before in rows
                ],
            )
        return len(rows)


def seed_from_catalogue(db, path: Path | None = None, open_po_rate: float = 0.12) -> dict:
    """Populate the mock ERP from the seeded CPSE catalogues.

    The point of the exercise is that SAMAN writes into a system it does not
    own, so the mock is loaded from the same raw rows the CPSEs uploaded rather
    than from SAMAN's own derived tables.
    """
    import random

    from sqlalchemy import select

    from .models import Cpse, RawItem

    initialise(path)
    rng = random.Random(20260101)

    rows = db.execute(
        select(
            RawItem.legacy_code,
            RawItem.description,
            RawItem.uom,
            RawItem.plant,
            RawItem.price,
            RawItem.qty_on_hand,
            Cpse.code,
        ).join(Cpse, Cpse.id == RawItem.cpse_id)
    ).all()

    mara, makt, mard, mbew, ekpo = [], [], [], [], []
    for n, (code, description, uom, plant, price, qty, cpse) in enumerate(rows):
        matnr = f"{cpse}-{code}"
        werks = plant or "MAIN"
        mara.append((matnr, "HIBE", (uom or "EA")[:3], werks, "", "", ""))
        makt.append((matnr, "EN", (description or "")[:80]))
        mard.append((matnr, werks, float(qty or 0)))
        mbew.append((matnr, werks, float(price or 0), float(price or 0) * float(qty or 0)))
        # A minority of materials carry an open purchase order. Those are the
        # records a consolidation must hold back rather than change underneath.
        if rng.random() < open_po_rate:
            ekpo.append(
                (f"45{n:08d}", 10, matnr, 100.0, float(rng.randint(1, 80)), float(price or 0))
            )

    with connect(path) as conn:
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO mara VALUES (?,?,?,?,?,?,?)", mara)
        conn.executemany("INSERT INTO makt VALUES (?,?,?)", makt)
        conn.executemany("INSERT INTO mard VALUES (?,?,?)", mard)
        conn.executemany("INSERT INTO mbew VALUES (?,?,?,?)", mbew)
        conn.executemany("INSERT INTO ekpo VALUES (?,?,?,?,?,?)", ekpo)

    return {
        "materials": len(mara),
        "stock_rows": len(mard),
        "valuation_rows": len(mbew),
        "open_po_lines": len(ekpo),
    }
