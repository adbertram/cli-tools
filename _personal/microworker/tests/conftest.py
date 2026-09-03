"""Shared fixtures: a disposable MicroWorker project root with a config.json.

Every test points `MICROWORKER_ROOT` at a temp directory, so nothing here can
read or write the real project -- including `data/tasks.db`, which merge creates
under that same root. `SITES` mirrors the real config.json shape: ten sites,
each with exactly `cli`, `account`, `lastpass_item` and `auth_command`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from microworker_cli import envelope

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SITES = {
    "taskerdata": {"cli": "taskerdata", "account": True, "lastpass_item": "TaskerData",
                   "auth_command": "taskerdata auth login --credential-type browser_session"},
    "microworkers": {"cli": "microworkers", "account": True, "lastpass_item": "Microworkers",
                     "auth_command": "microworkers auth login --credential-type browser_session"},
    "oneforma": {"cli": None, "account": True, "lastpass_item": "OneForma", "auth_command": None},
    "humanrail": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None},
    "mercor": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None},
    "trainee-digital": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None},
    "atlas-capture": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None},
    "outlier": {"cli": None, "account": True, "lastpass_item": "Outlier", "auth_command": None},
    "crowdgen": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None},
    "testpapas": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None},
}


def write_config(root: Path, sites: dict) -> Path:
    path = root / "config.json"
    path.write_text(json.dumps({"sites": sites}, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("MICROWORKER_ROOT", str(tmp_path))
    write_config(tmp_path, SITES)
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def clock(monkeypatch):
    """`envelope.utc_now()` under test control.

    Timestamps are second-resolution, so two merges in the same test would
    otherwise stamp identical `first_seen_at` and `last_seen_at` values and the
    first-seen/last-seen distinction could not be observed at all.
    """
    class Clock:
        now = "2026-09-02T00:00:00Z"

        def set(self, value: str) -> str:
            self.now = value
            return value

    clock = Clock()
    monkeypatch.setattr(envelope, "utc_now", lambda: clock.now)
    return clock


@pytest.fixture
def microworkers_record() -> dict:
    """One real `microworkers tasks list` record, frozen from a live run."""
    records = json.loads(
        (FIXTURES / "microworkers_tasks_list.json").read_text(encoding="utf-8"))
    assert isinstance(records, list) and records, "fixture must be a non-empty list"
    return records[0]
