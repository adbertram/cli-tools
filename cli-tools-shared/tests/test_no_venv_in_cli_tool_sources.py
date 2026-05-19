"""Enforce: no virtualenv directories inside CLI tool source folders.

A CLI tool's canonical source folder (e.g., ~/Dropbox/GitRepos/cli-tools/copilot/)
must NOT contain a `.venv/`, `venv/`, or `.virtualenv/` directory at its root.
Virtualenvs must live at a user path outside the source tree, such as:

    - ~/.local/share/uv/tools/<tool>/         (created by `uv tool install`)
    - ~/.venvs/<tool>/                        (manual venv location)

Rationale: a virtualenv inside the CLI tool folder gets synced by Dropbox,
pollutes the source tree, and can confuse editable-install resolution
(see the copilot-cli redirect bug fixed alongside this test).
"""
from __future__ import annotations

from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent.parent  # cli-tools/
SKIP_DIRS = {
    ".git",
    ".DS_Store",
    "_templates",
    "docs",
    "node_modules",
    "__pycache__",
}
FORBIDDEN_VENVS = {".venv", "venv", ".virtualenv", "env", ".env_dir"}


def _find_cli_tools():
    """Find all CLI tool directories that have a pyproject.toml."""
    tools = []
    for d in sorted(TOOLS_DIR.iterdir()):
        if not d.is_dir() or d.name in SKIP_DIRS or d.name.startswith("."):
            continue
        if (d / "pyproject.toml").exists():
            tools.append(d)
    return tools


@pytest.fixture(params=_find_cli_tools(), ids=lambda d: d.name)
def cli_tool(request):
    return request.param


def test_no_venv_in_cli_tool_source(cli_tool):
    """A CLI tool source folder must not contain any virtualenv directory."""
    offenders = []
    for name in FORBIDDEN_VENVS:
        candidate = cli_tool / name
        if candidate.exists():
            offenders.append(candidate)

    assert not offenders, (
        f"{cli_tool.name} contains virtualenv directories inside its source folder: "
        f"{[str(p.relative_to(cli_tool)) for p in offenders]}. "
        f"Virtualenvs must live outside the source tree (e.g., "
        f"~/.local/share/uv/tools/<tool>/ or ~/.venvs/<tool>/). "
        f"Remove these and reinstall via `uv tool install -e {cli_tool} --force`."
    )
