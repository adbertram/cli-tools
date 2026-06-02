"""Regression tests for cache isolation in live CLI execution checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

import cli_test_utils


SKILL_ROOT = Path(__file__).resolve().parents[1]
LIVE_TEST_FILES = [
    SKILL_ROOT / "tests/test_execution.py",
    SKILL_ROOT / "tests/test_filters.py",
    SKILL_ROOT / "tests/test_output.py",
]


def test_run_live_cli_command_clears_cache_before_target(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(cli_test_utils.subprocess, "run", fake_run)

    cli_test_utils.run_live_cli_command("/tmp/example", ["items", "list"], timeout=17)

    assert calls == [
        ["/tmp/example", "cache", "clear"],
        ["/tmp/example", "items", "list"],
    ]


def test_live_tests_use_cache_clearing_runner():
    for path in LIVE_TEST_FILES:
        text = path.read_text()
        assert "run_live_cli_command" in text
        assert "run_cli_command(" not in text

