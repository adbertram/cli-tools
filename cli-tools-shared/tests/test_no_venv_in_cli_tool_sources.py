"""Enforce: no virtualenv directories inside CLI tool source folders.

A CLI tool's canonical source folder (e.g., <cli-tools-root>/copilot/)
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
SKIP_PARTS = SKIP_DIRS | {"templates"}


def _find_cli_projects():
    """Find repo-owned CLI project directories that have a pyproject.toml."""
    projects = []
    for pyproject in sorted(TOOLS_DIR.rglob("pyproject.toml")):
        project_dir = pyproject.parent
        rel_parts = project_dir.relative_to(TOOLS_DIR).parts
        if any(part in SKIP_PARTS or part.startswith(".") for part in rel_parts):
            continue
        projects.append(project_dir)
    return projects


@pytest.fixture(params=_find_cli_projects(), ids=lambda d: str(d.relative_to(TOOLS_DIR)))
def cli_project(request):
    return request.param


def test_no_venv_in_cli_tool_source(cli_project):
    """A CLI project source folder must not contain any virtualenv directory."""
    offenders = []
    for name in FORBIDDEN_VENVS:
        candidate = cli_project / name
        if candidate.exists():
            offenders.append(candidate)

    assert not offenders, (
        f"{cli_project.relative_to(TOOLS_DIR)} contains virtualenv directories inside its source folder: "
        f"{[str(p.relative_to(cli_project)) for p in offenders]}. "
        f"Virtualenvs must live outside the source tree (e.g., "
        f"~/.local/share/uv/tools/<tool>/ or ~/.venvs/<tool>/). "
        f"Remove these and reinstall via `uv tool install -e {cli_project} --force`."
    )
