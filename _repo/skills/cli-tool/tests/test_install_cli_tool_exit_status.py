"""install-cli-tool.sh must propagate a failed install through its exit status.

Regression guard for the 2026-08-25 R2 migration incident. The installer
already detected the broken install -- it emitted ``"success": false`` and
``"help_works": false`` -- but still exited 0, so callers that gate on the exit
status (``shippo/install.sh`` runs it under ``set -e`` and then prints
"Installation complete") treated a venv whose CLI could not even run ``--help``
as a completed install.

The uv calls are faked so nothing touches the machine's real uv tool registry:
``HOME`` is redirected into ``tmp_path``, which moves both ``UV_TOOL_DIR`` and
``UV_TOOL_BIN_DIR`` under the fixture.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = SKILL_ROOT / "scripts/install-cli-tool.sh"
REPO_ROOT = SKILL_ROOT.parents[2]
SHARED_DIR = REPO_ROOT / "_repo/cli-tools-shared"

FAKE_UV = """#!/usr/bin/env bash
set -uo pipefail

case "${1:-} ${2:-}" in
    "tool install")
        mkdir -p "$HOME/.local/share/uv/tools/$FAKE_TOOL_NAME/bin"
        mkdir -p "$HOME/.local/bin"
        target="$HOME/.local/bin/.$FAKE_TOOL_NAME-real"
        printf '%s\\n' '#!/usr/bin/env bash' "exit $FAKE_HELP_EXIT" > "$target"
        chmod +x "$target"
        ln -sf "$target" "$HOME/.local/bin/$FAKE_TOOL_NAME"
        exit 0
        ;;
    "pip show")
        case "${3:-}" in
            "$FAKE_PACKAGE_NAME")
                printf 'Name: %s\\nEditable project location: %s\\n' "${3}" "$FAKE_TOOL_DIR"
                exit 0
                ;;
            cli-tools-shared)
                printf 'Name: cli-tools-shared\\nEditable project location: %s\\n' "$FAKE_SHARED_DIR"
                exit 0
                ;;
        esac
        exit 1
        ;;
    "pip install")
        exit 0
        ;;
esac
printf 'unexpected uv args: %s\\n' "$*" >&2
exit 9
"""


def _run_installer(tmp_path: Path, help_exit: int) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_home = tmp_path / "home"
    fake_bin.mkdir()
    fake_home.mkdir()

    fake_uv = fake_bin / "uv"
    fake_uv.write_text(FAKE_UV)
    fake_uv.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(fake_home),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_TOOL_NAME": "cloudflare",
        "FAKE_PACKAGE_NAME": "cloudflare",
        "FAKE_TOOL_DIR": str(REPO_ROOT / "cloudflare"),
        "FAKE_SHARED_DIR": str(SHARED_DIR),
        "FAKE_HELP_EXIT": str(help_exit),
    }
    return subprocess.run(
        [str(INSTALLER), "cloudflare"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(autouse=True)
def _require_cloudflare_checkout():
    if not (REPO_ROOT / "cloudflare" / "pyproject.toml").is_file():
        pytest.skip("cloudflare/pyproject.toml not present in this checkout")


def test_installer_exits_non_zero_when_the_installed_cli_cannot_run_help(tmp_path):
    result = _run_installer(tmp_path, help_exit=1)
    payload = json.loads(result.stdout)

    assert payload["success"] is False
    assert payload["help_works"] is False
    assert result.returncode != 0, (
        "installer reported a failed install but exited 0; callers gating on "
        "the exit status would treat the broken venv as installed"
    )


def test_installer_exits_zero_when_the_installed_cli_runs_help(tmp_path):
    result = _run_installer(tmp_path, help_exit=0)
    payload = json.loads(result.stdout)

    assert payload["success"] is True
    assert payload["help_works"] is True
    assert result.returncode == 0, result.stderr
