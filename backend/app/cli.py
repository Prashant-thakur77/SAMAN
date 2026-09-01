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
        from .erp import seed_from_catalogue

        summary.update(
            {f"erp_{k}": v for k, v in seed_from_catalogue(db).items()}
        )
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


def cmd_demo(args: argparse.Namespace) -> int:
    """Seed, run the whole pipeline, then print the held-out metrics table."""
    from .metrics import compute_metrics

    init_db()
    started = time.time()
    with SessionLocal() as db:
        summary = seed_database(db, profile=args.profile)
        from .erp import seed_from_catalogue

        summary.update({f"erp_{k}": v for k, v in seed_from_catalogue(db).items()})
        _print_table(f"SAMAN seed — {args.profile} profile", summary)

        print("\nRunning pipeline ...")
        status = run_pipeline(db)
        if status.state != "done":
            print(f"!! pipeline {status.state}: {status.error}")
            return 1
        print(f"  stages: {' -> '.join(status.stages_done)}")

        report = compute_metrics(db)

    print_metrics(report)
    print(f"\nTotal: {time.time() - started:.1f}s")
    print("\n  UI   http://localhost:5173     (make dev)")
    print("  API  http://localhost:8000/api/docs")
    print("  Sign in as steward@cpcl.in / demo")
    return 0 if report["gate_passed"] else 1


def print_metrics(report: dict) -> None:
    """The metrics table `make demo` prints. Every number is from held-out."""
    dup = report["duplicate"]["pairwise"]
    bcubed = report["duplicate"]["bcubed"]
    base = report["baseline_exact_text"]["pairwise"]

    print("\n" + "=" * 66)
    print(f"  SAMAN metrics — {report['split']} split (40% of ground truth)")
    print("=" * 66)
    print("  Thresholds tuned on the 60% tuning split only; nothing below was")
    print("  tuned against these numbers.\n")

    print(f"  {'GATE (spec §8 M3)':34} {'value':>9} {'target':>8}   result")
    print("  " + "-" * 62)
    for name, entry in report["gate"].items():
        value = "n/a" if entry["value"] is None else f"{entry['value']:.4f}"
        print(f"  {name.replace('_', ' '):34} {value:>9} {entry['target']:>8.2f}   "
              f"{'PASS' if entry['pass'] else 'FAIL'}")

    print(f"\n  {'DUPLICATE DETECTION':34} {'precision':>9} {'recall':>8} {'F1':>8}")
    print("  " + "-" * 62)
    print(f"  {'pairwise':34} {dup['precision']:>9.4f} {dup['recall']:>8.4f} {dup['f1']:>8.4f}")
    print(f"  {'B-cubed (cluster level)':34} {bcubed['precision']:>9.4f} "
          f"{bcubed['recall']:>8.4f} {bcubed['f1']:>8.4f}")
    print(f"  {'baseline: exact text match':34} {base['precision']:>9.4f} "
          f"{base['recall']:>8.4f} {base['f1']:>8.4f}")

    veto = report["veto"]
    print("\n  VETO LAYER (planted §2A traps, held-out)")
    print("  " + "-" * 62)
    refused = f"{veto['traps_refused']:,} of {veto['traps_total']:,}"
    print(f"  {'traps correctly refused':34} {refused:>16}")
    for kind, counts in veto["by_kind"].items():
        print(f"    {kind:32} {counts['accuracy']:>9.4f}  ({counts['correct']}/{counts['total']})")

    print("\n  PER CLASS (worst first)")
    print("  " + "-" * 62)
    for row in report["per_class"]:
        print(f"  {row['class_code']:34} {row['precision']:>9.4f} {row['recall']:>8.4f} "
              f"{row['f1']:>8.4f}")
    print(f"\n  Worst-performing class: {report['worst_class']}")

    engines = report.get("engines", {})
    if engines:
        print("\n  ACTIVE ENGINES")
        print("  " + "-" * 62)
        for tier, name in engines.items():
            print(f"  {tier:34} {name}")

    auto = report["automation"]
    print(f"\n  {'automation rate':34} {auto['automation_rate']:>9.4f}")
    print(f"  {'pairs needing human review':34} {auto['needs_review']:>9,}")
    candidates = report["blocking"]["stats"].get("candidate_pairs", 0)
    print(f"  {'candidate pairs generated':34} {candidates:>9,}")
    print("=" * 66)


def cmd_tune(_args: argparse.Namespace) -> int:
    from .tuning import report

    with SessionLocal() as db:
        result = report(db)
    print(f"\nThreshold sweep on the {result['split']} split "
          f"(precision floor {result['precision_floor']})")
    print(f"{'T_HIGH':>8} {'precision':>10} {'recall':>8} {'F1':>8} {'clusters':>9}")
    for row in result["sweep"]:
        mark = "  <-- recommended" if row["threshold"] == result["recommended_T_HIGH"] else ""
        print(f"{row['threshold']:>8} {row['precision']:>10.4f} {row['recall']:>8.4f} "
              f"{row['f1']:>8.4f} {row['clusters']:>9,}{mark}")
    print(f"\nRecommended T_HIGH = {result['recommended_T_HIGH']}")
    print(result["note"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="saman", description="SAMAN maintenance commands")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="generate the synthetic catalogue estate")
    seed.add_argument("--profile", choices=sorted(PROFILES), default="demo")
    seed.set_defaults(func=cmd_seed)

    run = sub.add_parser("pipeline", help="run the pipeline over any unprocessed rows")
    run.set_defaults(func=cmd_pipeline)

    demo = sub.add_parser("demo", help="seed, run the pipeline, print metrics")
    demo.add_argument("--profile", choices=sorted(PROFILES), default="demo")
    demo.set_defaults(func=cmd_demo)

    tune = sub.add_parser("tune", help="sweep match thresholds on the tuning split")
    tune.set_defaults(func=cmd_tune)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
