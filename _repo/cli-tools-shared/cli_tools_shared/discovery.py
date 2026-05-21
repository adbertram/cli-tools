"""Discover CLIs that consume ``cli_tools_shared``.

Used by the rollout-validation script after the persistent Chromium profile
refactor to enumerate per-tool ``browser.py`` files and confirm each tool
re-authenticates cleanly with the new base-class behavior.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


_IMPORT_RE = re.compile(r"from\s+cli_tools_shared\b|import\s+cli_tools_shared\b")


def discover_consumers(repo_root: Path | str | None = None) -> list[Path]:
    """Return the list of CLI ``browser.py`` files that import ``cli_tools_shared``.

    Walks ``<repo_root>/*/<pkg>_cli/browser.py``. A consumer is included
    when ``browser.py`` (or any sibling .py in the same package) contains
    a ``from cli_tools_shared``/``import cli_tools_shared`` line. Files
    that do not import ``cli_tools_shared`` are excluded. Hidden /
    underscore-prefixed package dirs are skipped.

    Returns paths sorted by tool name for deterministic output.
    """
    root = Path(repo_root) if repo_root is not None else _default_repo_root()
    if not root.is_dir():
        return []

    found: list[Path] = []
    for tool_dir in sorted(root.iterdir()):
        if not tool_dir.is_dir():
            continue
        if tool_dir.name.startswith((".", "_")):
            continue
        for pkg_dir in tool_dir.iterdir():
            if not pkg_dir.is_dir():
                continue
            if not pkg_dir.name.endswith("_cli"):
                continue
            if pkg_dir.name.startswith("_"):
                continue
            browser_py = pkg_dir / "browser.py"
            if not browser_py.is_file():
                continue
            if _imports_cli_tools_shared(pkg_dir):
                found.append(browser_py)
    return found


def _imports_cli_tools_shared(pkg_dir: Path) -> bool:
    """Return True when any .py in ``pkg_dir`` imports cli_tools_shared."""
    for py in pkg_dir.glob("*.py"):
        try:
            text = py.read_text()
        except OSError:
            continue
        if _IMPORT_RE.search(text):
            return True
    return False


def _default_repo_root() -> Path:
    """Return the cli-tools repo root (parent of this package's repo)."""
    # _repo/cli-tools-shared/cli_tools_shared/discovery.py
    # -> _repo/cli-tools-shared/cli_tools_shared
    # -> _repo/cli-tools-shared
    # -> _repo
    # -> cli-tools (the repo root containing every CLI)
    return Path(__file__).resolve().parents[3]
