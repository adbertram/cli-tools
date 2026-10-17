"""Regression coverage for the worktree refusal in install-cli-tool.sh.

``uv tool install`` writes into a single global venv per CLI
(``~/.local/share/uv/tools/<pkg>``), shared by every checkout on the
machine -- there is no per-worktree install. Running install-cli-tool.sh from
a linked git worktree overlays the ``cli-tools-shared`` dependency (see the
script's "Local shared dependency overlay" section) from that worktree's
copy into the *global* registry; once the worktree is removed, every CLI
that depends on cli-tools-shared keeps resolving to the now-missing path.
This is exactly how a prior repair worktree's teardown broke the production
bricklink and garrul CLIs on adam-server.

A first fix only printed a stderr warning and then let the global
``uv tool install`` / ``uv pip install --editable`` run anyway, which did not
stop the overlay it warned about. The script now refuses outright -- exits
before invoking ``uv`` at all -- whenever it detects its own checkout is a
linked worktree, and reports the refusal on both stdout (as JSON, for
callers that only parse stdout) and stderr.
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
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


def _make_uv_spy(tmp_path: Path) -> tuple[Path, Path]:
    """Return (bin dir, marker path). The stub ``uv`` records every call."""
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


def test_install_script_reports_worktree_refusal_as_json_on_stdout(tmp_path):
    """Automated repair callers parse the JSON on stdout -- the refusal must
    be visible there too, not only in a stderr warning that a JSON-only
    parser never looks at."""
    primary_repo = _build_primary_checkout(tmp_path)
    worktree_root = _add_worktree(primary_repo, tmp_path)
    script = worktree_root / "_repo" / "skills" / "cli-tool" / "scripts" / "install-cli-tool.sh"

    result = _run(script, MISSING_TOOL)

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["worktree"] is True, result.stdout
    assert "linked git worktree" in payload["error"], result.stdout


def test_install_script_never_invokes_uv_from_a_linked_worktree(tmp_path, monkeypatch):
    """The actual regression: a prior fix only warned and then still ran
    `uv tool install` / `uv pip install --editable` against the global
    ~/.local/share/uv/tools registry from the worktree's own copy of the
    tool and of cli-tools-shared -- which is exactly the failure mode that
    broke the production bricklink and garrul CLIs. A real tool directory
    (with a pyproject.toml, so the pre-install tool-dir check passes) must
    still never reach any `uv` invocation when run from a worktree.
    """
    primary_repo = _build_primary_checkout(tmp_path)
    worktree_root = _add_worktree(primary_repo, tmp_path)
    script = worktree_root / "_repo" / "skills" / "cli-tool" / "scripts" / "install-cli-tool.sh"

    tool_dir = worktree_root / REAL_TOOL
    tool_dir.mkdir()
    (tool_dir / "pyproject.toml").write_text(f'[project]\nname = "{REAL_TOOL}-cli"\n')
    shared_dir = worktree_root / "_repo" / "cli-tools-shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "pyproject.toml").write_text('[project]\nname = "cli-tools-shared"\n')

    spy_bin, marker = _make_uv_spy(tmp_path)
    import os
    env = dict(os.environ)
    env["PATH"] = f"{spy_bin}:{env['PATH']}"

    result = _run(script, REAL_TOOL, env=env)

    assert result.returncode == 1, result.stderr
    assert "linked git worktree" in result.stderr, result.stderr
    assert not marker.exists(), (
        "install-cli-tool.sh invoked uv from a linked worktree: "
        f"{marker.read_text() if marker.exists() else ''}"
    )
