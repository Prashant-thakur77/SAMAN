"""Command-line entry points used by the Makefile.

    python -m app.cli seed --profile demo
    python -m app.cli pipeline
    python -m app.cli status
"""

from __future__ import annotations

import argparse
import sys
import time

from .db import SessionLocal, init_db
from .pipeline import run_pipeline
from .seed import PROFILES, seed_database


def _print_table(title: str, rows: dict) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for key, value in rows.items():
        formatted = f"{value:,}" if isinstance(value, int) else value
        print(f"  {key.replace('_', ' '):26} {formatted}")


def cmd_seed(args: argparse.Namespace) -> int:
    init_db()
    started = time.time()
    with SessionLocal() as db:
        summary = seed_database(db, profile=args.profile)
    summary["seconds"] = round(time.time() - started, 1)
    _print_table(f"SAMAN seed — {args.profile} profile", summary)
    print("\nSeeded users all use password 'demo'.")
    return 0


def cmd_pipeline(_args: argparse.Namespace) -> int:
    init_db()
    started = time.time()
    with SessionLocal() as db:
        status = run_pipeline(db)
    print(
        f"pipeline {status.state}: stages {', '.join(status.stages_done) or 'none'} "
        f"({round(time.time() - started, 1)}s)"
    )
    return 0 if status.state == "done" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="saman", description="SAMAN maintenance commands")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="generate the synthetic catalogue estate")
    seed.add_argument("--profile", choices=sorted(PROFILES), default="demo")
    seed.set_defaults(func=cmd_seed)

    run = sub.add_parser("pipeline", help="run the pipeline over any unprocessed rows")
    run.set_defaults(func=cmd_pipeline)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
