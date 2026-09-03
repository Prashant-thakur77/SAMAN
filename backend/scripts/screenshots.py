"""Regenerate the README screenshots from the running application (spec §8).

Run via ``make screenshots``. The point of scripting this rather than cropping
by hand is that the images cannot drift: every one is the built bundle, served
by `vite preview`, talking to a real API over the demo database, driven through
a real sign-in. If a screen breaks, the screenshot breaks with it.

Requires the optional documentation tooling::

    uv pip install --python backend/.venv/bin/python playwright
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "docs" / "screenshots"

@dataclass
class Shot:
    """One screenshot, and whatever it takes to make the screen worth looking at.

    An empty form photographs badly and says nothing about the feature, so the
    screens that need input get driven first — a real query typed into
    Smart-Create, a real dry run on the migration screen.
    """

    name: str
    path: str
    marker: str
    theme: str = "light"
    #: Steps run after the page settles and before the shutter.
    setup: Callable[[Any], None] | None = None
    settle_ms: int = 1_200


#: A gate valve in a house style that appears nowhere in the catalogue --
#: abbreviated, reordered, with a Hindi token -- which still resolves to the
#: right material. It shows the three answers at once: the existing record, a
#: different manufacturer's equivalent, and the near-misses the veto refused.
SMART_CREATE_PROBE = "वाल्व GATE 32NB CL 300 CS FLGD 51.1 BAR KITZ"


def _open_drawer(page) -> None:
    """Open the item drawer over the results — the §6.3 behaviour a still image
    of a table cannot otherwise show."""
    # The first cell holds a link that stops propagation, so click a plain cell.
    page.click("tbody tr:first-child td:nth-child(2)")
    page.wait_for_selector("[role=dialog]", timeout=15_000)


#: A rendered valve nameplate, used for the camera screenshot. Drawn rather
#: than photographed so the image is reproducible; the reader treats it the same
#: either way.
NAMEPLATE = REPO / "docs" / "fixtures" / "nameplate.png"


def _scan_nameplate(page) -> None:
    """Drive the camera input with a nameplate image (§5).

    A file input with `capture` opens the camera on a phone and a file picker on
    a laptop; Playwright sets the file directly, which is the same code path.
    """
    page.set_input_files("input[type=file]", str(NAMEPLATE))
    page.wait_for_selector("text=What the reader saw", timeout=30_000)


def _smart_create(page) -> None:
    page.fill("#sc-description", SMART_CREATE_PROBE)
    page.fill("#sc-uom", "NOS")
    page.click("button:has-text('Check before creating')")
    page.wait_for_selector("text=Already in the catalogue", timeout=20_000)


def _migration_dry_run(page) -> None:
    page.click("button:has-text('Run a dry run')")
    page.wait_for_selector("text=Safe to apply", timeout=30_000)


def _restricted_mode(page) -> None:
    page.click("button:has-text('Compare')")
    page.wait_for_selector("text=What actually crossed the wire", timeout=90_000)


def _assistant(page) -> None:
    """Open the floating assistant and ask it something it explains rather
    than performs, so the panel is photographed with an answer in it."""
    page.click("button[aria-label='Ask SAMAN']")
    page.fill("input[aria-label='Ask the assistant']", "What is a CNMC?")
    page.keyboard.press("Enter")
    page.wait_for_selector("text=Damm check digit", timeout=20_000)


def _copilot(page) -> None:
    # Typed rather than filled: `fill` sets the DOM value directly, which leaves
    # a React-controlled input showing text the component has already cleared.
    # Driving it as keystrokes photographs the state a person would actually see.
    field = page.locator("input[placeholder*='overpays']")
    field.click()
    field.press_sequentially("Which CPSE overpays for gaskets?", delay=8)
    page.keyboard.press("Enter")
    # The answer types itself in; wait for the citations rather than a guess.
    page.wait_for_selector("text=/cite|source|evidence|query/i", timeout=25_000)


#: Ordered as the README tells the story, not as the router lists them.
SHOTS: list[Shot] = [
    Shot("home", "/", "text=Overview"),
    Shot("search", "/search?q=6205", "text=Search", setup=_open_drawer, settle_ms=900),
    # A coded item with purchase history, so the page shows the whole story:
    # golden record, CNMC, every CPSE's legacy code, evidence, price trend.
    Shot("item", "/items/6", "text=Golden record", settle_ms=1_600),
    Shot("workbench", "/workbench", "text=Review", theme="dark"),
    Shot("substitutes", "/substitutes", "text=Substitutes", settle_ms=900),
    # A five-member cluster that already carries a code, so the page shows the
    # golden record, every member and the split/merge controls together.
    Shot("cluster", "/clusters/268", "text=Field provenance", theme="dark"),
    Shot("executive", "/dashboard/executive", "text=Analytics"),
    Shot("opportunity", "/dashboard/opportunity", "text=Analytics", theme="dark"),
    Shot("smart-create", "/smart-create", "text=Smart-Create", setup=_smart_create),
    Shot(
        "scan",
        "/smart-create",
        "text=Smart-Create",
        setup=_scan_nameplate,
        settle_ms=1_200,
    ),
    Shot("migration", "/migration", "text=ERP migration", setup=_migration_dry_run),
    Shot(
        "restricted-mode",
        "/pprl",
        "text=Restricted mode",
        setup=_restricted_mode,
        # The measured-cost block lands after the overlap does; catching the
        # page between the two makes it look half-built.
        settle_ms=4_000,
    ),
    Shot("copilot", "/copilot", "text=Copilot", theme="dark", setup=_copilot),
    Shot("assistant", "/workbench", "text=Review", setup=_assistant, settle_ms=900),
    Shot("onboard", "/onboard", "text=Onboard a CPSE"),
    Shot("audit", "/audit", "text=Governance"),
    Shot("admin", "/admin", "text=Engine health"),
]

VIEWPORT = {"width": 1440, "height": 960}


def capture(base_url: str, role: str, password: str) -> int:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(__doc__.strip().splitlines()[-1])
        print("playwright is not installed — see the module docstring.")
        return 1

    OUTPUT.mkdir(parents=True, exist_ok=True)
    written, failed = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
        page = context.new_page()

        # The public front page comes first, because it is what a visitor meets
        # first. Framed like every other shot rather than full-page, so the
        # gallery stays a grid.
        page.goto(f"{base_url}/welcome", wait_until="networkidle")
        page.wait_for_selector("text=One Nation, One Material Code", timeout=15_000)
        page.wait_for_timeout(1_500)
        page.screenshot(path=str(OUTPUT / "landing.png"), full_page=False)
        written.append("landing.png")
        print(f"  {(OUTPUT / 'landing.png').relative_to(REPO)}  (light)")

        # /login is a picker over the seeded accounts, not an email field:
        # choose the role, then sign in.
        page.goto(f"{base_url}/login", wait_until="networkidle")
        # The sign-in screen is the first thing anyone sees, so it is captured
        # before the sign-in rather than left out of the gallery.
        page.wait_for_selector("text=One Nation", timeout=15_000)
        page.wait_for_timeout(2_000)
        page.screenshot(path=str(OUTPUT / "login.png"), full_page=False)
        written.append("login.png")
        print(f"  {(OUTPUT / 'login.png').relative_to(REPO)}  (light)")

        page.click(f"li:has-text('{role}') button")
        page.fill("input[type=password]", password)
        page.click("button[type=submit]")
        page.wait_for_url(f"{base_url}/", timeout=15_000)

        for shot in SHOTS:
            try:
                _set_theme(page, shot.theme)
                page.goto(f"{base_url}{shot.path}", wait_until="networkidle")
                page.wait_for_selector(shot.marker, timeout=15_000)
                if shot.setup:
                    shot.setup(page)
                # Charts draw in and KPIs count up; catching them mid-animation
                # makes the platform look broken in a still image.
                page.wait_for_timeout(shot.settle_ms)
                destination = OUTPUT / f"{shot.name}.png"
                page.screenshot(path=str(destination), full_page=False)
                written.append(destination.name)
                print(f"  {destination.relative_to(REPO)}  ({shot.theme})")
            except PlaywrightTimeout as exc:
                failed.append(f"{shot.name} ({shot.path})")
                print(f"  !! {shot.name}: {str(exc).splitlines()[0]}")

        browser.close()

    print(f"\n{len(written)} screenshots in {OUTPUT.relative_to(REPO)}")
    if failed:
        print("failed: " + ", ".join(failed))
        return 1
    return 0


def _set_theme(page, theme: str) -> None:
    """Set the stored theme before navigation, so no frame renders the other one."""
    page.add_init_script(
        f"try {{ localStorage.setItem('saman.theme', '{theme}') }} catch (e) {{}}"
    )
    page.evaluate(
        f"try {{ localStorage.setItem('saman.theme', '{theme}') }} catch (e) {{}}"
    )


def wait_for(base_url: str, seconds: int = 60) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:4173")
    parser.add_argument("--role", default="registrar")
    parser.add_argument("--password", default="demo")
    args = parser.parse_args()

    if not wait_for(args.base_url):
        print(f"nothing serving {args.base_url} — start `make dev` or `make preview` first")
        return 1
    return capture(args.base_url, args.role, args.password)


if __name__ == "__main__":
    sys.exit(main())
