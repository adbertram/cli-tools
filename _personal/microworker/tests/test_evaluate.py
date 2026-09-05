"""`evaluate apply`: the deterministic write half of the task-evaluator loop.

The evaluator agent produces JSON verdicts; this command validates and coerces
them into the ledger's `ai_can_handle` and `multimodal_required` columns.
Tests cover the write path, the missing-task path, the coercion contract, the
multimodal/ai capability consistency rules, and the strict-shape rejections.
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


def run_apply(project, runner, entries):
    path = write_verdict(project, entries)
    return runner.invoke(app, ["evaluate", "apply", str(path)])


def test_apply_sets_ai_can_handle_and_multimodal(project, runner):
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": True,
         "multimodal_required": True}])
    assert outcome.exit_code == 0, outcome.output
    result = json.loads(outcome.stdout)
    assert result["verdicts"] == 1
    assert result["updated"] == 1
    assert result["missing"] == []
    task = db.get_task("microworkers", "task-1")
    assert task["ai_can_handle"] == 1
    assert task["multimodal_required"] == 1


def test_apply_sets_multimodal_false(project, runner):
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": True,
         "multimodal_required": False}])
    assert outcome.exit_code == 0, outcome.output
    assert db.get_task("microworkers", "task-1")["multimodal_required"] == 0


def test_apply_normalizes_multimodal_null_when_not_ai_capable(project, runner):
    """A task no AI agent can do needs no agent modality: whatever the entry
    says, the stored `multimodal_required` is NULL."""
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": False,
         "multimodal_required": False}])
    assert outcome.exit_code == 0, outcome.output
    task = db.get_task("microworkers", "task-1")
    assert task["ai_can_handle"] == 0
    assert task["multimodal_required"] is None


def test_apply_reports_missing_task(project, runner):
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "ghost", "ai_can_handle": False,
         "multimodal_required": None}])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout)["updated"] == 0
    assert json.loads(outcome.stdout)["missing"] == ["microworkers/ghost"]


def test_apply_rejects_bad_ai_can_handle(project, runner):
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": "maybe",
         "multimodal_required": None}])
    assert outcome.exit_code == 2, outcome.output
    assert "ai_can_handle must be true, false, 1, 0, or null" in outcome.output


def test_apply_rejects_missing_multimodal_key(project, runner):
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": True}])
    assert outcome.exit_code == 2, outcome.output
    assert "'multimodal_required' is required" in outcome.output


def test_apply_rejects_multimodal_null_when_ai_capable(project, runner):
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": True,
         "multimodal_required": None}])
    assert outcome.exit_code == 2, outcome.output
    assert ("'multimodal_required' must be true or false when "
            "'ai_can_handle' is true") in outcome.output


def test_apply_normalizes_multimodal_true_when_not_ai_capable(project, runner):
    """The evaluator may write a modality against a human-gated role whose
    underlying work is visual; the script normalizes it to NULL instead of
    failing the file, keeping the column a clean tri-state."""
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": False,
         "multimodal_required": True}])
    assert outcome.exit_code == 0, outcome.output
    task = db.get_task("microworkers", "task-1")
    assert task["ai_can_handle"] == 0
    assert task["multimodal_required"] is None


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
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1", "ai_can_handle": None,
         "multimodal_required": None}])
    assert outcome.exit_code == 0, outcome.output
    task = db.get_task("microworkers", "task-1")
    assert task["ai_can_handle"] is None
    assert task["multimodal_required"] is None
