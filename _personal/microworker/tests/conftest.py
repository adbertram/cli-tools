"""Shared fixtures: a disposable MicroWorker project root with a config.json.

Every test points `MICROWORKER_ROOT` at a temp directory, so nothing here can
read or write the real project. `SITES` mirrors the real config.json shape:
eleven sites, each with exactly `cli`, `account`, `lastpass_item` and
`auth_command`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SITES = {
    "taskerdata": {"cli": "taskerdata", "account": True, "lastpass_item": "TaskerData",
                   "auth_command": "taskerdata auth login --credential-type browser_session"},
    "microworkers": {"cli": "microworkers", "account": True, "lastpass_item": "Microworkers",
                     "auth_command": "microworkers auth login --credential-type browser_session"},
    "toloka": {"cli": "toloka", "account": True, "lastpass_item": "Toloka",
               "auth_command": "toloka auth login --credential-type browser_session"},
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
def microworkers_record() -> dict:
    """One real `microworkers tasks list` record, frozen from a live run."""
    records = json.loads(
        (FIXTURES / "microworkers_tasks_list.json").read_text(encoding="utf-8"))
    assert isinstance(records, list) and records, "fixture must be a non-empty list"
    return records[0]
