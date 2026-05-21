#!/usr/bin/env python3
"""Validate the cli-tools-shared persistent-profile rollout across all consumers.

For every CLI under ``<cli-tools-root>/`` whose ``browser.py``
imports ``cli_tools_shared``, this script runs ``<tool> auth status`` and
classifies the result. The classification rules live in
:data:`_CLASSIFICATIONS` as a data table — first matching predicate wins.
Adding a new classification (e.g. ``"warn"`` for non-blocking issues)
means appending an entry, not editing branching code.

Exits 0 when every consumer is ``green`` or ``unsupported``. Exits 1 when
any consumer is ``red``. ``red`` rows print the exact re-auth command.

Usage::

    python scripts/validate_rollout.py
    python scripts/validate_rollout.py --repo-root /path/to/cli-tools
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

# Allow running from a checkout without ``pip install``-ing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cli_tools_shared.discovery import discover_consumers  # noqa: E402


# Data-driven classification table. Each entry is matched in order; the
# first matching predicate wins. Adding a new bucket means appending a
# row — no code changes elsewhere.
_CLASSIFICATIONS: list[dict] = [
    {
        "label": "green",
        "predicate": lambda r: r.returncode == 0,
        "fail_run": False,
    },
    {
        "label": "unsupported",
        "predicate": lambda r: (
            r.returncode != 0
            and b"No such command 'auth'" in (r.stderr or b"")
        ),
        "fail_run": False,
    },
    {
        "label": "red",
        "predicate": lambda r: r.returncode != 0,
        "fail_run": True,
    },
]


def _classify(result: subprocess.CompletedProcess) -> dict:
    """Return the first classification entry whose predicate matches ``result``."""
    for entry in _CLASSIFICATIONS:
        if entry["predicate"](result):
            return entry
    raise RuntimeError(
        "No classification matched — add a catch-all entry to _CLASSIFICATIONS"
    )


def _tool_name_for_browser_py(browser_py: Path) -> str:
    """Derive the CLI tool name from a ``.../<tool>/<pkg>_cli/browser.py`` path."""
    return browser_py.parent.parent.name


def _resolve_cli_binary(tool_name: str) -> Path | None:
    """Locate the installed CLI launcher for ``tool_name`` on $PATH."""
    found = shutil.which(tool_name)
    return Path(found) if found else None


def run(repo_root: Path | None = None) -> int:
    consumers = discover_consumers(repo_root) if repo_root else discover_consumers()
    if not consumers:
        print("No cli_tools_shared consumers found.", file=sys.stderr)
        return 0

    rows: list[tuple[str, str, str]] = []
    any_failure = False

    for browser_py in consumers:
        tool = _tool_name_for_browser_py(browser_py)
        binary = _resolve_cli_binary(tool)
        if binary is None:
            rows.append((tool, "unsupported", "no launcher on PATH"))
            continue

        result = subprocess.run(
            [str(binary), "auth", "status"],
            capture_output=True,
            timeout=30,
        )
        entry = _classify(result)
        label = entry["label"]
        if entry["fail_run"]:
            any_failure = True
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
            tail = stderr[-1] if stderr else f"exit={result.returncode}"
            rows.append((tool, label, tail))
        elif label == "unsupported":
            rows.append((tool, label, "auth not configured"))
        else:
            rows.append((tool, label, ""))

    width = max(len(tool) for tool, _, _ in rows)
    for tool, label, note in rows:
        suffix = f" — {note}" if note else ""
        print(f"  {tool:<{width}}  {label:<11}{suffix}")
        if label == "red":
            print(f"    fix:  {tool} auth login --force")

    print()
    print(
        f"{sum(1 for _, l, _ in rows if l == 'green')} green / "
        f"{sum(1 for _, l, _ in rows if l == 'red')} red / "
        f"{sum(1 for _, l, _ in rows if l == 'unsupported')} unsupported"
    )

    return 1 if any_failure else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Root of the cli-tools repo. Defaults to the containing cli-tools checkout.",
    )
    args = parser.parse_args()
    return run(args.repo_root)


if __name__ == "__main__":
    sys.exit(main())
