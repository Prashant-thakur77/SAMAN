"""Regenerate THIRD_PARTY_LICENSES.md and fail the build on GPL/AGPL (spec §8).

Run via ``make licenses``. Two questions are being answered, and they are not
the same question:

1. Is every dependency SAMAN *requires* permissively licensed? A GPL or AGPL
   package here is a build failure, because it would place a copyleft
   obligation on the platform itself.
2. What does each optional accelerator drag in? An optional accelerator lives
   behind ``make deps-optional`` and is not what the demo runs, so a copyleft
   package there is reported loudly and named rather than silently tolerated --
   an operator choosing to install it deserves to be told what it costs them.

The inventory comes from ``pip-licenses`` and ``license-checker``, the two
tools §8 names. Both are already installed, so this runs offline like
everything else.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
FRONTEND = REPO / "frontend"
OUTPUT = REPO / "THIRD_PARTY_LICENSES.md"

#: Copyleft that SAMAN will not take on. LGPL and MPL are handled separately:
#: they are file- or library-scoped and do not reach across a process boundary,
#: so they are reported rather than fatal.
FORBIDDEN = re.compile(r"\bA?GPL\b|GNU GENERAL PUBLIC|GNU AFFERO", re.I)
LGPL = re.compile(r"\bLGPL\b|LESSER GENERAL PUBLIC", re.I)
WEAK_COPYLEFT = re.compile(r"\bMPL\b|MOZILLA PUBLIC|\bEPL\b|ECLIPSE PUBLIC|\bCDDL\b", re.I)

#: pip-licenses reads the (deprecated) License field and its classifiers, and
#: reports UNKNOWN for a package that declares only a modern SPDX expression.
#: That is a gap in the tool, not a licensing problem, so resolve it directly.
UNKNOWN = {"UNKNOWN", "", "NONE"}


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _direct(requirements: Path) -> dict[str, set[str]]:
    """Declared packages mapped to the extras requested for each.

    ``uvicorn[standard]`` matters: its extras pull in uvloop, httptools,
    watchfiles and websockets, and a walk that ignored extras would report all
    four as undeclared strays.
    """
    declared: dict[str, set[str]] = {}
    for line in requirements.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.match(r"^([A-Za-z0-9._-]+)(?:\[([^\]]*)\])?", line)
        if not match:
            continue
        extras = {e.strip() for e in (match.group(2) or "").split(",") if e.strip()}
        declared.setdefault(_normalise(match.group(1)), set()).update(extras)
    return declared


def _wanted(requirement: str, extras: set[str]) -> bool:
    """Is this requirement installed, given the extras that were requested?"""
    gates = re.findall(r"""extra\s*==\s*["']([^"']+)["']""", requirement)
    return not gates or bool(extras & set(gates))


def _closure(roots: dict[str, set[str]]) -> set[str]:
    """Everything reachable from `roots`, honouring the extras each requested."""
    seen: set[str] = set()
    queue = [(name, extras) for name, extras in roots.items()]
    while queue:
        raw, extras = queue.pop()
        name = _normalise(raw)
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = md.distribution(name).requires or []
        except md.PackageNotFoundError:
            continue
        for requirement in requires:
            if not _wanted(requirement, extras):
                continue
            match = re.match(r"^([A-Za-z0-9._-]+)(?:\[([^\]]*)\])?", requirement.strip())
            if not match:
                continue
            child_extras = {e.strip() for e in (match.group(2) or "").split(",") if e.strip()}
            queue.append((match.group(1), child_extras))
    return seen


def _in_this_environment() -> set[str]:
    """Distributions actually installed in this virtualenv.

    ``pip-licenses`` walks the whole of ``sys.path``, which on a developer
    machine can include a checkout of something entirely unrelated. Anything
    outside the venv is not a SAMAN dependency and must not appear in the
    inventory as one.
    """
    prefix = Path(sys.prefix).resolve()
    inside: set[str] = set()
    for dist in md.distributions():
        location = getattr(dist, "_path", None)
        try:
            if location and prefix in Path(location).resolve().parents:
                inside.add(_normalise(dist.metadata["Name"] or ""))
        except (OSError, RuntimeError):
            continue
    return inside


def _resolve_license(name: str, reported: str) -> str:
    """Fill in a license pip-licenses could not read, from the metadata itself."""
    if reported.upper() not in UNKNOWN:
        return reported
    try:
        meta = md.metadata(name)
    except md.PackageNotFoundError:
        return reported
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(dict.fromkeys(classifiers))
    declared = (meta.get("License") or "").strip()
    if declared and "\n" not in declared and len(declared) < 60:
        return declared
    return "see package metadata"


def python_packages() -> list[dict]:
    raw = subprocess.run(
        [sys.executable, "-m", "piplicenses", "--format=json", "--with-urls"],
        capture_output=True, text=True, check=True, cwd=BACKEND,
    ).stdout
    required_direct = _direct(BACKEND / "requirements.txt")
    optional_direct = _direct(BACKEND / "requirements-optional.txt")
    required = _closure(required_direct)
    optional = _closure(optional_direct) - required
    installed_here = _in_this_environment()

    packages = []
    for entry in json.loads(raw):
        name = entry["Name"]
        key = _normalise(name)
        if key not in installed_here:
            continue
        if key in required:
            scope = "required"
        elif key in optional:
            scope = "optional"
        else:
            # Installed but reachable from neither list: a stray or a tool
            # someone added by hand. Reported so it cannot hide.
            scope = "unlisted"
        packages.append(
            {
                "name": name,
                "version": entry["Version"],
                "license": _resolve_license(name, entry["License"]),
                "url": entry.get("URL") or "",
                "scope": scope,
                "direct": key in required_direct or key in optional_direct,
            }
        )
    return sorted(packages, key=lambda p: p["name"].lower())


def node_packages() -> list[dict]:
    def run(production: bool) -> dict:
        command = ["npx", "--no-install", "license-checker", "--json"]
        if production:
            command.append("--production")
        result = subprocess.run(command, capture_output=True, text=True, cwd=FRONTEND)
        if result.returncode != 0:
            raise SystemExit(f"license-checker failed:\n{result.stderr[-2000:]}")
        return json.loads(result.stdout)

    shipped = run(production=True)
    everything = run(production=False)

    packages = []
    for identifier, entry in everything.items():
        name, _, version = identifier.rpartition("@")
        packages.append(
            {
                "name": name,
                "version": version,
                "license": str(entry.get("licenses") or "UNKNOWN"),
                "url": entry.get("repository") or "",
                "scope": "required" if identifier in shipped else "build-only",
            }
        )
    return sorted(packages, key=lambda p: p["name"].lower())


def classify(license_text: str) -> str:
    if FORBIDDEN.search(license_text) and not LGPL.search(license_text):
        return "forbidden"
    if LGPL.search(license_text):
        return "lgpl"
    if WEAK_COPYLEFT.search(license_text):
        return "weak-copyleft"
    return "permissive"


def _table(packages: list[dict]) -> str:
    lines = ["| Package | Version | License |", "|---|---|---|"]
    for package in packages:
        name = (
            f"[{package['name']}]({package['url']})" if package["url"] else package["name"]
        )
        lines.append(f"| {name} | `{package['version']}` | {package['license']} |")
    return "\n".join(lines)


def render(python: list[dict], node: list[dict]) -> str:
    def group(packages, scope):
        return [p for p in packages if p["scope"] == scope]

    counts: dict[str, int] = defaultdict(int)
    for package in python + node:
        counts[classify(package["license"])] += 1

    optional = group(python, "optional")
    copyleft_optional = [p for p in optional if classify(p["license"]) != "permissive"]

    parts = [
        "# Third-party licenses",
        "",
        "Generated by `make licenses` from `pip-licenses` and `license-checker`.",
        "Do not edit by hand — the file is regenerated and the build fails if any",
        "**required** dependency is GPL or AGPL licensed (spec §8).",
        "",
        f"- {len(python)} Python packages, {len(node)} npm packages",
        f"- {counts['permissive']} permissive, {counts['weak-copyleft']} weak copyleft, "
        f"{counts['lgpl']} LGPL, {counts['forbidden']} GPL/AGPL",
        "",
        "SAMAN itself is MIT licensed.",
        "",
    ]

    if copyleft_optional:
        parts += [
            "## ⚠ Copyleft in an optional accelerator",
            "",
            "These are **not installed by `make deps`** and are not what the demo runs.",
            "They arrive only with `make deps-optional`, and an operator who installs",
            "them takes on the obligation named here.",
            "",
            _table(copyleft_optional),
            "",
        ]

    parts += [
        "## Python — required",
        "",
        "Everything `make deps` installs, including transitive dependencies.",
        "",
        _table(group(python, "required")),
        "",
        "## Python — optional accelerators",
        "",
        "Installed only by `make deps-optional`. SAMAN runs fully without them and",
        "reports the active engine at `GET /api/health` (spec §0.4).",
        "",
        _table(optional) if optional else "_None installed._",
        "",
    ]

    unlisted = group(python, "unlisted")
    if unlisted:
        parts += [
            "## Python — installed but not declared",
            "",
            "Present in the environment but reachable from neither requirements file.",
            "",
            _table(unlisted),
            "",
        ]

    parts += [
        "## npm — shipped in the bundle",
        "",
        _table(group(node, "required")),
        "",
        "## npm — build tooling only",
        "",
        "Vite, TypeScript, Tailwind and their dependencies. These never reach the",
        "browser.",
        "",
        _table(group(node, "build-only")),
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="verify only; do not rewrite THIRD_PARTY_LICENSES.md",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="also fail on copyleft in an optional accelerator",
    )
    args = parser.parse_args()

    python = python_packages()
    node = node_packages()

    if not args.check:
        OUTPUT.write_text(render(python, node))
        print(f"wrote {OUTPUT.relative_to(REPO)}")

    failures = []
    warnings = []
    for package in python + node:
        verdict = classify(package["license"])
        if verdict == "permissive":
            continue
        line = (
            f"  {package['name']} {package['version']} — {package['license']} "
            f"[{package['scope']}]"
        )
        fatal = verdict == "forbidden" and (
            args.strict or package["scope"] in ("required", "unlisted")
        )
        if fatal:
            failures.append(line)
        else:
            warnings.append(f"{line} ({verdict})")

    if warnings:
        print("\nCopyleft outside the required set:")
        print("\n".join(sorted(warnings)))

    if failures:
        print("\nGPL/AGPL in the required dependency set — refusing to build (§8):")
        print("\n".join(sorted(failures)))
        return 1

    print(f"\n{len(python)} Python + {len(node)} npm packages checked; required set is clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
