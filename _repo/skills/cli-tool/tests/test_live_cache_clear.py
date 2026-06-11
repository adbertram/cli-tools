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


def test_run_cli_command_removes_harness_python_environment(monkeypatch):
    captured_env = {}

    monkeypatch.setenv("VIRTUAL_ENV", "/tmp/harness-venv")
    monkeypatch.setenv("PYTHONPATH", "/tmp/harness-pythonpath")
    monkeypatch.setenv("PYTHONHOME", "/tmp/harness-pythonhome")
    monkeypatch.setenv("__PYVENV_LAUNCHER__", "/tmp/harness-launcher")
    monkeypatch.setenv("PATH", "/tmp/harness-venv/bin:/usr/bin")

    def fake_run(cmd, **kwargs):
        captured_env.update(kwargs["env"])
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(cli_test_utils.subprocess, "run", fake_run)

    cli_test_utils.run_cli_command("/tmp/example", ["--help"])

    assert captured_env["PATH"] == "/usr/bin"
    assert "VIRTUAL_ENV" not in captured_env
    assert "PYTHONPATH" not in captured_env
    assert "PYTHONHOME" not in captured_env
    assert "__PYVENV_LAUNCHER__" not in captured_env


def test_live_tests_use_cache_clearing_runner():
    for path in LIVE_TEST_FILES:
        text = path.read_text()
        assert "run_live_cli_command" in text
        assert "run_cli_command(" not in text
