"""`evaluate apply`: the deterministic write half of the task-evaluator loop.

The evaluator agent produces JSON verdicts; this command validates and coerces
them into the ledger's `ai_can_handle` column. Tests cover the write path, the
missing-task path, the coercion contract, and the strict-shape rejections.
"""

from __future__ import annotations

import json

from microworker_cli import db
from microworker_cli.main import app


def seed(project, site="microworkers", task_id="task-1") -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO tasks (site, task_id, title, description, url, "
            "pay_amount, pay_currency, est_minutes, slots_open, expires_at, "
            "raw, first_seen_at, last_seen_at, first_seen_run_id, "
            "last_seen_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (site, task_id, "Title", None, None, None, None, None, None, None,
             json.dumps({"id": task_id}), "2026-09-01T00:00:00Z",
             "2026-09-01T00:00:00Z", "run", "run"))
        conn.commit()
    finally:
        conn.close()


def write_verdict(project, entries):
    path = project / "verdicts.json"
    path.write_text(json.dumps(entries))
    return path


def test_apply_sets_ai_can_handle(project, runner):
    seed(project)
    path = write_verdict(project, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": True}])
    outcome = runner.invoke(app, ["evaluate", "apply", str(path)])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout) == {
        "file": str(path), "verdicts": 1, "updated": 1, "missing": []}
    assert db.get_task("microworkers", "task-1")["ai_can_handle"] == 1


def test_apply_reports_missing_task(project, runner):
    seed(project)
    path = write_verdict(project, [
        {"site": "microworkers", "task_id": "ghost", "ai_can_handle": False}])
    outcome = runner.invoke(app, ["evaluate", "apply", str(path)])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout)["updated"] == 0
    assert json.loads(outcome.stdout)["missing"] == ["microworkers/ghost"]


def test_apply_rejects_bad_ai_can_handle(project, runner):
    seed(project)
    path = write_verdict(project, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": "maybe"}])
    outcome = runner.invoke(app, ["evaluate", "apply", str(path)])
    assert outcome.exit_code == 2, outcome.output
    assert "ai_can_handle must be true, false, 1, 0, or null" in outcome.output


def test_apply_rejects_non_list(project, runner):
    path = project / "verdicts.json"
    path.write_text(json.dumps({"site": "x"}))
    outcome = runner.invoke(app, ["evaluate", "apply", str(path)])
    assert outcome.exit_code == 2, outcome.output
    assert "must be a JSON array" in outcome.output


def test_apply_clears_with_null(project, runner):
    seed(project)
    db.set_task_ai_can_handle("microworkers", "task-1", 1)
    assert db.get_task("microworkers", "task-1")["ai_can_handle"] == 1
    path = write_verdict(project, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": None}])
    outcome = runner.invoke(app, ["evaluate", "apply", str(path)])
    assert outcome.exit_code == 0, outcome.output
    assert db.get_task("microworkers", "task-1")["ai_can_handle"] is None
