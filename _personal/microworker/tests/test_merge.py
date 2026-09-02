"""`merge`: all sites required, adapters applied, one transaction into SQLite."""

from __future__ import annotations

import json

import pytest
from cli_tools_shared.exceptions import ClientError

from conftest import SITES
from microworker_cli import adapters, db, envelope, merge, paths, schema
from microworker_cli.main import app

RUN = "20260902T000000Z"
LATER_RUN = "20260903T000000Z"


def write_all_envelopes(ok_sites: dict[str, list] | None = None, run_id: str = RUN):
    """One envelope per configured site: `ok` with the given tasks, else no_account."""
    ok_sites = ok_sites if ok_sites is not None else {}
    for name in SITES:
        if name in ok_sites:
            data = envelope.build(name, envelope.OK, None, ok_sites[name])
        else:
            data = envelope.build(name, envelope.NO_ACCOUNT, "fixture", [])
        envelope.write(paths.envelope_path(run_id, name), data)


def test_missing_envelopes_listed_and_no_database_created(project):
    write_all_envelopes()
    paths.envelope_path(RUN, "mercor").unlink()
    paths.envelope_path(RUN, "outlier").unlink()
    with pytest.raises(ClientError, match="no envelope for: mercor, outlier"):
        merge.merge(RUN)
    assert not paths.db_path().exists()


def test_ok_envelope_without_adapter_fails(project):
    write_all_envelopes({"oneforma": [{"id": 1}]})
    with pytest.raises(ClientError, match="no adapter for site 'oneforma'"):
        merge.merge(RUN)
    assert not paths.db_path().exists()


def test_invalid_envelope_fails(project):
    write_all_envelopes()
    path = paths.envelope_path(RUN, "mercor")
    data = json.loads(path.read_text())
    data["status"] = "bogus"
    path.write_text(json.dumps(data))
    with pytest.raises(schema.SchemaError, match="mercor.json"):
        merge.merge(RUN)
    assert not paths.db_path().exists()


def test_site_name_mismatch_fails(project):
    write_all_envelopes()
    path = paths.envelope_path(RUN, "mercor")
    data = json.loads(path.read_text())
    data["site"] = "microworkers"
    path.write_text(json.dumps(data))
    with pytest.raises(ClientError, match="claims site 'microworkers'"):
        merge.merge(RUN)


def test_bad_raw_task_fails_whole_merge(project, microworkers_record):
    broken = dict(microworkers_record, campaign_id=None)
    write_all_envelopes({"microworkers": [microworkers_record, broken]})
    with pytest.raises(ClientError, match="campaign_id"):
        merge.merge(RUN)
    assert not paths.db_path().exists()


def test_schema_invalid_task_aborts_write_before_the_database_exists(
        project, monkeypatch, microworkers_record):
    monkeypatch.setitem(
        adapters.ADAPTERS, "microworkers",
        lambda raw: dict(adapters.microworkers.to_task(raw), pay_amount="free"))
    write_all_envelopes({"microworkers": [microworkers_record]})
    with pytest.raises(schema.SchemaError, match="tasks\\[0\\]"):
        merge.merge(RUN)
    assert not paths.db_path().exists()


def test_schema_invalid_task_leaves_an_existing_database_untouched(
        project, monkeypatch, clock, microworkers_record):
    write_all_envelopes({"microworkers": [microworkers_record]})
    merge.merge(RUN)
    before = db.list_tasks()

    clock.set("2026-09-03T00:00:00Z")
    write_all_envelopes({"microworkers": [microworkers_record]}, run_id=LATER_RUN)
    monkeypatch.setitem(
        adapters.ADAPTERS, "microworkers",
        lambda raw: dict(adapters.microworkers.to_task(raw), task_id=""))
    with pytest.raises(schema.SchemaError):
        merge.merge(LATER_RUN)

    assert db.list_tasks() == before
    assert [run["run_id"] for run in db.list_runs()] == [RUN]


def test_first_merge_inserts_rows_and_run_summary(project, clock, microworkers_record):
    clock.set("2026-09-02T00:00:00Z")
    write_all_envelopes({"microworkers": [microworkers_record]})
    summary = merge.merge(RUN)

    assert summary == {
        "run_id": RUN,
        "db_path": str(paths.db_path()),
        "sites": {name: ("ok" if name == "microworkers" else "no_account")
                  for name in SITES},
        "task_count": 1,
        "inserted": 1,
        "updated": 0,
    }
    task = db.get_task("microworkers", microworkers_record["campaign_id"])
    assert task == {
        "site": "microworkers",
        "task_id": microworkers_record["campaign_id"],
        "title": microworkers_record["title"],
        "url": microworkers_record["url"],
        "pay_amount": 0.10,
        "pay_currency": "USD",
        "est_minutes": 5,
        "slots_open": 15,
        "expires_at": None,
        "raw": microworkers_record,
        "first_seen_at": "2026-09-02T00:00:00Z",
        "last_seen_at": "2026-09-02T00:00:00Z",
        "first_seen_run_id": RUN,
        "last_seen_run_id": RUN,
    }
    run = db.get_run(RUN)
    assert run["merged_at"] == "2026-09-02T00:00:00Z"
    assert run["task_count"] == 1 and run["inserted"] == 1 and run["updated"] == 0
    assert set(run["sites"]) == set(SITES)
    assert run["sites"]["microworkers"] == {
        "status": "ok", "error": None,
        "fetched_at": "2026-09-02T00:00:00Z", "task_count": 1}
    assert run["sites"]["mercor"]["error"] == "fixture"


def test_repeated_task_in_one_run_writes_one_row(project, microworkers_record):
    write_all_envelopes({"microworkers": [microworkers_record, microworkers_record]})
    summary = merge.merge(RUN)
    assert summary["task_count"] == 2
    assert summary["inserted"] == 1 and summary["updated"] == 0
    assert len(db.list_tasks()) == 1


def test_later_run_updates_last_seen_and_preserves_first_seen(
        project, clock, microworkers_record):
    clock.set("2026-09-02T00:00:00Z")
    write_all_envelopes({"microworkers": [microworkers_record]})
    merge.merge(RUN)

    clock.set("2026-09-03T00:00:00Z")
    changed = dict(microworkers_record, title="Renamed", payment="$0.25")
    write_all_envelopes({"microworkers": [changed]}, run_id=LATER_RUN)
    summary = merge.merge(LATER_RUN)

    assert summary["inserted"] == 0 and summary["updated"] == 1
    task = db.get_task("microworkers", microworkers_record["campaign_id"])
    assert task["first_seen_at"] == "2026-09-02T00:00:00Z"
    assert task["first_seen_run_id"] == RUN
    assert task["last_seen_at"] == "2026-09-03T00:00:00Z"
    assert task["last_seen_run_id"] == LATER_RUN
    assert task["title"] == "Renamed"
    assert task["pay_amount"] == 0.25
    assert task["raw"] == changed
    assert [run["run_id"] for run in db.list_runs()] == [LATER_RUN, RUN]


def test_remerging_the_same_run_id_is_idempotent(project, clock, microworkers_record):
    write_all_envelopes({"microworkers": [microworkers_record]})
    first = merge.merge(RUN)
    tasks_after_first = db.list_tasks()

    second = merge.merge(RUN)
    assert first["inserted"] == 1 and second["inserted"] == 0
    assert second["updated"] == 1
    assert db.list_tasks() == tasks_after_first
    assert [run["run_id"] for run in db.list_runs()] == [RUN]
    assert set(db.get_run(RUN)["sites"]) == set(SITES)


def test_cli_merge_prints_summary(project, runner):
    write_all_envelopes()
    outcome = runner.invoke(app, ["merge", RUN])
    assert outcome.exit_code == 0, outcome.output
    summary = json.loads(outcome.stdout)
    assert summary["task_count"] == 0
    assert summary["db_path"] == str(paths.db_path())
    assert paths.db_path().is_file()


def test_cli_merge_missing_run_exits_2(project, runner):
    outcome = runner.invoke(app, ["merge", "never-ran"])
    assert outcome.exit_code == 2, outcome.output
    assert "no envelope for" in outcome.output
