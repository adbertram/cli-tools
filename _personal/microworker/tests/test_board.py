"""The board store and board API: columns, delegations, and the approval gate.

The dispatcher is exercised for real here, but through an echo harness --
`harness_command` is a shell one-liner that never invokes an agent. The
approval gate is the point under test: a `work` delegation finishing moves a
card to `review`, and only `approve` from `review` may create an `apply`
delegation, which is what moves the card to `done`.
"""

from __future__ import annotations

import json
import time

import pytest
from cli_tools_shared.exceptions import ClientError
from fastapi.testclient import TestClient

from microworker_cli import db
from microworker_cli.board import server

ECHO_HARNESS = "echo delegated-ok; echo {prompt} >/dev/null"
ECHO_APPLY_HARNESS = "echo applied-ok; echo {prompt} >/dev/null"

TASK = {
    "site": "microworkers",
    "task_id": "task-123",
    "title": "Categorize a set of images",
    "description": "Tag 100 product photos by room, style and material.",
    "url": "https://microworkers.example/tasks/123",
    "pay_amount": 0.35,
    "pay_currency": "USD",
    "est_minutes": 5,
    "slots_open": 120,
    "expires_at": "2026-09-30T00:00:00Z",
    "raw": {"id": "task-123"},
}


def seed_task(project) -> None:
    """One ledger row through the module's own connection, like a merge would."""
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO tasks (site, task_id, title, description, url, "
            "pay_amount, pay_currency, est_minutes, slots_open, expires_at, "
            "raw, first_seen_at, last_seen_at, first_seen_run_id, "
            "last_seen_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (TASK["site"], TASK["task_id"], TASK["title"], TASK["description"],
             TASK["url"], TASK["pay_amount"], TASK["pay_currency"],
             TASK["est_minutes"], TASK["slots_open"], TASK["expires_at"],
             json.dumps(TASK["raw"]), "2026-09-01T00:00:00Z",
             "2026-09-01T00:00:00Z", "run-a", "run-a"))
        conn.commit()
    finally:
        conn.close()


def wait_until(predicate, timeout: float = 20.0, step: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


@pytest.fixture
def board_client(project, monkeypatch):
    """A TestClient over the board app with a fast, echo-only dispatcher."""
    monkeypatch.setattr(server.Dispatcher, "POLL_SECONDS", 0.05)
    seed_task(project)
    with TestClient(server.app) as client:
        client.put("/api/settings", json={"settings": {
            "harness_command": ECHO_HARNESS,
            "work_prompt": "work $site $task_id",
            "apply_prompt": "apply $site $task_id",
        }})
        yield client


def card(board: dict, column: str | None = None):
    cards = board["cards"]
    if column:
        return [c for c in cards if c["column"] == column]
    return cards[0]


# --- the store -------------------------------------------------------------


def test_board_store_settings_roundtrip(project):
    assert db.board_settings() == {}
    db.board_set_settings({"harness_command": "claude -p \"{prompt}\""})
    assert db.board_settings()["harness_command"] == "claude -p \"{prompt}\""
    db.board_set_settings({"harness_command": "codex exec \"{prompt}\""})
    assert db.board_settings()["harness_command"] == "codex exec \"{prompt}\""


def test_board_store_rejects_unknown_column(project):
    with pytest.raises(ClientError, match="invalid board column"):
        db.board_upsert_task_state("site", "task", "nonsense",
                                   approved=False, updated_at="2026-09-01T00:00:00Z")


def test_board_store_rejects_unknown_delegation_fields(project):
    with pytest.raises(ClientError, match="cannot update delegation fields"):
        db.board_update_delegation(1, prompt="nope")


def test_board_store_delegation_lifecycle(project):
    now = "2026-09-01T00:00:00Z"
    delegation_id = db.board_create_delegation(
        "site", "task", "work", "do it", "", now)
    assert db.board_get_delegation(delegation_id)["status"] == "pending"
    assert db.board_pending_delegations()[0]["id"] == delegation_id
    db.board_update_delegation(
        delegation_id, status="running", pid=1, started_at=now,
        log_path="delegation-1.log")
    row = db.board_get_delegation(delegation_id)
    assert row["status"] == "running" and row["pid"] == 1
    db.board_update_delegation(
        delegation_id, status="done", exit_code=0, finished_at=now)
    assert db.board_pending_delegations() == []
    assert db.board_latest_delegations()[("site", "task")]["status"] == "done"


def test_board_store_rejects_unknown_kind(project):
    with pytest.raises(ClientError, match="invalid delegation kind"):
        db.board_create_delegation(
            "site", "task", "explode", "", "", "2026-09-01T00:00:00Z")


# --- the API ---------------------------------------------------------------


def test_board_shows_ledger_and_default_column(board_client):
    board = board_client.get("/api/board").json()
    assert board["meta"]["replica_error"] is None
    assert board["meta"]["task_count"] == 1
    assert card(board)["site"] == TASK["site"]
    assert card(board)["column"] == "backlog"
    assert card(board)["approved"] is False
    assert card(board)["description"] == TASK["description"]


def test_move_card_and_unknown_card(board_client):
    response = board_client.post("/api/cards/move", json={
        "site": TASK["site"], "task_id": TASK["task_id"], "column": "ready"})
    assert response.status_code == 200
    assert card(board_client.get("/api/board").json())["column"] == "ready"

    response = board_client.post("/api/cards/move", json={
        "site": TASK["site"], "task_id": TASK["task_id"], "column": "nonsense"})
    assert response.status_code == 400

    response = board_client.post("/api/cards/move", json={
        "site": "ghost", "task_id": "none", "column": "ready"})
    assert response.status_code == 404


def test_delegation_flow_and_approval_gate(board_client):
    # A fresh card starts in backlog; approve is refused there.
    response = board_client.post("/api/cards/approve", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})
    assert response.status_code == 409

    # Delegate: the dispatcher claims it and runs the echo harness.
    response = board_client.post("/api/cards/delegate", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})
    assert response.status_code == 200
    delegation_id = response.json()["id"]

    def finished():
        row = board_client.get(f"/api/delegations/{delegation_id}").json()
        return row["status"] in ("done", "failed")

    assert wait_until(finished), "dispatcher never finished the echo delegation"
    detail = board_client.get(f"/api/delegations/{delegation_id}").json()
    assert detail["status"] == "done" and detail["exit_code"] == 0
    assert "delegated-ok" in detail["log_tail"]

    # A finished work delegation moves the card to review.
    board = board_client.get("/api/board").json()
    assert card(board)["column"] == "review"
    assert card(board)["approved"] is False
    assert card(board)["delegation"]["kind"] == "work"

    # Approve from review: the apply delegation runs, the card lands done.
    response = board_client.post("/api/cards/approve", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})
    assert response.status_code == 200
    apply_id = response.json()["id"]

    def applied():
        row = board_client.get(f"/api/delegations/{apply_id}").json()
        return row["status"] in ("done", "failed")

    assert wait_until(applied), "dispatcher never finished the apply delegation"
    board = board_client.get("/api/board").json()
    assert card(board)["column"] == "done"
    assert card(board)["approved"] is True

    # A second approve is refused: already approved.
    response = board_client.post("/api/cards/approve", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})
    assert response.status_code == 409


def test_delegate_conflict_and_kill_pending(board_client, monkeypatch):
    monkeypatch.setattr(server.Dispatcher, "POLL_SECONDS", 30)  # keep it pending
    first = board_client.post("/api/cards/delegate", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})
    assert first.status_code == 200
    second = board_client.post("/api/cards/delegate", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})
    assert second.status_code == 409

    killed = board_client.post(
        f"/api/delegations/{first.json()['id']}/kill")
    assert killed.status_code == 200
    row = board_client.get(f"/api/delegations/{first.json()['id']}").json()
    assert row["status"] == "failed"


def test_columns_include_working(board_client):
    columns = board_client.get("/api/board").json()["columns"]
    assert columns.index("delegated") + 1 == columns.index("working")
    assert columns.index("working") + 1 == columns.index("review")


def test_card_walks_delegated_working_review(board_client):
    # A slow harness makes the `working` state observable: the dispatcher
    # flips the card the moment the agent starts, before it finishes.
    board_client.put("/api/settings", json={"settings": {
        "harness_command": "sleep 2; echo slow-ok; echo {prompt} >/dev/null"}})
    response = board_client.post("/api/cards/delegate", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})
    delegation_id = response.json()["id"]

    def column():
        return card(board_client.get("/api/board").json())["column"]

    assert wait_until(lambda: column() == "working", timeout=10), \
        f"card never entered working (column={column()})"
    detail = board_client.get(f"/api/delegations/{delegation_id}").json()
    assert detail["status"] == "running"

    def finished():
        row = board_client.get(f"/api/delegations/{delegation_id}").json()
        return row["status"] in ("done", "failed")

    assert wait_until(finished, timeout=20), "slow delegation never finished"
    assert column() == "review"
    assert "slow-ok" in board_client.get(
        f"/api/delegations/{delegation_id}").json()["log_tail"]


def test_harness_site_placeholder_is_substituted(board_client):
    board_client.put("/api/settings", json={"settings": {
        "harness_command": "echo site-is-{site} task-is-{task_id}; echo {prompt} >/dev/null"}})
    response = board_client.post("/api/cards/delegate", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})
    delegation_id = response.json()["id"]

    def finished():
        row = board_client.get(f"/api/delegations/{delegation_id}").json()
        return row["status"] in ("done", "failed")

    assert wait_until(finished), "site-substitution delegation never finished"
    log = board_client.get(f"/api/delegations/{delegation_id}").json()["log_tail"]
    assert f"site-is-{TASK['site']}" in log
    assert f"task-is-{TASK['task_id']}" in log


def test_failed_work_delegation_returns_card_to_delegated(board_client):
    board_client.put("/api/settings", json={"settings": {
        "harness_command": "echo {prompt} >/dev/null; exit 1"}})
    response = board_client.post("/api/cards/delegate", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})
    delegation_id = response.json()["id"]

    def failed():
        row = board_client.get(f"/api/delegations/{delegation_id}").json()
        return row["status"] in ("done", "failed")

    assert wait_until(failed), "failing delegation never settled"
    row = board_client.get(f"/api/delegations/{delegation_id}").json()
    assert row["status"] == "failed" and row["exit_code"] == 1
    assert card(board_client.get("/api/board").json())["column"] == "delegated"


def test_failed_apply_withdraws_approval(board_client):
    board_client.put("/api/settings", json={"settings": {
        "harness_command": "echo {prompt} >/dev/null"}})  # work succeeds
    board_client.post("/api/cards/delegate", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})

    def in_review():
        return card(board_client.get("/api/board").json())["column"] == "review"

    assert wait_until(in_review), "work delegation never reached review"

    board_client.put("/api/settings", json={"settings": {
        "harness_command": "echo {prompt} >/dev/null; exit 1"}})  # apply fails
    approved = board_client.post("/api/cards/approve", json={
        "site": TASK["site"], "task_id": TASK["task_id"]})
    assert approved.status_code == 200
    apply_id = approved.json()["id"]

    def applied():
        row = board_client.get(f"/api/delegations/{apply_id}").json()
        return row["status"] in ("done", "failed")

    assert wait_until(applied), "apply delegation never settled"
    board = board_client.get("/api/board").json()
    assert card(board)["column"] == "review"
    assert card(board)["approved"] is False


def test_board_state_cli_reads_and_writes(project, runner):
    from microworker_cli.main import app
    outcome = runner.invoke(app, ["board", "state", TASK["site"], TASK["task_id"]])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout)["column"] == "backlog"

    outcome = runner.invoke(
        app, ["board", "state", TASK["site"], TASK["task_id"], "working"])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout)["column"] == "working"

    outcome = runner.invoke(app, ["board", "state", TASK["site"], TASK["task_id"]])
    assert json.loads(outcome.stdout)["column"] == "working"
    assert json.loads(outcome.stdout)["approved"] is False

    outcome = runner.invoke(
        app, ["board", "state", TASK["site"], TASK["task_id"], "nonsense"])
    assert outcome.exit_code == 2, outcome.output


def test_settings_roundtrip(board_client):
    settings = board_client.get("/api/settings").json()
    assert settings["harness_command"] == ECHO_HARNESS
    board_client.put("/api/settings", json={"settings": {
        "refresh_seconds": "42"}})
    settings = board_client.get("/api/settings").json()
    assert settings["refresh_seconds"] == "42"
    assert settings["harness_command"] == ECHO_HARNESS  # untouched keys stay


def test_index_and_static_assets(board_client):
    page = board_client.get("/")
    assert page.status_code == 200
    assert "MicroWorker Board" in page.text
    sortable = board_client.get("/static/sortable.min.js")
    assert sortable.status_code == 200
    assert "Sortable" in sortable.text
