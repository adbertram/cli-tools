"""Regression coverage for the worktree refusal in new-cli-tool's uv install step.

new-cli-tool's ``install_with_uv()`` runs a global
``uv tool install -e <tool_dir> --force --refresh`` with no ``--no-install``
flag set. That writes into the same single global registry
(``~/.local/share/uv/tools/<pkg>``) guarded elsewhere in this repo's
installers: running it from a linked git worktree overlays
``cli-tools-shared`` from that worktree's copy into the global registry, and
once the worktree is removed every CLI installed from here keeps resolving
to the now-missing path -- the same failure that broke the production
bricklink and garrul CLIs.

``install_with_uv()`` now refuses before invoking ``uv`` at all whenever
``CLI_TOOLS_DIR`` (the repo root the script resolves from its own location)
is a linked worktree, mirroring the guard in both install-cli-tool.sh
installers.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "new-cli-tool"

_loader = importlib.machinery.SourceFileLoader("new_cli_tool", str(MODULE_PATH))
_spec = importlib.util.spec_from_loader("new_cli_tool", _loader)
new_cli_tool = importlib.util.module_from_spec(_spec)
_loader.exec_module(new_cli_tool)


def _build_primary_checkout(tmp_path: Path) -> Path:
    repo_root = tmp_path / "primary"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    (repo_root / "placeholder.txt").write_text("x")
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


def test_refuses_worktree_install_false_for_primary_checkout(tmp_path, monkeypatch):
    primary_repo = _build_primary_checkout(tmp_path)
    monkeypatch.setattr(new_cli_tool, "CLI_TOOLS_DIR", primary_repo)
    monkeypatch.delenv("CLI_TOOLS_ALLOW_WORKTREE_INSTALL", raising=False)

    assert new_cli_tool.refuses_worktree_install() is False


def test_refuses_worktree_install_true_for_linked_worktree(tmp_path, monkeypatch):
    primary_repo = _build_primary_checkout(tmp_path)
    worktree_root = _add_worktree(primary_repo, tmp_path)
    monkeypatch.setattr(new_cli_tool, "CLI_TOOLS_DIR", worktree_root)
    monkeypatch.delenv("CLI_TOOLS_ALLOW_WORKTREE_INSTALL", raising=False)

    assert new_cli_tool.refuses_worktree_install() is True


def test_refuses_worktree_install_bypassed_by_env_var(tmp_path, monkeypatch):
    primary_repo = _build_primary_checkout(tmp_path)
    worktree_root = _add_worktree(primary_repo, tmp_path)
    monkeypatch.setattr(new_cli_tool, "CLI_TOOLS_DIR", worktree_root)
    monkeypatch.setenv("CLI_TOOLS_ALLOW_WORKTREE_INSTALL", "1")

    assert new_cli_tool.refuses_worktree_install() is False


def test_install_with_uv_never_invokes_uv_from_a_linked_worktree(tmp_path, monkeypatch, capsys):
    """The actual regression: install_with_uv() must bail out before any
    subprocess call to `uv` when run from a linked worktree."""
    primary_repo = _build_primary_checkout(tmp_path)
    worktree_root = _add_worktree(primary_repo, tmp_path)
    monkeypatch.setattr(new_cli_tool, "CLI_TOOLS_DIR", worktree_root)
    monkeypatch.delenv("CLI_TOOLS_ALLOW_WORKTREE_INSTALL", raising=False)

    tool_dir = worktree_root / "faketool"
    tool_dir.mkdir()
    (tool_dir / "pyproject.toml").write_text('[project]\nname = "faketool-cli"\n')

    real_run = subprocess.run

    def _spy_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd and cmd[0] == "uv":
            pytest.fail(f"uv was invoked from a linked worktree: {cmd}")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy_run)

    result = new_cli_tool.install_with_uv(tool_dir, "faketool", "api")

    assert result is False
    captured = capsys.readouterr()
    assert "linked git worktree" in captured.err
