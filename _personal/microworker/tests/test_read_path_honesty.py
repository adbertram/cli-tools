"""The read side must not answer a question it was not asked.

Three false negatives are covered here, all of which previously exited 0 with
plausible-looking output:

  * `--limit` truncating a larger result with nothing anywhere saying so, so
    "100 tasks" and "the first 100 of 2000 tasks" printed identically.
  * a misspelled `--filter` field returning `[]`, so "that field does not
    exist" was indistinguishable from "no task matched".
  * a misspelled `--properties` name emitting that key as `null` on every row,
    so a typo read as "the field exists and is empty".

Plus the two error classes that escaped the exit-2 contract entirely: a
`config.json` that is not JSON, and a database the SQLite engine refuses.
"""

from __future__ import annotations

import json

import pytest

from conftest import SITES
from microworker_cli import db, envelope, merge, paths
from microworker_cli.main import app

RUN = "20260902T000000Z"


def merged_tasks(project, microworkers_record, count: int) -> None:
    """A ledger holding `count` distinct tasks from one merge."""
    tasks = [dict(microworkers_record, campaign_id=f"task{index:05d}")
             for index in range(count)]
    for name in SITES:
        data = (envelope.build(name, envelope.OK, None, tasks)
                if name == "microworkers"
                else envelope.build(name, envelope.NO_ACCOUNT, "fixture", []))
        envelope.write(paths.envelope_path(RUN, name), data)
    merge.merge(RUN)


@pytest.fixture
def big_ledger(project, microworkers_record):
    merged_tasks(project, microworkers_record, 250)
    return project


def test_tasks_list_announces_truncation_on_stderr(runner, big_ledger):
    outcome = runner.invoke(app, ["tasks", "list"])
    assert outcome.exit_code == 0, outcome.output
    rows = json.loads(outcome.stdout)
    assert len(rows) == 100
    assert "Showing 100 of 250 tasks" in outcome.stderr


def test_untruncated_list_says_nothing(runner, big_ledger):
    outcome = runner.invoke(app, ["tasks", "list", "--limit", "250"])
    assert outcome.exit_code == 0, outcome.output
    assert len(json.loads(outcome.stdout)) == 250
    assert outcome.stderr == ""


def test_truncation_notice_never_reaches_stdout(runner, big_ledger):
    """stdout stays data only, so piping into a JSON reader is unaffected."""
    outcome = runner.invoke(app, ["tasks", "list", "--limit", "3"])
    assert len(json.loads(outcome.stdout)) == 3
    assert "Showing" not in outcome.stdout


def test_truncation_counts_rows_after_filtering(runner, big_ledger):
    outcome = runner.invoke(app, ["tasks", "list", "--filter",
                                 "task_id:startswith:task0000", "--limit", "4"])
    assert outcome.exit_code == 0, outcome.output
    assert "Showing 4 of 10 tasks" in outcome.stderr


def test_runs_list_announces_truncation_too(project, runner, microworkers_record):
    for index in range(5):
        run_id = f"2026090{index}T000000Z"
        for name in SITES:
            envelope.write(paths.envelope_path(run_id, name),
                           envelope.build(name, envelope.NO_ACCOUNT, "fixture", []))
        merge.merge(run_id)
    outcome = runner.invoke(app, ["runs", "list", "--limit", "2"])
    assert outcome.exit_code == 0, outcome.output
    assert len(json.loads(outcome.stdout)) == 2
    assert "Showing 2 of 5 runs" in outcome.stderr


@pytest.mark.parametrize("argv, bad", [
    (["tasks", "list", "--filter", "pay_amt:gt:1"], "pay_amt"),
    (["tasks", "list", "--filter", "titel:eq:x"], "titel"),
    (["runs", "list", "--filter", "runid:eq:x"], "runid"),
    (["sites", "list", "--filter", "clii:eq:x"], "clii"),
])
def test_unknown_filter_field_exits_2_instead_of_returning_empty(
        runner, big_ledger, argv, bad):
    outcome = runner.invoke(app, argv)
    assert outcome.exit_code == 2, outcome.output
    assert bad in outcome.output
    assert outcome.stdout.strip() == ""


def test_a_real_filter_field_still_works(runner, big_ledger):
    rows = json.loads(runner.invoke(
        app, ["tasks", "list", "--filter", "site:eq:microworkers",
              "--limit", "5"]).stdout)
    assert len(rows) == 5


@pytest.mark.parametrize("argv, bad", [
    (["tasks", "list", "--properties", "task_id,pay_amout"], "pay_amout"),
    (["tasks", "get", "microworkers", "task00000", "--properties", "titel"], "titel"),
    (["runs", "list", "--properties", "run_id,insertd"], "insertd"),
    (["runs", "get", RUN, "--properties", "siets"], "siets"),
    (["sites", "list", "--properties", "name,clii"], "clii"),
    (["sites", "get", "humanrail", "--properties", "acount"], "acount"),
])
def test_unknown_property_exits_2_instead_of_emitting_null(runner, big_ledger, argv, bad):
    outcome = runner.invoke(app, argv)
    assert outcome.exit_code == 2, outcome.output
    assert bad in outcome.output
    assert "available fields" in outcome.output
    assert outcome.stdout.strip() == ""


def test_runs_get_still_accepts_a_nested_site_property(runner, big_ledger):
    row = json.loads(runner.invoke(
        app, ["runs", "get", RUN, "--properties", "run_id,sites.microworkers"]).stdout)
    assert row["run_id"] == RUN
    assert row["sites.microworkers"]["status"] == "ok"


def test_a_real_property_that_is_null_still_projects(runner, big_ledger):
    """The allowlist rejects typos; it does not hide a real field's null."""
    rows = json.loads(runner.invoke(
        app, ["tasks", "list", "--limit", "1", "--properties", "task_id,expires_at"]).stdout)
    assert rows[0]["expires_at"] is None


def test_unparseable_config_json_exits_2_naming_the_path(project, runner):
    path = paths.config_path()
    path.write_text('{"sites": {"microworkers": {"cli": "microworkers",')
    outcome = runner.invoke(app, ["sites", "list"])
    assert outcome.exit_code == 2, outcome.output
    assert str(path) in outcome.output
    assert "is not valid JSON" in outcome.output
    assert "line 1" in outcome.output


def test_a_database_the_engine_refuses_exits_2_naming_the_path(
        project, runner, microworkers_record):
    merged_tasks(project, microworkers_record, 1)
    paths.db_path().write_bytes(b"this is not a SQLite database" * 100)
    outcome = runner.invoke(app, ["tasks", "list"])
    assert outcome.exit_code == 2, outcome.output
    assert str(paths.db_path()) in outcome.output


def test_ok_envelope_for_an_unimplemented_adapter_exits_2(project, runner):
    """`taskerdata` has no verified record shape; that is exit 2, not exit 1."""
    for name in SITES:
        data = (envelope.build(name, envelope.OK, None, [{"id": 1}])
                if name == "taskerdata"
                else envelope.build(name, envelope.NO_ACCOUNT, "fixture", []))
        envelope.write(paths.envelope_path(RUN, name), data)
    outcome = runner.invoke(app, ["merge", RUN])
    assert outcome.exit_code == 2, outcome.output
    assert "taskerdata adapter is not implemented" in outcome.output
    assert not paths.db_path().exists()


def test_task_and_run_field_lists_track_the_database_columns():
    """The allowlists are derived, so a new column cannot be left out of them."""
    from microworker_cli import main

    assert main.TASK_FIELDS == db.TASK_COLUMNS
    assert main.RUN_FIELDS == db.RUN_COLUMNS
    assert main.RUN_GET_FIELDS == db.RUN_COLUMNS + ("sites",)
    assert set(main.SITE_FIELDS) == {"name", "cli", "account", "lastpass_item",
                                     "auth_command"}


def test_unconfigured_envelope_in_the_run_directory_fails_the_merge(project, runner):
    """A stray `<site>.json` must not be silently skipped."""
    for name in SITES:
        envelope.write(paths.envelope_path(RUN, name),
                       envelope.build(name, envelope.NO_ACCOUNT, "fixture", []))
    stray = paths.run_dir(RUN) / "microworkers2.json"
    stray.write_text(json.dumps({
        "site": "microworkers2", "status": "ok",
        "fetched_at": "2026-09-02T00:00:00Z", "error": None,
        "tasks": [{"campaign_id": "x"}]}))
    outcome = runner.invoke(app, ["merge", RUN])
    assert outcome.exit_code == 2, outcome.output
    assert "microworkers2" in outcome.output
    assert not paths.db_path().exists()


def test_a_complete_run_directory_still_merges(project, runner):
    for name in SITES:
        envelope.write(paths.envelope_path(RUN, name),
                       envelope.build(name, envelope.NO_ACCOUNT, "fixture", []))
    assert runner.invoke(app, ["merge", RUN]).exit_code == 0


def test_a_non_envelope_file_beside_the_envelopes_is_named(project, runner):
    """Only `*.json` is claimed to be an envelope; the check covers all of them."""
    for name in SITES:
        envelope.write(paths.envelope_path(RUN, name),
                       envelope.build(name, envelope.NO_ACCOUNT, "fixture", []))
    (paths.run_dir(RUN) / "notes.txt").write_text("scratch")
    assert runner.invoke(app, ["merge", RUN]).exit_code == 0
    (paths.run_dir(RUN) / "merged.json").write_text("{}")
    outcome = runner.invoke(app, ["merge", RUN])
    assert outcome.exit_code == 2, outcome.output
    assert "merged" in outcome.output
