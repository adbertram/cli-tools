"""The atlas-capture adapter: raw `tasks list` record -> task contract.

Real records are the fixtures under ``tests/fixtures/`` captured live
2026-09-03 from Adam's authenticated Atlas Capture session:
``atlas-capture-account.json`` (the real ``user.me`` payload) and
``atlas-capture-tasks-empty.json`` (the real, currently-empty task list). No
real Atlas TASK record exists yet, so the adapter's mapping is deliberately
not written — see the module docstring for why it refuses instead of guessing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli_tools_shared.exceptions import ClientError

from microworker_cli.adapters import atlas_capture

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_site_constant():
    assert atlas_capture.SITE == "atlas-capture"


def test_to_task_refuses_the_real_account_payload():
    """The account record is real but is NOT a task record: refusing is the
    only honest behavior until a real task record exists."""
    with pytest.raises(ClientError) as excinfo:
        atlas_capture.to_task(load("atlas-capture-account.json"))
    assert "atlas-capture" in str(excinfo.value)
    assert "no real task record" in str(excinfo.value)


def test_to_task_refuses_any_guessed_record_shape():
    """A made-up record shape must not quietly map — nothing is invented."""
    with pytest.raises(ClientError):
        atlas_capture.to_task({"id": "ep-1", "title": "Label an episode",
                               "url": "https://audit.atlascapture.io/tasks"})
    with pytest.raises(ClientError):
        atlas_capture.to_task({})


def test_empty_task_list_means_adapter_is_never_called():
    """The only real task payload is empty: a registered adapter is invoked
    per record, so zero records means zero mappings — this is the fact the
    module docstring relies on."""
    assert load("atlas-capture-tasks-empty.json") == []
