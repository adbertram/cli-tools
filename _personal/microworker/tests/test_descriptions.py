"""`descriptions apply`: the deterministic write half of the worker
description loop.

Site workers produce description text (real detail-page text via `enrich`,
or a short generated factual description); this command validates and fills
only ledger rows that carry no stored description yet. Tests cover the fill
path, the already-described skip, the missing-task path, and the strict-shape
rejections.
"""

from __future__ import annotations

import json

from microworker_cli import db
from microworker_cli.main import app


def seed(project, site="microworkers", task_id="task-1",
         description=None) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO tasks (site, task_id, title, description, url, "
            "pay_amount, pay_currency, est_minutes, slots_open, expires_at, "
            "raw, first_seen_at, last_seen_at, first_seen_run_id, "
            "last_seen_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (site, task_id, "Title", description, None, None, None, None,
             None, None, json.dumps({"id": task_id}), "2026-09-01T00:00:00Z",
             "2026-09-01T00:00:00Z", "run", "run"))
        conn.commit()
    finally:
        conn.close()


def run_apply(project, runner, entries):
    path = project / "descriptions.json"
    path.write_text(json.dumps(entries))
    return runner.invoke(app, ["descriptions", "apply", str(path)])


def test_apply_fills_empty_description(project, runner):
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1",
         "description": "Visit the page and answer the questions."}])
    assert outcome.exit_code == 0, outcome.output
    result = json.loads(outcome.stdout)
    assert result["entries"] == 1
    assert result["updated"] == 1
    assert result["skipped"] == 0
    assert result["missing"] == []
    assert db.get_task("microworkers", "task-1")["description"] \
        == "Visit the page and answer the questions."


def test_apply_skips_row_that_already_has_description(project, runner):
    seed(project, description="Already real text from the site detail page.")
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1",
         "description": "Generated fallback must not clobber real text."}])
    assert outcome.exit_code == 0, outcome.output
    result = json.loads(outcome.stdout)
    assert result["updated"] == 0
    assert result["skipped"] == 1
    assert db.get_task("microworkers", "task-1")["description"] \
        == "Already real text from the site detail page."


def test_apply_reports_missing_task(project, runner):
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "ghost", "description": "x"}])
    assert outcome.exit_code == 0, outcome.output
    result = json.loads(outcome.stdout)
    assert result["updated"] == 0
    assert result["missing"] == ["microworkers/ghost"]


def test_apply_rejects_empty_description(project, runner):
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1", "description": "  "}])
    assert outcome.exit_code == 2, outcome.output
    assert "'description' must be a non-empty string" in outcome.output


def test_apply_rejects_missing_key(project, runner):
    seed(project)
    outcome = run_apply(project, runner, [
        {"site": "microworkers", "task_id": "task-1"}])
    assert outcome.exit_code == 2, outcome.output
    assert "'description' must be a non-empty string" in outcome.output


def test_apply_rejects_non_list(project, runner):
    path = project / "descriptions.json"
    path.write_text(json.dumps({"site": "x"}))
    outcome = runner.invoke(app, ["descriptions", "apply", str(path)])
    assert outcome.exit_code == 2, outcome.output
    assert "must be a JSON array" in outcome.output
