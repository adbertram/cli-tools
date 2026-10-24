"""Tests for the root README catalog generator (refresh_readme.py).

Run with: python3 -m pytest _repo/_scripts/tests/test_refresh_readme.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "refresh_readme.py"
_spec = importlib.util.spec_from_file_location("refresh_readme", MODULE_PATH)
refresh_readme = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(refresh_readme)


def _write_tool(root: Path, folder: str, scripts: dict[str, str], description: str) -> None:
    tool_dir = root / folder
    tool_dir.mkdir(parents=True)
    script_lines = "\n".join(f'{name} = "{target}"' for name, target in scripts.items())
    (tool_dir / "pyproject.toml").write_text(
        "[project]\n"
        f'name = "{folder}"\n'
        f'description = "{description}"\n'
        "[project.scripts]\n"
        f"{script_lines}\n",
        encoding="utf-8",
    )


def test_canonical_command_prefers_folder_name_match():
    # Regression for agent-issues #689: a tool with more than one console-script
    # alias (gemini ships gemini and gemini-api) must not crash and must pick the
    # alias matching the folder name.
    scripts = {"gemini": "gemini_cli.main:app", "gemini-api": "gemini_cli.main:app"}
    assert refresh_readme.canonical_command("gemini", scripts) == "gemini"


def test_canonical_command_falls_back_to_shortest_then_alphabetical():
    scripts = {"zeta": "pkg:app", "beta": "pkg:app", "al": "pkg:app"}
    # No alias matches the folder name -> shortest, then alphabetical.
    assert refresh_readme.canonical_command("tool", scripts) == "al"


def test_canonical_command_rejects_empty_scripts():
    with pytest.raises(ValueError):
        refresh_readme.canonical_command("tool", {})


def test_read_tool_metadata_handles_multi_alias_tool(tmp_path):
    # Regression for agent-issues #689: read_tool_metadata previously raised
    # "must define exactly one project script" for gemini's two aliases.
    _write_tool(
        tmp_path,
        "gemini",
        {"gemini": "gemini_cli.main:app", "gemini-api": "gemini_cli.main:app"},
        "Gemini CLI.",
    )
    _write_tool(tmp_path, "airtable", {"airtable": "airtable_cli.main:app"}, "Airtable CLI.")

    tools = refresh_readme.read_tool_metadata(tmp_path)

    assert tools["gemini"]["command"] == "gemini"
    assert tools["airtable"]["command"] == "airtable"
