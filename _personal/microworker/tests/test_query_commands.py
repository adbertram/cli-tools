"""`tasks list|get` and `runs list|get`: the read side of the task database.

Everything here goes through the CLI, because the shape these commands print --
`raw` parsed in JSON and absent from the table -- is the contract, not the row
the database happens to hold.
"""

from __future__ import annotations

import json

import pytest

from conftest import SITES
from microworker_cli import envelope, merge, paths
from microworker_cli.main import app

RUN = "20260902T000000Z"
LATER_RUN = "20260903T000000Z"


def write_envelopes(ok_tasks: list, run_id: str):
    for name in SITES:
        if name == "microworkers":
            data = envelope.build(name, envelope.OK, None, ok_tasks)
        else:
            data = envelope.build(name, envelope.NO_ACCOUNT, "fixture", [])
        envelope.write(paths.envelope_path(run_id, name), data)


@pytest.fixture
def two_runs(project, clock, microworkers_record):
    """A database holding two tasks across two merges, with distinct last-seen times.

    The first run merges the frozen record; the second merges a cheaper, newer
    task only, so the older row keeps the older `last_seen_at` and list ordering
    is observable.
    """
    clock.set("2026-09-02T00:00:00Z")
    write_envelopes([microworkers_record], RUN)
    merge.merge(RUN)

    clock.set("2026-09-03T00:00:00Z")
    newer = dict(microworkers_record, campaign_id="cheapcafe01",
                 title="Newer task", payment="$1.50", ttf_minutes=9)
    write_envelopes([newer], LATER_RUN)
    merge.merge(LATER_RUN)
    return microworkers_record, newer


def run_json(runner, argv):
    outcome = runner.invoke(app, argv)
    assert outcome.exit_code == 0, outcome.output
    return json.loads(outcome.stdout)


def test_tasks_list_newest_last_seen_first_with_parsed_raw(runner, two_runs):
    older, newer = two_runs
    rows = run_json(runner, ["tasks", "list"])
    assert [row["task_id"] for row in rows] == [newer["campaign_id"], older["campaign_id"]]
    assert rows[0]["raw"] == newer
    assert rows[0]["last_seen_run_id"] == LATER_RUN
    assert rows[1]["first_seen_run_id"] == RUN
    assert list(rows[0]) == [
        "site", "task_id", "title", "description", "url", "pay_amount",
        "pay_currency", "est_minutes", "slots_open", "expires_at", "raw",
        "first_seen_at", "last_seen_at", "first_seen_run_id", "last_seen_run_id",
        "ai_can_handle", "multimodal_required"]


def test_tasks_list_filter_limit_properties(runner, two_runs):
    older, newer = two_runs
    rows = run_json(runner, ["tasks", "list", "--filter", "pay_amount:gt:1",
                             "--limit", "5", "--properties", "task_id,pay_amount"])
    assert rows == [{"task_id": newer["campaign_id"], "pay_amount": 1.5}]


def test_tasks_list_limit(runner, two_runs):
    assert len(run_json(runner, ["tasks", "list", "--limit", "1"])) == 1


def test_tasks_list_table_drops_raw(runner, two_runs, monkeypatch):
    # The shared table printer shows the first six columns, so `raw` would not
    # reach the terminal by default anyway. `--properties` is what makes the
    # drop observable: ask for it explicitly and it is still not rendered,
    # because a whole nested site record has no readable table cell. With
    # `description` in the contract the first six columns are site, task_id,
    # title, description, url, pay_amount.
    monkeypatch.setenv("COLUMNS", "300")
    outcome = runner.invoke(app, ["tasks", "list", "--table"])
    assert outcome.exit_code == 0, outcome.output
    assert "Task Id" in outcome.stdout and "Description" in outcome.stdout
    assert "Pay Currency" not in outcome.stdout  # seventh column, cut off

    outcome = runner.invoke(app, ["tasks", "list", "--table",
                                  "--properties", "task_id,raw,site"])
    assert outcome.exit_code == 0, outcome.output
    assert "Task Id" in outcome.stdout and "Site" in outcome.stdout
    assert "Raw" not in outcome.stdout
    assert "positions_total" not in outcome.stdout


def test_tasks_list_bad_filter_exits_nonzero(runner, two_runs):
    assert runner.invoke(app, ["tasks", "list", "--filter", "nonsense"]).exit_code != 0


def test_tasks_list_empty_database_is_an_empty_list(project, runner):
    write_envelopes([], RUN)
    merge.merge(RUN)
    assert run_json(runner, ["tasks", "list"]) == []


def test_tasks_get(runner, two_runs):
    older, _ = two_runs
    row = run_json(runner, ["tasks", "get", "microworkers", older["campaign_id"]])
    assert row["title"] == older["title"]
    assert row["raw"] == older
    assert row["first_seen_at"] == "2026-09-02T00:00:00Z"


def test_tasks_get_properties_and_table(runner, two_runs):
    older, _ = two_runs
    row = run_json(runner, ["tasks", "get", "microworkers", older["campaign_id"],
                            "--properties", "task_id,pay_amount"])
    assert row == {"task_id": older["campaign_id"], "pay_amount": 0.1}

    outcome = runner.invoke(app, ["tasks", "get", "microworkers", older["campaign_id"],
                                  "--properties", "title", "--table"])
    assert outcome.exit_code == 0, outcome.output
    assert "Field" in outcome.stdout and "title" in outcome.stdout


def test_tasks_get_unknown_exits_2(runner, two_runs):
    outcome = runner.invoke(app, ["tasks", "get", "microworkers", "nope"])
    assert outcome.exit_code == 2, outcome.output
    assert "no task 'nope' for site 'microworkers'" in outcome.output


def test_runs_list_newest_first(runner, two_runs):
    rows = run_json(runner, ["runs", "list"])
    assert [row["run_id"] for row in rows] == [LATER_RUN, RUN]
    assert list(rows[0]) == ["run_id", "merged_at", "task_count", "inserted",
                             "updated", "skipped_stale"]
    assert rows[0] == {"run_id": LATER_RUN, "merged_at": "2026-09-03T00:00:00Z",
                       "task_count": 1, "inserted": 1, "updated": 0,
                       "skipped_stale": 0}


def test_runs_list_filter_limit_properties_and_table(runner, two_runs, monkeypatch):
    rows = run_json(runner, ["runs", "list", "--filter", f"run_id:eq:{RUN}",
                             "--limit", "5", "--properties", "run_id,task_count"])
    assert rows == [{"run_id": RUN, "task_count": 1}]
    assert len(run_json(runner, ["runs", "list", "--limit", "1"])) == 1

    monkeypatch.setenv("COLUMNS", "300")
    outcome = runner.invoke(app, ["runs", "list", "--table"])
    assert outcome.exit_code == 0, outcome.output
    assert "Merged At" in outcome.stdout and LATER_RUN in outcome.stdout


def test_runs_list_bad_filter_exits_nonzero(runner, two_runs):
    assert runner.invoke(app, ["runs", "list", "--filter", "nonsense"]).exit_code != 0


def test_runs_get_carries_every_site_summary(runner, two_runs):
    row = run_json(runner, ["runs", "get", RUN])
    assert row["merged_at"] == "2026-09-02T00:00:00Z"
    assert set(row["sites"]) == set(SITES)
    assert row["sites"]["microworkers"] == {
        "status": "ok", "error": None,
        "fetched_at": "2026-09-02T00:00:00Z", "task_count": 1,
        "unparsed_payments": 0}
    assert row["sites"]["mercor"] == {
        "status": "no_account", "error": "fixture",
        "fetched_at": "2026-09-02T00:00:00Z", "task_count": 0,
        "unparsed_payments": 0}


def test_runs_get_properties_and_table(runner, two_runs):
    assert run_json(runner, ["runs", "get", RUN, "--properties", "run_id,inserted"]) == {
        "run_id": RUN, "inserted": 1}
    outcome = runner.invoke(app, ["runs", "get", RUN, "--table"])
    assert outcome.exit_code == 0, outcome.output
    assert "Field" in outcome.stdout and "merged_at" in outcome.stdout


def test_runs_get_unknown_exits_2(runner, two_runs):
    outcome = runner.invoke(app, ["runs", "get", "never-merged"])
    assert outcome.exit_code == 2, outcome.output
    assert "no run 'never-merged'" in outcome.output


@pytest.mark.parametrize("argv", [
    ["tasks", "list"],
    ["tasks", "get", "microworkers", "1"],
    ["runs", "list"],
    ["runs", "get", RUN],
], ids=lambda argv: " ".join(argv))
def test_query_without_a_database_exits_2(project, runner, argv):
    assert not paths.db_path().exists()
    outcome = runner.invoke(app, argv)
    assert outcome.exit_code == 2, outcome.output
    assert str(paths.db_path()) in outcome.output
    assert "microworker merge" in outcome.output
