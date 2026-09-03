"""Shared fixtures: a disposable MicroWorker project root with a config.json.

Every test points `MICROWORKER_ROOT` at a temp directory, so nothing here can
read or write the real project -- including `data/tasks.db`, which merge creates
under that same root. `SITES` mirrors the real config.json shape: eight sites,
each with exactly `cli`, `account`, `lastpass_item`, `auth_command` and
`disabled` (testpapas and taskerdata were cut from the roster 2026-09-03 per
Adam; the fixture tracks it).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from microworker_cli import envelope

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SITES = {
    "microworkers": {"cli": "microworkers", "account": True, "lastpass_item": "Microworkers",
                     "auth_command": "microworkers auth login --credential-type browser_session",
                     "disabled": False},
    "oneforma": {"cli": None, "account": True, "lastpass_item": "OneForma", "auth_command": None,
                 "disabled": False},
    "humanrail": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None,
                  "disabled": False},
    "mercor": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None,
               "disabled": False},
    "trainee-digital": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None,
                        "disabled": False},
    "atlas-capture": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None,
                      "disabled": False},
    "outlier": {"cli": None, "account": True, "lastpass_item": "Outlier", "auth_command": None,
                "disabled": False},
    "crowdgen": {"cli": None, "account": False, "lastpass_item": None, "auth_command": None,
                 "disabled": False},
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
