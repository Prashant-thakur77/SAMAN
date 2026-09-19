"""The five demo moves, driven through the built UI in a real browser.

Run via ``make e2e`` with the app up (``make dev`` or ``make preview``). Each
move is what the presenter does on stage, in order; a regression in any of
them is caught here before a judge sees it. The checks read what the screen
says, not the API, so a page that loads its data and then fails to render it
still fails.

Requires the optional tooling::

    uv pip install --python backend/.venv/bin/python playwright

The Chromium build is looked for under ``~/.cache/ms-playwright``; pass
``--chromium`` to point elsewhere, or install one with ``playwright install
chromium``.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _chromium() -> str | None:
    hits = sorted(
        glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
    )
    return hits[-1] if hits else None


def sign_in(page, base: str, role: str, password: str) -> None:
    page.goto(f"{base}/login", wait_until="networkidle")
    page.click(f"li:has-text('{role}') button")
    page.fill("input[type=password]", password)
    page.click("button[type=submit]")
    page.wait_for_url(f"{base}/", timeout=20_000)


def move_1_search(page, base: str) -> str:
    """The same bearing under several names; open one row's cluster."""
    page.goto(f"{base}/search?q=6205", wait_until="networkidle")
    page.wait_for_selector("tbody tr", timeout=20_000)
    matches = page.inner_text("text=/matches/")
    count = int(re.sub(r"[^\d]", "", matches.split(" match")[0]) or 0)
    assert count >= 4, f"expected several 6205 rows, saw {matches!r}"
    cpses = {c.strip() for c in page.locator("tbody tr td:nth-child(2)").all_inner_texts()}
    assert len(cpses) >= 2, f"6205 should appear in more than one CPSE, saw {cpses}"
    page.click("tbody tr:first-child td:nth-child(2)")
    page.wait_for_selector("[role=dialog]", timeout=15_000)
    return f"{count} rows across {len(cpses)} CPSEs; the drawer opened"


def move_2_workbench(page, base: str) -> str:
    """A grey card with its why; approve with A, take it back with U."""
    page.goto(f"{base}/workbench", wait_until="networkidle")
    page.wait_for_selector("text=Attribute comparison", timeout=30_000)
    why = page.inner_text("article header")
    assert "why" in why.lower() or "recommendation" in page.inner_text("article").lower()
    # Labels render in small caps; read them case-insensitively.
    task = re.search(r"task (\d+)", page.inner_text("article header"), re.I).group(1)
    page.keyboard.press("a")
    page.wait_for_selector(f"text=Task {task} approved.", timeout=15_000)
    page.keyboard.press("u")
    page.wait_for_function("() => !document.body.innerText.includes('approved.')", timeout=15_000)
    header = page.inner_text("article header")
    assert f"task {task}" in header.lower(), "the undone card should be back in front"
    return f"task {task} approved and taken back"


def move_3_smart_create(page, base: str) -> str:
    """A house-style description with a Hindi token resolves to a coded material."""
    page.goto(f"{base}/smart-create", wait_until="networkidle")
    page.fill("#sc-description", "वाल्व GATE 32NB CL 300 CS FLGD 51.1 BAR KITZ")
    page.click("button:has-text('Check before creating')")
    page.wait_for_selector("text=Already in the catalogue", timeout=60_000)
    body = page.inner_text("main")
    assert "This material already exists" in body or "A possible match" in body, body[:300]
    assert re.search(r"\b\d{2,3}\.\d%", body), "a confidence should be shown"
    return "an existing material was found for the Hindi-tokened description"


def move_4_dashboards(page, base: str) -> str:
    """Executive figures with provenance; a tile opens its rows; Opportunity loads."""
    page.goto(f"{base}/dashboard/executive", wait_until="networkidle")
    page.wait_for_selector("text=audit #", timeout=60_000)
    text = page.inner_text("main").lower()
    assert "synthetic" in text, "the page must say the estate is synthetic"
    assert "progress by cpse" in text
    page.click("text=The coded rows")
    page.wait_for_url("**/search?cnmc=yes", timeout=15_000)
    page.goto(f"{base}/dashboard/opportunity", wait_until="networkidle")
    page.wait_for_selector("text=Savings identified", timeout=60_000)
    assert "Assumes" in page.inner_text("main") or "assum" in page.inner_text("main").lower()
    return "executive provenance shown, a tile opened its rows, opportunity states its assumption"


def move_5_audit_admin(page, base: str) -> str:
    """The chain verifies; Admin says what runs where."""
    page.goto(f"{base}/audit", wait_until="networkidle")
    page.wait_for_selector("tbody tr", timeout=30_000)
    verify = page.locator("button:has-text('Verify')")
    if verify.count():
        verify.first.click()
        page.wait_for_timeout(1_500)
        assert (
            "intact" in page.inner_text("main").lower()
            or "verified" in page.inner_text("main").lower()
        )
    page.goto(f"{base}/admin", wait_until="networkidle")
    page.wait_for_selector("text=What runs where", timeout=30_000)
    text = page.inner_text("main").lower()
    assert "local" in text and "browser" in text
    assert "automatic issue" in text
    return "ledger verified, engines and policy shown"


MOVES = [
    ("1 · search", move_1_search),
    ("2 · workbench", move_2_workbench),
    ("3 · smart-create", move_3_smart_create),
    ("4 · dashboards", move_4_dashboards),
    ("5 · audit + admin", move_5_audit_admin),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--role", default="registrar")
    parser.add_argument("--password", default="demo")
    parser.add_argument("--chromium", default=_chromium())
    parser.add_argument("--shots", help="directory for a screenshot after each move")
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed — see the module docstring.")
        return 1

    failures = 0
    with sync_playwright() as p:
        browser = (
            p.chromium.launch(executable_path=args.chromium)
            if args.chromium
            else p.chromium.launch()
        )
        page = browser.new_context(viewport={"width": 1366, "height": 900}).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        sign_in(page, args.base_url, args.role, args.password)
        for name, move in MOVES:
            started = time.perf_counter()
            try:
                note = move(page, args.base_url)
                print(f"  ok   {name:20} {time.perf_counter() - started:5.1f}s  {note}")
            except Exception as exc:  # report every move, then fail
                failures += 1
                took = time.perf_counter() - started
                print(f"  FAIL {name:20} {took:5.1f}s  {type(exc).__name__}: {str(exc)[:160]}")
            if args.shots:
                Path(args.shots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(args.shots) / f"{name[0]}.png"))
        if errors:
            print(f"  page errors: {len(errors)} (first: {errors[0][:160]})")
        browser.close()
    print(f"\n{len(MOVES) - failures}/{len(MOVES)} demo moves pass")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
