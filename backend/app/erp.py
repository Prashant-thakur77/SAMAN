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

    from .models import Cpse, Item, RawItem, Stock

    initialise(path)
    rng = random.Random(20260101)

    # Stock and valuation come from `stock`, not from `raw_item.qty_on_hand`.
    # §4 makes `stock` authoritative for every inventory feature, and the mock
    # ERP is one: seeding MARD from the raw snapshot instead left the migration
    # screen reporting 370 units of a material whose item page said 581. Two
    # numbers for one material is the thing this whole platform exists to stop.
    rows = db.execute(
        select(
            RawItem.legacy_code,
            RawItem.description,
            RawItem.uom,
            RawItem.plant,
            RawItem.price,
            RawItem.qty_on_hand,
            Cpse.code,
            Stock.qty_on_hand,
            Stock.unit_value,
            Stock.plant,
        )
        .join(Cpse, Cpse.id == RawItem.cpse_id)
        .join(Item, Item.raw_item_id == RawItem.id, isouter=True)
        .join(Stock, Stock.item_id == Item.id, isouter=True)
    ).all()

    mara, makt, mard, mbew, ekpo = [], [], [], [], []
    for n, row in enumerate(rows):
        (
            code,
            description,
            uom,
            plant,
            price,
            raw_qty,
            cpse,
            stock_qty,
            unit_value,
            stock_plant,
        ) = row
        matnr = f"{cpse}-{code}"
        # A catalogue row that never reached the pipeline has no stock row; fall
        # back to its own snapshot rather than reporting the material as empty.
        qty = float(stock_qty if stock_qty is not None else (raw_qty or 0))
        value = float(unit_value if unit_value is not None else (price or 0))
        werks = stock_plant or plant or "MAIN"
        mara.append((matnr, "HIBE", (uom or "EA")[:3], werks, "", "", ""))
        makt.append((matnr, "EN", (description or "")[:80]))
        mard.append((matnr, werks, qty))
        mbew.append((matnr, werks, value, value * qty))
        # A minority of materials carry an open purchase order. Those are the
        # records a consolidation must hold back rather than change underneath.
        if rng.random() < open_po_rate:
            ekpo.append((f"45{n:08d}", 10, matnr, 100.0, float(rng.randint(1, 80)), value))

    with connect(path) as conn:
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO mara VALUES (?,?,?,?,?,?,?)", mara)
        conn.executemany("INSERT INTO makt VALUES (?,?,?)", makt)
        conn.executemany("INSERT INTO mard VALUES (?,?,?)", mard)
        conn.executemany("INSERT INTO mbew VALUES (?,?,?,?)", mbew)
        conn.executemany("INSERT INTO ekpo VALUES (?,?,?,?,?,?)", ekpo)

    # DELETE leaves the pages behind: a reseeded mock ERP was 54 MB of which
    # 92% was free list. It matters here because the file is an artefact people
    # copy around, and because `fingerprint()` reads every page of it.
    with connect(path) as conn:
        conn.execute("VACUUM")

    return {
        "materials": len(mara),
        "stock_rows": len(mard),
        "valuation_rows": len(mbew),
        "open_po_lines": len(ekpo),
    }


# --------------------------------------------------------------------------
# The SAP door: BAPIs over RFC (docs/sap-integration.md)
# --------------------------------------------------------------------------


class ErpUnavailable(RuntimeError):
    """The requested ERP adapter cannot be used on this machine."""


#: MATNR is CHAR 18; the two customer fields on the MARA append structure are
#: CHAR 20 and CHAR 18 in the convention this project documents. BAPI_TE_MARA
#: is positional, so the widths are part of the contract.
MATNR_WIDTH = 18
CNMC_WIDTH = 20
SUPERSEDES_WIDTH = 18
#: RFC_READ_TABLE takes its WHERE clause as 72-character lines; one material
#: per line keeps every line short and every batch bounded.
RFC_BATCH = 50


def _chunks(values: list, size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _num(text: str | None) -> float:
    try:
        return float((text or "0").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _value_part(matnr: str, cnmc: str | None, supersedes: str | None, flags: bool) -> str:
    """One BAPI_TE_MARA (or MARAX) row: material, then the append fields in order.

    With ``flags`` the row is the X-structure: a mark per field that is to be
    written, so a field can be cleared as well as set."""
    if flags:
        return (
            matnr.ljust(MATNR_WIDTH)
            + ("X" if cnmc is not None else " ")
            + ("X" if supersedes is not None else " ")
        )
    return (
        matnr.ljust(MATNR_WIDTH)
        + (cnmc or "").ljust(CNMC_WIDTH)
        + (supersedes or "").ljust(SUPERSEDES_WIDTH)
    )


def _raise_on_error(result: dict, matnr: str) -> None:
    returned = result.get("RETURN") or []
    messages = returned if isinstance(returned, list) else [returned]
    for message in messages:
        if (message or {}).get("TYPE") in ("E", "A"):
            raise RuntimeError(f"SAP refused {matnr}: {message.get('MESSAGE', '')}".strip())


class RfcErpAdapter:
    """`ErpAdapter` over SAP's RFC interface.

    Reads use RFC_READ_TABLE on the five tables the mock models; writes use
    BAPI_MATERIAL_SAVEDATA for the deletion flag and, through the BAPI_TE_MARA
    extension, the two customer fields that carry the national code and the
    surviving master; every batch ends with BAPI_TRANSACTION_COMMIT. Written
    against the connector's documented call shapes and tested with a fake
    connection that records the calls; not yet run against a live SAP system.
    """

    def __init__(
        self,
        connection,
        cnmc_field: str = "ZZ_CNMC",
        supersedes_field: str = "ZZ_SUPERSEDES",
        batch: int = RFC_BATCH,
    ):
        self.conn = connection
        self.cnmc_field = cnmc_field.upper()
        self.supersedes_field = supersedes_field.upper()
        self.batch = batch

    @classmethod
    def from_settings(cls, settings) -> RfcErpAdapter:
        try:
            from pyrfc import Connection
        except ImportError as exc:
            raise ErpUnavailable("pyrfc (and the SAP NetWeaver RFC SDK) is not installed") from exc
        if not (settings.sap_ashost and settings.sap_user and settings.sap_passwd):
            raise ErpUnavailable(
                "SAP_ASHOST, SAP_USER and SAP_PASSWD must be set for the rfc adapter"
            )
        try:
            connection = Connection(
                ashost=settings.sap_ashost,
                sysnr=settings.sap_sysnr,
                client=settings.sap_client,
                user=settings.sap_user,
                passwd=settings.sap_passwd,
            )
        except Exception as exc:  # the connector raises its own hierarchy
            raise ErpUnavailable(
                f"could not open an RFC connection to {settings.sap_ashost}: {exc}"
            ) from exc
        return cls(connection, settings.sap_cnmc_field, settings.sap_supersedes_field)

    # -- reads ------------------------------------------------------------

    @staticmethod
    def _options(matnrs: list[str], extra: tuple[str, ...] = ()) -> list[dict]:
        lines = []
        for i, matnr in enumerate(matnrs):
            head = "( " if i == 0 else ""
            tail = " )" if i == len(matnrs) - 1 else " OR"
            lines.append({"TEXT": f"{head}MATNR EQ '{matnr}'{tail}"})
        for clause in extra:
            lines.append({"TEXT": f"AND {clause}"})
        return lines

    def _read_table(
        self, table: str, fields: list[str], matnrs: list[str], extra: tuple[str, ...] = ()
    ) -> list[dict]:
        rows: list[dict] = []
        for chunk in _chunks(list(matnrs), self.batch):
            result = self.conn.call(
                "RFC_READ_TABLE",
                QUERY_TABLE=table,
                DELIMITER="|",
                FIELDS=[{"FIELDNAME": f} for f in fields],
                OPTIONS=self._options(chunk, extra),
            )
            for entry in result.get("DATA", []):
                values = entry["WA"].split("|")
                rows.append({f.lower(): v.strip() for f, v in zip(fields, values, strict=False)})
        return rows

    def read_masters(self, matnrs: list[str]) -> dict[str, dict]:
        if not matnrs:
            return {}
        fields = ["MATNR", "MTART", "MEINS", "LVORM", self.cnmc_field, self.supersedes_field]
        out: dict[str, dict] = {}
        for row in self._read_table("MARA", fields, matnrs):
            # The mock's column names are the contract's; the customer fields
            # map onto them whatever a site called them.
            out[row["matnr"]] = {
                "matnr": row["matnr"],
                "mtart": row.get("mtart", ""),
                "meins": row.get("meins", ""),
                "lvorm": row.get("lvorm", ""),
                "zz_cnmc": row.get(self.cnmc_field.lower(), ""),
                "zz_supersedes": row.get(self.supersedes_field.lower(), ""),
            }
        return out

    def read_open_transactions(self, matnrs: list[str]) -> dict[str, OpenTransactions]:
        if not matnrs:
            return {}
        pos: dict[str, tuple[int, float]] = {}
        # Not deleted and delivery not complete: the lines a consolidation
        # must not change a material underneath.
        for row in self._read_table(
            "EKPO", ["MATNR", "MENGE"], matnrs, extra=("LOEKZ EQ ''", "ELIKZ EQ ''")
        ):
            lines, qty = pos.get(row["matnr"], (0, 0.0))
            pos[row["matnr"]] = (lines + 1, qty + _num(row.get("menge")))
        stock: dict[str, float] = {}
        for row in self._read_table("MARD", ["MATNR", "LABST"], matnrs):
            stock[row["matnr"]] = stock.get(row["matnr"], 0.0) + _num(row.get("labst"))
        value: dict[str, float] = {}
        for row in self._read_table("MBEW", ["MATNR", "SALK3"], matnrs):
            value[row["matnr"]] = value.get(row["matnr"], 0.0) + _num(row.get("salk3"))
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

    def _save(
        self,
        matnr: str,
        del_flag: str | None = None,
        cnmc: str | None = None,
        supersedes: str | None = None,
    ) -> dict:
        params: dict = {"HEADDATA": {"MATERIAL": matnr, "BASIC_VIEW": "X"}}
        if del_flag is not None:
            params["CLIENTDATA"] = {"DEL_FLAG": del_flag}
            params["CLIENTDATAX"] = {"DEL_FLAG": "X"}
        if cnmc is not None or supersedes is not None:
            params["EXTENSIONIN"] = [
                {
                    "STRUCTURE": "BAPI_TE_MARA",
                    "VALUEPART1": _value_part(matnr, cnmc, supersedes, False),
                }
            ]
            params["EXTENSIONINX"] = [
                {
                    "STRUCTURE": "BAPI_TE_MARAX",
                    "VALUEPART1": _value_part(matnr, cnmc, supersedes, True),
                }
            ]
        result = self.conn.call("BAPI_MATERIAL_SAVEDATA", **params)
        _raise_on_error(result, matnr)
        return result

    def _commit(self) -> None:
        self.conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

    def write_crossref(self, matnr: str, cnmc: str) -> dict:
        self._save(matnr, cnmc=cnmc)
        self._commit()
        return self.read_masters([matnr]).get(matnr, {})

    def block_material(self, matnr: str, supersedes: str) -> dict:
        self._save(matnr, del_flag="X", supersedes=supersedes)
        self._commit()
        return self.read_masters([matnr]).get(matnr, {})

    def restore(self, matnr: str, before: dict) -> None:
        self.restore_many([(matnr, before)])

    def write_crossref_many(self, pairs: list[tuple[str, str]]) -> int:
        for matnr, cnmc in pairs:
            self._save(matnr, cnmc=cnmc)
        if pairs:
            self._commit()
        return len(pairs)

    def block_material_many(self, pairs: list[tuple[str, str]]) -> int:
        for matnr, supersedes in pairs:
            self._save(matnr, del_flag="X", supersedes=supersedes)
        if pairs:
            self._commit()
        return len(pairs)

    def restore_many(self, rows: list[tuple[str, dict]]) -> int:
        for matnr, before in rows:
            self._save(
                matnr,
                del_flag=before.get("lvorm", ""),
                cnmc=before.get("zz_cnmc", ""),
                supersedes=before.get("zz_supersedes", ""),
            )
        if rows:
            self._commit()
        return len(rows)


# --------------------------------------------------------------------------
# Which door is open on this machine
# --------------------------------------------------------------------------

_rfc_cache: tuple[str, object, str | None] | None = None


def reset_adapter() -> None:
    global _rfc_cache
    _rfc_cache = None


def get_adapter():
    """The adapter the settings ask for, or the mock with a reason (§0.4)."""
    global _rfc_cache
    settings = get_settings()
    if (settings.saman_erp_adapter or "mock").strip().lower() != "rfc":
        return MockErpAdapter()
    if _rfc_cache is None:
        try:
            _rfc_cache = ("rfc", RfcErpAdapter.from_settings(settings), None)
        except ErpUnavailable as exc:
            _rfc_cache = ("mock", MockErpAdapter(), str(exc))
    return _rfc_cache[1]


def adapter_status() -> dict:
    """For /api/health and the Migration screen: what is live, and why."""
    settings = get_settings()
    requested = (settings.saman_erp_adapter or "mock").strip().lower()
    if requested != "rfc":
        return {
            "requested": requested,
            "mode": "mock",
            "engine": "mock SAP (SQLite: MARA, MAKT, EKPO, MARD, MBEW)",
            "degraded": False,
            "note": "The demo's SAP stand-in; set SAMAN_ERP_ADAPTER=rfc for a live system.",
        }
    get_adapter()
    mode, _, reason = _rfc_cache or ("mock", None, "not initialised")
    if mode == "rfc":
        return {
            "requested": "rfc",
            "mode": "rfc",
            "engine": f"SAP RFC via pyrfc ({settings.sap_ashost}, client {settings.sap_client})",
            "degraded": False,
            "note": "BAPI_MATERIAL_SAVEDATA writes, RFC_READ_TABLE reads, one commit per batch.",
        }
    return {
        "requested": "rfc",
        "mode": "mock",
        "engine": "mock SAP (SQLite: MARA, MAKT, EKPO, MARD, MBEW)",
        "degraded": True,
        "note": f"SAP RFC requested but unavailable ({reason}); using the mock ERP",
    }
