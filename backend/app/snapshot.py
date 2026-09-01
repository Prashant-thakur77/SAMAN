"""Demo snapshots — restore a known-good state in seconds (spec §8A).

A live demo goes wrong in one of two ways: someone approves the wrong cluster
five minutes before you present, or a question sends you down a path that
mutates the data you were about to show. Re-seeding costs minutes. This costs
about a second.

Both databases are captured, because they are two systems and a half-restored
pair is worse than either: the platform's own SQLite file and the mock ERP.
`VACUUM INTO` is used rather than a file copy -- SQLite in WAL mode keeps recent
writes in a sidecar file, so copying just the `.db` can silently capture a
database missing its most recent transactions.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from . import erp
from .config import get_settings

#: One directory holding one snapshot. A history is not what this is for --
#: "get back to the state I demo from" is.
SNAPSHOT_DIRNAME = "snapshot"


def snapshot_dir() -> Path:
    return get_settings().db_file.parent / SNAPSHOT_DIRNAME


def _targets() -> list[tuple[str, Path]]:
    return [("app", get_settings().db_file), ("erp", erp.erp_path())]


@dataclass
class SnapshotResult:
    files: list[str]
    bytes_written: int
    seconds: float

    def as_dict(self) -> dict:
        return {
            "files": self.files,
            "bytes": self.bytes_written,
            "seconds": round(self.seconds, 3),
        }


def exists() -> bool:
    directory = snapshot_dir()
    return directory.is_dir() and any(directory.glob("*.db"))


def capture() -> SnapshotResult:
    """Write a consistent copy of every database into the snapshot directory."""
    started = time.perf_counter()
    directory = snapshot_dir()
    directory.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    total = 0
    for name, source in _targets():
        if not source.exists():
            continue
        destination = directory / f"{name}.db"
        # VACUUM INTO refuses to overwrite, and it also compacts, which is why
        # a restore is fast: the snapshot has no free pages to read past.
        destination.unlink(missing_ok=True)
        connection = sqlite3.connect(source)
        try:
            connection.execute("VACUUM INTO ?", (str(destination),))
        finally:
            connection.close()
        written.append(destination.name)
        total += destination.stat().st_size

    return SnapshotResult(written, total, time.perf_counter() - started)


def restore() -> SnapshotResult:
    """Put every database back to the snapshot. Raises if there is none."""
    if not exists():
        raise FileNotFoundError(
            f"no snapshot in {snapshot_dir()} — run `make demo-snapshot` first"
        )

    started = time.perf_counter()
    from .db import dispose_engine

    # Every open connection has to go first. A restored file underneath a live
    # connection is how you get "database disk image is malformed" on stage.
    dispose_engine()

    restored: list[str] = []
    total = 0
    for name, destination in _targets():
        source = snapshot_dir() / f"{name}.db"
        if not source.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        # The sidecars belong to the database being replaced; leaving them in
        # place would let SQLite replay writes that the snapshot predates.
        for suffix in ("-wal", "-shm"):
            destination.with_name(destination.name + suffix).unlink(missing_ok=True)
        shutil.copyfile(source, destination)
        restored.append(destination.name)
        total += destination.stat().st_size

    _reset_caches()
    return SnapshotResult(restored, total, time.perf_counter() - started)


def _reset_caches() -> None:
    """Drop anything derived from the database we just replaced."""
    from . import smart_create

    smart_create.reset_embedder_cache()
