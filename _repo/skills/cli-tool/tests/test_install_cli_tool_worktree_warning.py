"""Regression coverage for the worktree warning in install-cli-tool.sh.

``uv tool install`` writes into a single global venv per CLI
(``~/.local/share/uv/tools/<pkg>``), shared by every checkout on the
machine -- there is no per-worktree install. Running install-cli-tool.sh from
a linked git worktree overlays the ``cli-tools-shared`` dependency (see the
script's "Local shared dependency overlay" section) from that worktree's
copy into the *global* registry; once the worktree is removed, every CLI
that depends on cli-tools-shared keeps resolving to the now-missing path.
This is exactly how a prior repair worktree's teardown broke the production
bricklink and garrul CLIs on adam-server.

The script now warns on stderr whenever it detects its own checkout is a
linked worktree, so that condition is visible instead of silent.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
MISSING_TOOL = "nosuchtool-xyz"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(script), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _build_primary_checkout(tmp_path: Path) -> Path:
    """Create a standalone git checkout (not a worktree) with the installer."""
    repo_root = tmp_path / "primary"
    skill_dir = repo_root / "_repo" / "skills" / "cli-tool"
    shutil.copytree(SCRIPTS_DIR, skill_dir / "scripts")

    subprocess.run(["git", "init", "-q"], cwd=repo_root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        cwd=repo_root, check=True,
    )
    return repo_root


def _add_worktree(primary_repo: Path, tmp_path: Path) -> Path:
    """Add a linked worktree of ``primary_repo`` and return its root."""
    subprocess.run(
        ["git", "branch", "wt-branch"], cwd=primary_repo, check=True,
    )
    worktree_root = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(worktree_root), "wt-branch"],
        cwd=primary_repo, check=True,
    )
    return worktree_root


def test_install_script_warns_when_run_from_a_linked_worktree(tmp_path):
    primary_repo = _build_primary_checkout(tmp_path)
    worktree_root = _add_worktree(primary_repo, tmp_path)
    script = worktree_root / "_repo" / "skills" / "cli-tool" / "scripts" / "install-cli-tool.sh"

    result = _run(script, MISSING_TOOL)

    assert result.returncode == 1, result.stderr
    assert "linked git worktree" in result.stderr, result.stderr
    assert "canonical cli-tools checkout" in result.stderr, result.stderr


def test_install_script_does_not_warn_from_a_primary_checkout(tmp_path):
    primary_repo = _build_primary_checkout(tmp_path)
    script = primary_repo / "_repo" / "skills" / "cli-tool" / "scripts" / "install-cli-tool.sh"

    result = _run(script, MISSING_TOOL)

    assert result.returncode == 1, result.stderr
    assert "linked git worktree" not in result.stderr, result.stderr
