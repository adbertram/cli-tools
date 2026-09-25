"""Regression coverage for symlink-safe root resolution in the cli-tool scripts.

``~/.claude/skills/cli-tool`` is a symlink to
``<cli-tools-root>/_repo/skills/cli-tool``, and that symlinked spelling is the
documented invocation route for the lifecycle scripts in the skill's ``scripts/``
directory. A ``cd`` without ``-P`` keeps the symlink in ``$PWD``, so ``cd
"$SCRIPT_DIR/../../../.."`` lands beside the symlink instead of on the cli-tools
root, and every path derived from it (``<root>/<tool>``) misses the real
repository -- which is how every invocation through the symlinked skill path came
to fail with ``CLI tool directory not found: <wrong root>/<tool>``.

Each test below builds a fake cli-tools root, exposes its cli-tool skill
directory through a symlink, and runs the real script through the symlinked
spelling. The assertions are on the root the script resolved to, so they fail
against a ``cd`` without ``-P`` and pass with ``cd -P``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
FAKE_TOOL = "faketool"
MISSING_TOOL = "nosuchtool-xyz"
SCAFFOLDED_TOOL = "exists"


def _symlinked_skill_scripts(tmp_path: Path) -> tuple[Path, Path]:
    """Return (fake cli-tools root, scripts dir reached through a symlinked skill dir)."""
    repo_root = tmp_path / "fakeroot"
    skill_dir = repo_root / "_repo" / "skills" / "cli-tool"
    shutil.copytree(SCRIPTS_DIR, skill_dir / "scripts")

    link_dir = tmp_path / "linkview"
    link_dir.mkdir()
    (link_dir / "cli-tool").symlink_to(skill_dir)

    return repo_root, link_dir / "cli-tool" / "scripts"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(script), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_install_script_resolves_cli_tools_dir_through_symlinked_skill_dir(tmp_path):
    """The reported failure: install-cli-tool.sh must find tools under the real root."""
    repo_root, scripts = _symlinked_skill_scripts(tmp_path)
    expected_root = repo_root.resolve()

    result = _run(scripts / "install-cli-tool.sh", "--force-refresh", MISSING_TOOL)

    assert result.returncode == 1, result.stderr
    assert f"{expected_root}/{MISSING_TOOL}" in result.stderr, result.stderr


def test_validate_script_resolves_cli_tools_dir_through_symlinked_skill_dir(tmp_path):
    """validate-cli-tool.sh must inspect the tool directory under the real root."""
    repo_root, scripts = _symlinked_skill_scripts(tmp_path)
    tool_dir = repo_root / FAKE_TOOL
    tool_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text('[project]\nname = "faketool-cli"\n')

    result = _run(scripts / "validate-cli-tool.sh", FAKE_TOOL)

    payload = json.loads(result.stdout)
    assert payload["cli_name"] == FAKE_TOOL
    assert payload["checks"]["dir_exists"] is True, result.stdout


def test_list_script_resolves_cli_tools_dir_through_symlinked_skill_dir(tmp_path):
    """list-cli-tool.sh must enumerate tools under the real root."""
    repo_root, scripts = _symlinked_skill_scripts(tmp_path)
    tool_dir = repo_root / FAKE_TOOL
    tool_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text('[project]\nname = "faketool-cli"\n')

    result = _run(scripts / "list-cli-tool.sh")

    assert result.returncode == 0, result.stderr
    assert FAKE_TOOL in result.stdout, result.stdout


def test_remove_script_resolves_cli_tools_dir_through_symlinked_skill_dir(tmp_path):
    """remove-cli-tool.sh must look for the named tool under the real root."""
    repo_root, scripts = _symlinked_skill_scripts(tmp_path)
    expected_root = repo_root.resolve()

    result = _run(scripts / "remove-cli-tool.sh", MISSING_TOOL)

    assert result.returncode == 1, result.stderr
    assert f"{expected_root}/{MISSING_TOOL}" in result.stderr, result.stderr


def test_create_skill_script_resolves_cli_tools_dir_through_symlinked_skill_dir(tmp_path):
    """create-cli-tool-skill must scaffold under the real ``_repo/skills`` directory."""
    repo_root, scripts = _symlinked_skill_scripts(tmp_path)
    existing_skill = repo_root / "_repo" / "skills" / f"{SCAFFOLDED_TOOL}-cli"
    existing_skill.mkdir(parents=True)

    result = _run(scripts / "create-cli-tool-skill", SCAFFOLDED_TOOL)

    assert result.returncode == 1, result.stderr
    assert f"{existing_skill.resolve()} already exists" in result.stderr, result.stderr
