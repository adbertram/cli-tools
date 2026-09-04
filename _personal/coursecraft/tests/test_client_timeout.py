"""Tests for CourseCraft's Airtable subprocess boundary."""

import subprocess

import pytest

from coursecraft_cli.client import (
    AIRTABLE_CLI_COMMAND_TIMEOUT_SECONDS,
    CourseCraftClient,
    ClientError,
)


def _client() -> CourseCraftClient:
    return CourseCraftClient.__new__(CourseCraftClient)


def test_run_airtable_command_uses_retry_budget_timeout(monkeypatch):
    captured = {}

    def fake_run(args, *, stdin, capture_output, text, timeout):
        captured["args"] = args
        captured["stdin"] = stdin
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"records": []}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = _client()._run_airtable_command(["records", "list", "Courses"])

    assert result == {"records": []}
    assert captured["args"] == ["airtable", "records", "list", "Courses"]
    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["timeout"] == AIRTABLE_CLI_COMMAND_TIMEOUT_SECONDS


def test_run_airtable_command_reports_subprocess_timeout(monkeypatch):
    def fake_run(args, *, stdin, capture_output, text, timeout):
        assert stdin is subprocess.DEVNULL
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ClientError, match=f"airtable CLI command timed out after {AIRTABLE_CLI_COMMAND_TIMEOUT_SECONDS}s"):
        _client()._run_airtable_command(["records", "list", "Courses"])
