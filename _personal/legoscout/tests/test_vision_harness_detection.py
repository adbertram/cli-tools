"""`vision.judge()` shells to exactly one vision-capable CLI, resolved once
from a deterministic read of the environment -- never a runtime
try-A-then-B fallback chain.

`detect_harness()` mirrors the elif chain already used by
`learn/scripts/collect-history-context.sh`: Claude Code, Codex, and
DeepSeek Harness (`dsh`) each carry their own environment marker.
Antigravity has no documented marker anywhere, so it (and an unattended/cron
invocation) fall into "unknown". Both `dsh` and "unknown" route to the fixed
designated fallback provider (`codex`) since `dsh` has no native vision and
Antigravity's presence cannot be detected.
"""
from __future__ import annotations

import json
import subprocess
from unittest import mock

import pytest

from legoscout_cli.pricing import vision

_HARNESS_ENV_VARS = ("CLAUDECODE", "CODEX_THREAD_ID", "CODEX_SHELL", "DSH_SHELL")


def _clean_env(monkeypatch, **overrides):
    for name in _HARNESS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)


# --- detect_harness() ------------------------------------------------------


def test_detect_harness_claude_code(monkeypatch):
    _clean_env(monkeypatch, CLAUDECODE="1")
    assert vision.detect_harness() == "claude"


def test_detect_harness_codex_via_thread_id(monkeypatch):
    _clean_env(monkeypatch, CODEX_THREAD_ID="01a076f3-cf2a-77e2-816b-95ed97fff500")
    assert vision.detect_harness() == "codex"


def test_detect_harness_codex_via_shell(monkeypatch):
    _clean_env(monkeypatch, CODEX_SHELL="1")
    assert vision.detect_harness() == "codex"


def test_detect_harness_deepseek(monkeypatch):
    _clean_env(monkeypatch, DSH_SHELL="1")
    assert vision.detect_harness() == "dsh"


def test_detect_harness_unknown_when_nothing_set(monkeypatch):
    _clean_env(monkeypatch)
    assert vision.detect_harness() == "unknown"


def test_detect_harness_claude_takes_priority_when_multiple_set(monkeypatch):
    _clean_env(monkeypatch, CLAUDECODE="1", DSH_SHELL="1")
    assert vision.detect_harness() == "claude"


# --- resolve_provider() -----------------------------------------------------


def test_resolve_provider_passes_through_claude(monkeypatch):
    _clean_env(monkeypatch, CLAUDECODE="1")
    assert vision.resolve_provider() == "claude"


def test_resolve_provider_passes_through_codex(monkeypatch):
    _clean_env(monkeypatch, CODEX_THREAD_ID="x")
    assert vision.resolve_provider() == "codex"


def test_resolve_provider_maps_dsh_to_designated_fallback(monkeypatch):
    _clean_env(monkeypatch, DSH_SHELL="1")
    assert vision.resolve_provider() == vision.DESIGNATED_FALLBACK_PROVIDER
    assert vision.resolve_provider() == "codex"


def test_resolve_provider_maps_unknown_to_designated_fallback(monkeypatch):
    _clean_env(monkeypatch)
    assert vision.resolve_provider() == vision.DESIGNATED_FALLBACK_PROVIDER
    assert vision.resolve_provider() == "codex"


# --- judge() routes to the resolved provider, exactly once -----------------


def test_judge_routes_to_codex_when_provider_resolves_to_codex(monkeypatch, tmp_path):
    _clean_env(monkeypatch, CODEX_THREAD_ID="x")
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}")
    with mock.patch.object(vision, "_judge_via_codex",
                           return_value={"listing_category": "set"}) as codex_fn, \
         mock.patch.object(vision, "_judge_via_claude") as claude_fn:
        result = vision.judge([tmp_path / "img.jpg"], "classify", schema_path)
    assert result == {"listing_category": "set"}
    codex_fn.assert_called_once()
    claude_fn.assert_not_called()


def test_judge_routes_to_claude_when_provider_resolves_to_claude(monkeypatch, tmp_path):
    _clean_env(monkeypatch, CLAUDECODE="1")
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}")
    with mock.patch.object(vision, "_judge_via_claude",
                           return_value={"listing_category": "bulk"}) as claude_fn, \
         mock.patch.object(vision, "_judge_via_codex") as codex_fn:
        result = vision.judge([tmp_path / "img.jpg"], "classify", schema_path)
    assert result == {"listing_category": "bulk"}
    claude_fn.assert_called_once()
    codex_fn.assert_not_called()


# --- _judge_via_codex: stdin regression + parsing ---------------------------


def test_judge_via_codex_closes_stdin(tmp_path):
    """Regression test: codex exec hangs reading stdin unless it is
    explicitly closed (probed and fixed 2026-09-06)."""
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}")
    event = {"type": "item.completed",
             "item": {"type": "agent_message",
                      "text": json.dumps({"listing_category": "set"})}}
    proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(event) + "\n", stderr="")
    with mock.patch.object(vision.subprocess, "run", return_value=proc) as run:
        result = vision._judge_via_codex(
            [tmp_path / "img.jpg"], "classify", schema_path, "gpt-5.6-sol")
    assert result == {"listing_category": "set"}
    _args, kwargs = run.call_args
    assert kwargs["stdin"] == vision.subprocess.DEVNULL


def test_judge_via_codex_raises_on_nonzero_exit(tmp_path):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}")
    proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    with mock.patch.object(vision.subprocess, "run", return_value=proc):
        with pytest.raises(RuntimeError, match="boom"):
            vision._judge_via_codex(
                [tmp_path / "img.jpg"], "classify", schema_path, "gpt-5.6-sol")


def test_judge_via_codex_raises_when_no_agent_message(tmp_path):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}")
    proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps({"type": "turn.started"}) + "\n",
        stderr="")
    with mock.patch.object(vision.subprocess, "run", return_value=proc):
        with pytest.raises(RuntimeError, match="no agent_message event"):
            vision._judge_via_codex(
                [tmp_path / "img.jpg"], "classify", schema_path, "gpt-5.6-sol")


# --- _judge_via_claude: stdin + parsing -------------------------------------


def test_judge_via_claude_closes_stdin(tmp_path):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}")
    response = {"is_error": False, "result": json.dumps({"listing_category": "bulk"})}
    proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(response), stderr="")
    with mock.patch.object(vision.subprocess, "run", return_value=proc) as run:
        result = vision._judge_via_claude(
            [tmp_path / "img.jpg"], "classify", schema_path, "opus")
    assert result == {"listing_category": "bulk"}
    _args, kwargs = run.call_args
    assert kwargs["stdin"] == vision.subprocess.DEVNULL


def test_judge_via_claude_raises_on_is_error(tmp_path):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}")
    response = {"is_error": True, "result": "hit rate limit"}
    proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(response), stderr="")
    with mock.patch.object(vision.subprocess, "run", return_value=proc):
        with pytest.raises(RuntimeError, match="hit rate limit"):
            vision._judge_via_claude(
                [tmp_path / "img.jpg"], "classify", schema_path, "opus")
