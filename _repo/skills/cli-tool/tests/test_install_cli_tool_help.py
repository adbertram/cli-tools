"""Public help contract for the canonical CLI-tool installer."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


INSTALLER = Path(__file__).resolve().parents[1] / "scripts/install-cli-tool.sh"


@pytest.mark.parametrize("help_flag", ["--help", "-h"])
def test_installer_should_print_usage_when_help_requested(help_flag: str):
    result = subprocess.run(
        [str(INSTALLER), help_flag],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "Usage: install-cli-tool.sh [--force-refresh] <name>\n"
    assert result.stderr == ""
