"""Unit tests for cli_test_utils.run_cli_command timeout-retry semantics.

CLI startup can stall for tens of seconds under bursty host contention
(Dropbox sync, parallel agent sessions). One stall must not fail a harness
run, but a genuine hang (two consecutive timeouts) must still raise.
"""

import subprocess

import pytest

import cli_test_utils


def test_run_cli_command_retries_once_after_timeout(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(cli_test_utils.subprocess, "run", fake_run)

    result = cli_test_utils.run_cli_command("fake-cli", ["--help"], timeout=5)

    assert result.returncode == 0
    assert result.stdout == "ok"
    assert calls == [["fake-cli", "--help"], ["fake-cli", "--help"]]
    assert "timed out after 5s" in capsys.readouterr().err


def test_run_cli_command_raises_after_second_timeout(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr(cli_test_utils.subprocess, "run", fake_run)

    with pytest.raises(subprocess.TimeoutExpired):
        cli_test_utils.run_cli_command("fake-cli", ["--help"], timeout=5)

    assert len(calls) == 2
