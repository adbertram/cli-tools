"""Removal completeness contract for ``remove-cli-tool.sh``.

The script used to report success while leaving three registration surfaces
behind -- the tool's own service skill (``_repo/skills/<name>-cli/``), its
``[cli_specific.<name>]`` section in
``_repo/skills/cli-tool/tests/cli_test_config.toml`` and its row in the root
``README.md`` -- and it pointed the operator at ``<cli-tools-root>/docs/cli_tools.md``
instead of ``<cli-tools-root>/_repo/docs/cli_tools.md``. It also aborted on the
``uv tool uninstall`` line whenever the tool was not installed (``uv`` exits 2),
because ``set -e`` turned a missing tool into a failed removal.

Each test builds a cli-tools-shaped fixture tree, copies the real script into
``<fixture>/_repo/skills/cli-tool/scripts/`` so the script's own root resolution
points at the fixture, and redirects ``HOME`` and ``PATH`` so no real launcher,
``uv`` registry entry, or repository file is touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
REMOVER = SKILL_ROOT / "scripts/remove-cli-tool.sh"

TOOL = "fixturetool"
OTHER_TOOL = "alphatool"
MISSING_TOOL = "notatool"

CONFIG_TEMPLATE = """[general]
command_timeout = 30

[exclusions]
no_auth_clis = ["{other}"]

[cli_specific.{other}]
list_commands = ["things list"]

[cli_specific.{tool}]
list_commands = ["posts list"]

[cli_specific.{tool}.param_fixtures]
"posts list" = {{ "_pos1" = "blog" }}

[cli_specific.zeta]
max_nested_depth = 4
"""

README_TEMPLATE = """| Tool | Command | What it does |
| --- | --- | --- |
| [`{other}`]({other}/) | `{other}` | The tool that stays. |
| [`{tool}`]({tool}/) | `{tool}` | The tool under removal. |
| [`zeta`](zeta/) | `zeta` | Another tool that stays. |
"""

FAKE_UV = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$UV_LOG"
if [ "${1:-} ${2:-}" = "tool uninstall" ]; then
    exit "${FAKE_UV_UNINSTALL_RC:-0}"
fi
printf 'unexpected uv args: %s\\n' "$*" >&2
exit 9
"""


def _build_fixture_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(repo_root, home_dir)`` for a cli-tools-shaped fixture tree."""
    repo_root = tmp_path / "cli-tools"
    home_dir = tmp_path / "home"
    fake_bin = home_dir / "bin"

    script_dir = repo_root / "_repo" / "skills" / "cli-tool" / "scripts"
    tests_dir = repo_root / "_repo" / "skills" / "cli-tool" / "tests"
    skill_dir = repo_root / "_repo" / "skills" / f"{TOOL}-cli"
    docs_dir = repo_root / "_repo" / "docs"
    bin_dir = home_dir / ".local" / "bin"
    for directory in (script_dir, tests_dir, skill_dir, docs_dir, bin_dir, fake_bin):
        directory.mkdir(parents=True, exist_ok=True)

    script = script_dir / "remove-cli-tool.sh"
    shutil.copy2(REMOVER, script)
    script.chmod(0o755)

    tool_dir = repo_root / TOOL
    tool_dir.mkdir()
    (tool_dir / "pyproject.toml").write_text(
        f'[project]\nname = "{TOOL}-cli"\n', encoding="utf-8"
    )

    (skill_dir / "SKILL.md").write_text("service skill body\n", encoding="utf-8")
    (skill_dir / "usage.json").write_text("{}\n", encoding="utf-8")

    (tests_dir / "cli_test_config.toml").write_text(
        CONFIG_TEMPLATE.format(tool=TOOL, other=OTHER_TOOL), encoding="utf-8"
    )
    (repo_root / "README.md").write_text(
        README_TEMPLATE.format(tool=TOOL, other=OTHER_TOOL), encoding="utf-8"
    )
    (docs_dir / "cli_tools.md").write_text(
        f"| `{TOOL}` | Docs row. |\n| `{OTHER_TOOL}` | Docs row. |\n", encoding="utf-8"
    )

    launcher = bin_dir / TOOL
    launcher.symlink_to(home_dir / ".local" / "share" / "uv" / "tools" / f"{TOOL}-cli" / "bin" / TOOL)

    fake_uv = fake_bin / "uv"
    fake_uv.write_text(FAKE_UV, encoding="utf-8")
    fake_uv.chmod(0o755)

    return repo_root, home_dir


def _run_remover(
    repo_root: Path,
    home_dir: Path,
    *args: str,
    uv_uninstall_rc: int = 0,
) -> subprocess.CompletedProcess[str]:
    script = repo_root / "_repo" / "skills" / "cli-tool" / "scripts" / "remove-cli-tool.sh"
    return subprocess.run(
        [str(script), *args],
        cwd=repo_root,
        env={
            **os.environ,
            "HOME": str(home_dir),
            "PATH": f"{home_dir / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "UV_LOG": str(repo_root / "uv.log"),
            "FAKE_UV_UNINSTALL_RC": str(uv_uninstall_rc),
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("help_flag", ["--help", "-h"])
def test_remover_should_print_usage_when_help_requested(tmp_path, help_flag):
    repo_root, home_dir = _build_fixture_repo(tmp_path)

    result = _run_remover(repo_root, home_dir, help_flag)

    assert result.returncode == 0
    assert result.stdout == "Usage: remove-cli-tool.sh <tool-name>\n"
    assert result.stderr == ""


def test_remover_should_require_a_tool_name(tmp_path):
    repo_root, home_dir = _build_fixture_repo(tmp_path)

    result = _run_remover(repo_root, home_dir)

    assert result.returncode == 1
    assert "Error: Tool name required" in result.stderr


def test_remover_should_delete_every_registration_surface(tmp_path):
    repo_root, home_dir = _build_fixture_repo(tmp_path)

    result = _run_remover(repo_root, home_dir, TOOL)

    assert result.returncode == 0, result.stderr
    assert not (repo_root / TOOL).exists()
    assert not (home_dir / ".local" / "bin" / TOOL).exists()
    assert not (repo_root / "_repo" / "skills" / f"{TOOL}-cli").exists()

    readme_lines = (repo_root / "README.md").read_text(encoding="utf-8").splitlines()
    assert not [line for line in readme_lines if f"[`{TOOL}`]({TOOL}/)" in line]
    assert [line for line in readme_lines if f"[`{OTHER_TOOL}`]({OTHER_TOOL}/)" in line]

    config_text = (repo_root / "_repo" / "skills" / "cli-tool" / "tests" / "cli_test_config.toml").read_text(
        encoding="utf-8"
    )
    assert f"[cli_specific.{TOOL}]" not in config_text
    assert f"[cli_specific.{TOOL}.param_fixtures]" not in config_text
    config = tomllib.loads(config_text)
    assert set(config["cli_specific"]) == {OTHER_TOOL, "zeta"}
    assert config["cli_specific"][OTHER_TOOL] == {"list_commands": ["things list"]}
    assert config["exclusions"]["no_auth_clis"] == [OTHER_TOOL]

    assert str(repo_root / "_repo" / "docs" / "cli_tools.md") in result.stdout
    assert str(repo_root / "docs" / "cli_tools.md") not in result.stdout

    uv_log = (repo_root / "uv.log").read_text(encoding="utf-8")
    assert f"tool uninstall {TOOL}-cli" in uv_log


def test_remover_should_finish_when_the_uv_tool_is_not_installed(tmp_path):
    """``uv tool uninstall`` exits 2 for a tool that is not installed."""
    repo_root, home_dir = _build_fixture_repo(tmp_path)

    result = _run_remover(repo_root, home_dir, TOOL, uv_uninstall_rc=2)

    assert result.returncode == 0, result.stderr
    assert not (repo_root / TOOL).exists()
    assert not (repo_root / "_repo" / "skills" / f"{TOOL}-cli").exists()
    assert f"[cli_specific.{TOOL}]" not in (
        repo_root / "_repo" / "skills" / "cli-tool" / "tests" / "cli_test_config.toml"
    ).read_text(encoding="utf-8")
    assert not [line for line in (repo_root / "README.md").read_text(encoding="utf-8").splitlines() if f"[`{TOOL}`]({TOOL}/)" in line]
    assert str(repo_root / "_repo" / "docs" / "cli_tools.md") in result.stdout


def test_remover_should_refuse_an_unknown_tool_without_touching_anything(tmp_path):
    repo_root, home_dir = _build_fixture_repo(tmp_path)
    readme_before = (repo_root / "README.md").read_text(encoding="utf-8")
    config_before = (
        repo_root / "_repo" / "skills" / "cli-tool" / "tests" / "cli_test_config.toml"
    ).read_text(encoding="utf-8")

    result = _run_remover(repo_root, home_dir, MISSING_TOOL)

    assert result.returncode == 1
    assert f"CLI tool '{MISSING_TOOL}' not found" in result.stderr
    assert (repo_root / "_repo" / "skills" / f"{TOOL}-cli").is_dir()
    assert (repo_root / "README.md").read_text(encoding="utf-8") == readme_before
    assert (
        repo_root / "_repo" / "skills" / "cli-tool" / "tests" / "cli_test_config.toml"
    ).read_text(encoding="utf-8") == config_before


def test_remover_should_report_absent_skill_and_config_and_readme_row(tmp_path):
    repo_root, home_dir = _build_fixture_repo(tmp_path)
    shutil.rmtree(repo_root / "_repo" / "skills" / f"{TOOL}-cli")
    (repo_root / "README.md").write_text(
        f"| Tool | Command | What it does |\n"
        f"| --- | --- | --- |\n"
        f"| [`{OTHER_TOOL}`]({OTHER_TOOL}/) | `{OTHER_TOOL}` | A tool that stays. |\n",
        encoding="utf-8",
    )
    (repo_root / "_repo" / "skills" / "cli-tool" / "tests" / "cli_test_config.toml").write_text(
        f'[exclusions]\nno_auth_clis = ["{OTHER_TOOL}"]\n\n'
        f"[cli_specific.{OTHER_TOOL}]\nlist_commands = [\"things list\"]\n",
        encoding="utf-8",
    )
    readme_before = (repo_root / "README.md").read_text(encoding="utf-8")
    config_before = (
        repo_root / "_repo" / "skills" / "cli-tool" / "tests" / "cli_test_config.toml"
    ).read_text(encoding="utf-8")

    result = _run_remover(repo_root, home_dir, TOOL)

    assert result.returncode == 0, result.stderr
    assert not (repo_root / TOOL).exists()
    assert f"Unchanged: no [cli_specific.{TOOL}] section" in result.stdout
    assert f"Unchanged: no README.md table row for '{TOOL}'" in result.stdout
    assert "Skill: (not found)" in result.stdout
    assert (repo_root / "README.md").read_text(encoding="utf-8") == readme_before
    assert (
        repo_root / "_repo" / "skills" / "cli-tool" / "tests" / "cli_test_config.toml"
    ).read_text(encoding="utf-8") == config_before
    assert str(repo_root / "_repo" / "docs" / "cli_tools.md") in result.stdout
