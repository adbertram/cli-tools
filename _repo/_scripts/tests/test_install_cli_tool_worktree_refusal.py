"""Regression coverage for the worktree refusal in _repo/_scripts/install-cli-tool.sh.

The root README documents this script as the main way to install a CLI
(``_repo/_scripts/install-cli-tool.sh <tool-folder>``). It runs
``uv tool install --force --editable`` directly and, unlike
``_repo/skills/cli-tool/scripts/install-cli-tool.sh``, had no check for a
linked git worktree -- so running it from an Issue Manager repair worktree
still installed an editable ``cli-tools-shared`` pointing at the worktree
into the global ``~/.local/share/uv/tools`` registry. That is exactly the
failure that broke the production bricklink and garrul CLIs: both declare
``cli-tools-shared = { path = "../_repo/cli-tools-shared", editable = true }``
in their pyproject.toml.

This script now refuses outright -- exits before invoking ``uv`` at all --
whenever it detects its own checkout is a linked worktree, mirroring the
guard already in the skill installer.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
INSTALLER_RELATIVE = Path("_repo/_scripts/install-cli-tool.sh")
RESOLVER_RELATIVE = Path("_repo/skills/cli-tool/scripts/resolve_uv_python.py")
MISSING_TOOL = "nosuchtool-xyz"
REAL_TOOL = "faketool"


def _run(script: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(script), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _build_primary_checkout(tmp_path: Path) -> Path:
    """Create a standalone git checkout (not a worktree) with the installer."""
    repo_root = tmp_path / "primary"
    installer_dest = repo_root / INSTALLER_RELATIVE
    installer_dest.parent.mkdir(parents=True)
    shutil.copy2(SCRIPTS_DIR / "install-cli-tool.sh", installer_dest)

    resolver_dest = repo_root / RESOLVER_RELATIVE
    resolver_dest.parent.mkdir(parents=True)
    resolver_src = SCRIPTS_DIR.parents[1] / RESOLVER_RELATIVE
    shutil.copy2(resolver_src, resolver_dest)

    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        cwd=repo_root, check=True,
    )
    return repo_root


def _add_worktree(primary_repo: Path, tmp_path: Path) -> Path:
    subprocess.run(["git", "branch", "wt-branch"], cwd=primary_repo, check=True)
    worktree_root = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(worktree_root), "wt-branch"],
        cwd=primary_repo, check=True,
    )
    return worktree_root


def _make_uv_spy(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "spy-bin"
    bin_dir.mkdir()
    marker = tmp_path / "uv-invoked.log"
    uv_stub = bin_dir / "uv"
    uv_stub.write_text(
        "#!/usr/bin/env bash\n"
        f"echo \"$@\" >> '{marker}'\n"
        "exit 0\n"
    )
    uv_stub.chmod(uv_stub.stat().st_mode | stat.S_IEXEC)
    return bin_dir, marker


def test_install_script_refuses_when_run_from_a_linked_worktree(tmp_path):
    primary_repo = _build_primary_checkout(tmp_path)
    worktree_root = _add_worktree(primary_repo, tmp_path)
    script = worktree_root / INSTALLER_RELATIVE

    result = _run(script, MISSING_TOOL)

    assert result.returncode != 0
    assert "linked git worktree" in result.stderr, result.stderr
    assert "canonical cli-tools checkout" in result.stderr, result.stderr


def test_install_script_does_not_warn_from_a_primary_checkout(tmp_path):
    primary_repo = _build_primary_checkout(tmp_path)
    script = primary_repo / INSTALLER_RELATIVE

    result = _run(script, MISSING_TOOL)

    assert "linked git worktree" not in result.stderr, result.stderr
    # Missing-tool failure is still reported through the existing path.
    assert "Tool folder not found" in result.stderr, result.stderr


def test_install_script_never_invokes_uv_from_a_linked_worktree(tmp_path):
    """The actual regression: this installer ran `uv tool install
    --force --editable` directly against the global
    ~/.local/share/uv/tools registry with no worktree guard at all. A real
    tool directory (with a pyproject.toml, so the pre-install checks pass)
    must never reach any `uv` invocation when run from a worktree."""
    primary_repo = _build_primary_checkout(tmp_path)
    worktree_root = _add_worktree(primary_repo, tmp_path)
    script = worktree_root / INSTALLER_RELATIVE

    tool_dir = worktree_root / REAL_TOOL
    tool_dir.mkdir()
    (tool_dir / "pyproject.toml").write_text(f'[project]\nname = "{REAL_TOOL}-cli"\n')

    spy_bin, marker = _make_uv_spy(tmp_path)
    env = dict(os.environ)
    env["PATH"] = f"{spy_bin}:{env['PATH']}"

    result = _run(script, REAL_TOOL, env=env)

    assert result.returncode != 0
    assert "linked git worktree" in result.stderr, result.stderr
    assert not marker.exists(), (
        "install-cli-tool.sh invoked uv from a linked worktree: "
        f"{marker.read_text() if marker.exists() else ''}"
    )


def test_install_script_bypass_env_var_allows_worktree_install(tmp_path):
    """CLI_TOOLS_ALLOW_WORKTREE_INSTALL=1 exists only for tests/CI with a
    sandboxed HOME; confirm it actually lifts the refusal so a sandboxed
    uv spy is reached."""
    primary_repo = _build_primary_checkout(tmp_path)
    worktree_root = _add_worktree(primary_repo, tmp_path)
    script = worktree_root / INSTALLER_RELATIVE

    tool_dir = worktree_root / REAL_TOOL
    tool_dir.mkdir()
    (tool_dir / "pyproject.toml").write_text(f'[project]\nname = "{REAL_TOOL}-cli"\n')

    spy_bin, marker = _make_uv_spy(tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    env = dict(os.environ)
    env["PATH"] = f"{spy_bin}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["CLI_TOOLS_ALLOW_WORKTREE_INSTALL"] = "1"

    result = _run(script, REAL_TOOL, env=env)

    assert "linked git worktree" not in result.stderr, result.stderr
    assert marker.exists(), "expected uv to be invoked once the bypass env var is set"
