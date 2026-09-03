"""Fixture-backed unit tests for atlas_capture_cli.parsers.

Every fixture under ``tests/fixtures/`` is a real payload captured live
2026-09-03 from Adam's authenticated Atlas Capture session (see parsers.py for
endpoint notes). Nothing here is fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli_tools_shared.exceptions import ClientError

from atlas_capture_cli import parsers

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_unwrap_trpc_returns_inner_json():
    body = {"result": {"data": {"json": {"hello": "world"},
                                "meta": {"values": {}, "v": 1}}}}
    assert parsers.unwrap_trpc(body) == {"hello": "world"}


def test_unwrap_trpc_rejects_wrong_envelope():
    with pytest.raises(ClientError):
        parsers.unwrap_trpc({"unexpected": True})
    with pytest.raises(ClientError):
        parsers.unwrap_trpc({"result": {"nope": 1}})


def test_normalize_user_me_from_real_fixture():
    raw = load("user-me.json")
    user = parsers.normalize_user_me(raw)
    assert user["id"] == "6a94b5a5435f5592a55678d2"
    assert user["email"] == "adbertram@gmail.com"
    assert user["full_name"] == "Adam Bertram"
    assert user["country"] == "United States"
    assert user["role"] == "USER"
    # The account has finished the onboarding wizard but is not yet certified.
    assert user["onboarding_completed"] is True
    assert user["onboarding_step"] == 4
    assert user["gt_probation_completed"] is False
    assert user["certified_role_count"] == 0


def test_normalize_rooms_config_from_real_fixture():
    raw = load("rooms-config.json")
    room = parsers.normalize_rooms_config(raw)
    assert room["default_room_id"] == "normal"
    assert room["room_label"] == "Standard Label Room"
    assert room["room_enabled"] is True
    assert room["has_access"] is True
    assert room["lock_reason"] is None
    assert room["admin_only"] is False


def test_normalize_account_status_from_real_fixture():
    raw = load("account-status.json")
    status = parsers.normalize_account_status(raw)
    assert status["bucket"] == "labeler"
    assert status["unit_label"] == "Episodes labeled"
    assert status["episodes_this_period"] == 0
    assert status["at_risk"] is True  # no labeling activity yet


def test_normalize_task_rows_empty_list_and_null():
    assert parsers.normalize_task_rows([]) == []
    assert parsers.normalize_task_rows(None) == []
    assert parsers.normalize_task_rows(load("tasks-list-empty.json")) == []


def test_normalize_task_rows_refuses_non_empty_records():
    # No real Atlas task record has ever been captured, so a schema must not
    # be guessed: non-empty record lists fail loudly.
    with pytest.raises(ClientError, match="no real Atlas task record"):
        parsers.normalize_task_rows([{"id": "1"}])


def test_normalize_task_rows_refuses_non_list():
    with pytest.raises(ClientError):
        parsers.normalize_task_rows({"not": "a list"})


def test_evaluate_tasks_route_redirect_to_dashboard_from_real_fixture():
    # Real capture: requesting /tasks landed on /dashboard (this account has
    # no task surface yet).
    state = load("tasks-route-dashboard.json")
    result = parsers.evaluate_tasks_route_state(
        state["final_url"], state["page_text"])
    assert result["has_tasks_surface"] is False
    assert "redirected" in result["reason"]


def test_evaluate_tasks_route_on_tasks_url_with_content():
    result = parsers.evaluate_tasks_route_state(
        "https://audit.atlascapture.io/tasks",
        "Task queue — nothing to do right now.")
    assert result["has_tasks_surface"] is True
    assert result["empty"] is True


def test_evaluate_tasks_route_redirect_to_login():
    result = parsers.evaluate_tasks_route_state(
        "https://audit.atlascapture.io/login", "")
    assert result["has_tasks_surface"] is False
    assert "login/verify" in result["reason"]
