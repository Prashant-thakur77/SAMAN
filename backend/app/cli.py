"""Command-line entry points used by the Makefile.

python -m app.cli seed --profile demo
python -m app.cli pipeline
python -m app.cli evaluate
python -m app.cli report --cpse CPCL [--send] [--out DIR]
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

        summary.update({f"erp_{k}": v for k, v in seed_from_catalogue(db).items()})
    summary["seconds"] = round(time.time() - started, 1)
    _print_table(f"SAMAN seed · {args.profile} profile", summary)
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
        _print_table(f"SAMAN seed · {args.profile} profile", summary)

        print("\nRunning pipeline ...")
        status = run_pipeline(db)
        if status.state != "done":
            print(f"!! pipeline {status.state}: {status.error}")
            return 1
        print(f"  stages: {' -> '.join(status.stages_done)}")

        # A registry with nothing approved has nothing to show. Bring the estate
        # to a realistic mid-flight state: some clusters coded, the rest still
        # in the queue where a reviewer can work them.
        from .seed import seed_registry_activity

        _print_table("Registry activity", seed_registry_activity(db))

        from .seed import seed_smart_create_activity

        _print_table("Smart-Create activity", seed_smart_create_activity(db))

        # The learned model needs labels; stand in for reviewers on the tuning
        # split so the demo can show a trained model and its held-out score.
        from . import learn

        _print_table(
            "Simulated reviewer labels (tuning split only)", learn.simulate_labels(db, 400)
        )
        try:
            model = learn.train(db)
            _print_table("Learned pairwise model", _learn_summary(model))
        except learn.NotEnoughLabels as exc:
            print(f"  learned model: {exc}")

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
        print(
            f"  {name.replace('_', ' '):34} {value:>9} {entry['target']:>8.2f}   "
            f"{'PASS' if entry['pass'] else 'FAIL'}"
        )

    print(f"\n  {'DUPLICATE DETECTION':34} {'precision':>9} {'recall':>8} {'F1':>8}")
    print("  " + "-" * 62)
    print(f"  {'pairwise':34} {dup['precision']:>9.4f} {dup['recall']:>8.4f} {dup['f1']:>8.4f}")
    print(
        f"  {'B-cubed (cluster level)':34} {bcubed['precision']:>9.4f} "
        f"{bcubed['recall']:>8.4f} {bcubed['f1']:>8.4f}"
    )
    print(
        f"  {'baseline: exact text match':34} {base['precision']:>9.4f} "
        f"{base['recall']:>8.4f} {base['f1']:>8.4f}"
    )

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
        print(
            f"  {row['class_code']:34} {row['precision']:>9.4f} {row['recall']:>8.4f} "
            f"{row['f1']:>8.4f}"
        )
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


def _learn_summary(model) -> dict:
    return {
        "labels": model.n_labels,
        "by_source": ", ".join(f"{k} {v}" for k, v in sorted(model.labels.items())),
        "cv_auc": model.cv.get("auc"),
        "holdout_pairs": (model.holdout or {}).get("pairs"),
        "holdout_model_auc": (model.holdout or {}).get("model_auc"),
        "holdout_pipeline_auc": (model.holdout or {}).get("pipeline_auc"),
        "grey_model_auc": (model.holdout or {}).get("grey_model_auc"),
        "history": str(__import__("app.learn", fromlist=["history_path"]).history_path()),
        "saved_to": str(__import__("app.learn", fromlist=["model_path"]).model_path()),
    }


def cmd_learn(_args: argparse.Namespace) -> int:
    """Train the pairwise model on every label in the Workbench."""
    from . import learn

    init_db()
    with SessionLocal() as db:
        try:
            model = learn.train(db)
        except learn.NotEnoughLabels as exc:
            print(f"!! {exc}")
            return 1
        _print_table("Learned pairwise model", _learn_summary(model))
        _print_table("Weights (standardised)", model.weights())
        suggestions = learn.suggest_thresholds(db)
        _print_table(
            "Threshold suggestions (suggested, not applied)",
            {
                row["class_code"]: (
                    f"T_HIGH {row['suggested_t_high']} (precision {row['suggested_precision']}, "
                    f"F1 {row['suggested_f1']}) vs current {row['current_t_high']} "
                    f"(precision {row['current_precision']}) on {row['labelled_pairs']} labels"
                )
                for row in suggestions["classes"]
            }
            or {"note": f"no class has {suggestions['min_labels']} labels with both answers yet"},
        )
    return 0


def cmd_llm_eval(args: argparse.Namespace) -> int:
    """Measure the configured language model on the project's own questions.

    Sixteen questions with the words a correct answer must contain
    (`app/data/llm_eval.yaml`). For each: did the guards accept the answer,
    were the expected words present, how long did it take. The same harness
    runs against the 3B local model, a 7B, or the remote endpoint, which is
    how a model earns its place here rather than by reputation.
    """
    import yaml

    from . import knowledge, llm
    from .config import REPO_ROOT

    cases = yaml.safe_load((REPO_ROOT / "backend" / "app" / "data" / "llm_eval.yaml").read_text())
    if getattr(args, "from_log", False):
        cases = _cases_from_log(args.limit)
        if not cases:
            print(f"no questions in the answer log ({knowledge.answer_log_path()})")
            return 1
        print(f"{len(cases)} distinct questions people asked, from the answer log")
    if not llm.available():
        print(f"no model answers ({llm.engine_label()}); nothing to measure")
        return 1
    print(f"model: {llm.engine_label()}\n")
    print(f"  {'outcome':10} {'correct':8} {'seconds':>7}  question")
    print("  " + "-" * 70)
    accepted = correct = 0
    total_seconds = 0.0
    knowledge.forget_answers()
    for case in cases:
        started = time.time()
        result = knowledge.answer(case["question"])
        seconds = time.time() - started
        total_seconds += seconds
        if result is not None and not result.refused and result.text:
            outcome = "accepted"
            accepted += 1
            text = result.text.lower()
            # A question from the log carries no expected words: acceptance and
            # latency are what it measures, and it counts as correct.
            ok = (
                any(str(word).lower() in text for word in case["expect"])
                if case.get("expect")
                else True
            )
            correct += int(ok)
        else:
            outcome = "declined" if result is None else "refused"
            ok = False
        print(f"  {outcome:10} {'yes' if ok else 'no':8} {seconds:7.1f}  {case['question'][:52]}")
        if result is not None and result.refused and result.note:
            print(f"             {result.note[:110]}")
        elif args.verbose and result is not None and result.text:
            print(f"             {result.text[:160]}")
    n = len(cases)
    print(
        f"\n  accepted {accepted}/{n}  correct {correct}/{n}  "
        f"mean {total_seconds / n:.1f}s per question"
    )
    print("  (correct = an accepted answer that contains one of the expected words)")
    return 0


def _cases_from_log(limit: int) -> list[dict]:
    """The most recent distinct questions in the answer log, newest first.

    A test set written by the people who asked. They carry no expected words,
    so the harness reports acceptance and latency for them; a maintainer who
    finds a good one moves it into `llm_eval.yaml` with the words it should
    contain.
    """
    import json

    from . import knowledge

    path = knowledge.answer_log_path()
    if path is None or not path.exists():
        return []
    seen: dict[str, None] = {}
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            question = str(json.loads(line).get("question") or "").strip()
        except ValueError:
            continue
        if question and question not in seen:
            seen[question] = None
        if len(seen) >= limit:
            break
    return [{"question": q, "expect": []} for q in seen]


def cmd_evaluate(_args: argparse.Namespace) -> int:
    """Score the latest run on held-out truth and record it on that run.

    What a fresh `make demo` does at the end of its pipeline, for a database
    that already exists: the executive dashboard reads the recorded snapshot
    rather than computing it per request, so a database from before the
    snapshot existed shows an empty scorecard until this has run.
    """
    from .metrics import record_evaluation

    init_db()
    started = time.time()
    with SessionLocal() as db:
        snapshot = record_evaluation(db)
    if snapshot is None:
        print("!! no match run to evaluate; run `make pipeline` first")
        return 1
    print_metrics(snapshot)
    print(
        f"\nRecorded on the latest match run at {snapshot['computed_at']} "
        f"({round(time.time() - started, 1)}s)."
    )
    return 0


def cmd_autoissue(args: argparse.Namespace) -> int:
    """Issue codes under the families' policies (dry run unless --apply).

    What a nightly cron line runs after `pipeline`: the gates are the ones the
    admin page states, and nothing issues for a family whose policy is off.
    """
    from . import autoissue

    init_db()
    with SessionLocal() as db:
        result = autoissue.run(db, dry_run=not args.apply, limit=args.limit, family=args.family)
    verb = "would issue" if result["dry_run"] else "issued"
    print(f"{verb} {len(result['issued'])} code(s); {result['eligible']} eligible")
    for row in result["issued"][:20]:
        code = row["code"] or "(dry run)"
        text = row["std_description"][:50]
        print(f"  {code:20} cluster {row['cluster_id']:6} {row['family']}  {text}")
    if len(result["issued"]) > 20:
        print(f"  … and {len(result['issued']) - 20} more")
    for row in result["skipped"]:
        print(f"  skipped cluster {row['cluster_id']}: {row['reason']}")
    if result["not_eligible"]:
        print("held back:")
        for reason, n in sorted(result["not_eligible"].items(), key=lambda kv: -kv[1]):
            print(f"  {n:6}  {reason}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Write each CPSE's catalogue report as HTML and JSON, and optionally
    deliver it (SMTP when configured, the outbox otherwise). What a weekly
    cron line runs; see README "A report for each CPSE"."""
    import json
    from pathlib import Path

    from sqlalchemy import select

    from . import reports
    from .models import Cpse

    if not args.cpse and not args.all:
        print("!! name a CPSE with --cpse CODE, or pass --all")
        return 2
    init_db()
    out = Path(args.out) if args.out else reports.outbox_dir()
    out.mkdir(parents=True, exist_ok=True)
    failures = 0
    with SessionLocal() as db:
        codes = (
            [c for c in db.execute(select(Cpse.code).order_by(Cpse.code)).scalars()]
            if args.all
            else [args.cpse.upper()]
        )
        for code in codes:
            try:
                report = reports.cpse_report(db, code)
            except LookupError as exc:
                print(f"!! {exc}")
                failures += 1
                continue
            html = reports.render_html(report)
            stem = f"saman-report-{code}-{report['period']['to']}"
            (out / f"{stem}.html").write_text(html, encoding="utf-8")
            (out / f"{stem}.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
            )
            line = f"  {code:6} {out / stem}.html  actions {len(report['actions'])}"
            if args.send:
                to = (
                    [args.to]
                    if args.to
                    else (
                        [report["cpse"]["contact_email"]] if report["cpse"]["contact_email"] else []
                    )
                )
                if not to:
                    line += (
                        "  not sent: no contact email (set one under Administration or pass --to)"
                    )
                    failures += 1
                else:
                    try:
                        result = reports.deliver(report, html, to, db=db, user="cli")
                    except OSError as exc:
                        line += f"  not sent: {exc}"
                        failures += 1
                    else:
                        where = result["path"] if result["mode"] == "outbox" else result["host"]
                        line += f"  sent ({result['mode']}) -> {', '.join(to)} via {where}"
            print(line)
    return 1 if failures else 0


def cmd_simulate_reviews(args: argparse.Namespace) -> int:
    """Label tuning-split pairs from ground truth, as simulated reviewers."""
    from . import learn

    init_db()
    with SessionLocal() as db:
        _print_table("Simulated reviewer labels", learn.simulate_labels(db, args.n))
    return 0


def cmd_tune(_args: argparse.Namespace) -> int:
    from .tuning import report

    with SessionLocal() as db:
        result = report(db)
    print(
        f"\nThreshold sweep on the {result['split']} split "
        f"(precision floor {result['precision_floor']})"
    )
    print(f"{'T_HIGH':>8} {'precision':>10} {'recall':>8} {'F1':>8} {'clusters':>9}")
    for row in result["sweep"]:
        mark = "  <-- recommended" if row["threshold"] == result["recommended_T_HIGH"] else ""
        print(
            f"{row['threshold']:>8} {row['precision']:>10.4f} {row['recall']:>8.4f} "
            f"{row['f1']:>8.4f} {row['clusters']:>9,}{mark}"
        )
    print(f"\nRecommended T_HIGH = {result['recommended_T_HIGH']}")
    print(result["note"])
    return 0


def cmd_snapshot(_args: argparse.Namespace) -> int:
    from .snapshot import capture, snapshot_dir

    result = capture()
    print(f"snapshot -> {snapshot_dir()}")
    for name in result.files:
        print(f"  {name}")
    print(f"{result.bytes_written / 1_048_576:.0f} MB in {result.seconds:.2f}s")
    print("Restore any time with `make demo-restore`.")
    return 0


def cmd_restore(_args: argparse.Namespace) -> int:
    from .snapshot import restore, snapshot_dir

    try:
        result = restore()
    except FileNotFoundError as exc:
        print(exc)
        return 1
    print(f"restored from {snapshot_dir()}")
    for name in result.files:
        print(f"  {name}")
    print(f"{result.bytes_written / 1_048_576:.0f} MB in {result.seconds:.2f}s")
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

    learn_cmd = sub.add_parser("learn", help="train the pairwise model on Workbench labels")
    learn_cmd.set_defaults(func=cmd_learn)

    evaluate = sub.add_parser(
        "evaluate", help="score the latest run on held-out truth and record it on the run"
    )
    evaluate.set_defaults(func=cmd_evaluate)

    llm_eval = sub.add_parser(
        "llm-eval", help="measure the configured language model on the project's own questions"
    )
    llm_eval.add_argument("--verbose", action="store_true", help="print each answer")
    llm_eval.add_argument(
        "--from-log",
        action="store_true",
        help="ask the questions people actually asked (the answer log) instead of the fixed set",
    )
    llm_eval.add_argument("--limit", type=int, default=30, help="how many log questions (newest)")
    llm_eval.set_defaults(func=cmd_llm_eval)

    report = sub.add_parser(
        "report", help="write a CPSE's catalogue report (HTML + JSON) and optionally send it"
    )
    report.add_argument("--cpse", help="CPSE code, e.g. CPCL")
    report.add_argument("--all", action="store_true", help="every registered CPSE")
    report.add_argument(
        "--send", action="store_true", help="deliver by SMTP when configured, else to the outbox"
    )
    report.add_argument("--to", help="recipient instead of the CPSE's contact email")
    report.add_argument("--out", help="directory for the files (default: the outbox)")
    report.set_defaults(func=cmd_report)

    auto = sub.add_parser(
        "autoissue", help="issue codes under the families' policies (dry run unless --apply)"
    )
    auto.add_argument("--apply", action="store_true", help="issue rather than list")
    auto.add_argument("--family", help="one family only, e.g. BRNG")
    auto.add_argument("--limit", type=int, default=500)
    auto.set_defaults(func=cmd_autoissue)

    simulate = sub.add_parser(
        "simulate-reviews", help="label tuning-split pairs from ground truth (demo only)"
    )
    simulate.add_argument("--n", type=int, default=400)
    simulate.set_defaults(func=cmd_simulate_reviews)

    tune = sub.add_parser("tune", help="sweep match thresholds on the tuning split")
    tune.set_defaults(func=cmd_tune)

    snap = sub.add_parser("snapshot", help="capture the databases as a restore point")
    snap.set_defaults(func=cmd_snapshot)

    restore = sub.add_parser("restore", help="restore the databases from the snapshot")
    restore.set_defaults(func=cmd_restore)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
