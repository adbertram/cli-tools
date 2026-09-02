"""`merge`: all sites required, adapters applied, merged.json validates."""

from __future__ import annotations

import json

import pytest
from cli_tools_shared.exceptions import ClientError

from conftest import SITES
from microworker_cli import envelope, merge, paths, schema
from microworker_cli.main import app

RUN = "20260902T000000Z"


def write_all_envelopes(ok_sites: dict[str, list] | None = None):
    """One envelope per configured site: `ok` with the given tasks, else no_account."""
    ok_sites = ok_sites if ok_sites is not None else {}
    for name in SITES:
        if name in ok_sites:
            data = envelope.build(name, envelope.OK, None, ok_sites[name])
        else:
            data = envelope.build(name, envelope.NO_ACCOUNT, "fixture", [])
        envelope.write(paths.envelope_path(RUN, name), data)


def test_missing_envelopes_listed_and_nothing_written(project):
    write_all_envelopes()
    paths.envelope_path(RUN, "toloka").unlink()
    paths.envelope_path(RUN, "outlier").unlink()
    with pytest.raises(ClientError, match="no envelope for: toloka, outlier"):
        merge.merge(RUN)
    assert not paths.merged_path(RUN).exists()


def test_ok_envelope_without_adapter_fails(project):
    write_all_envelopes({"oneforma": [{"id": 1}]})
    with pytest.raises(ClientError, match="no adapter for site 'oneforma'"):
        merge.merge(RUN)
    assert not paths.merged_path(RUN).exists()


def test_invalid_envelope_fails(project):
    write_all_envelopes()
    path = paths.envelope_path(RUN, "toloka")
    data = json.loads(path.read_text())
    data["status"] = "bogus"
    path.write_text(json.dumps(data))
    with pytest.raises(schema.SchemaError, match="toloka.json"):
        merge.merge(RUN)


def test_site_name_mismatch_fails(project):
    write_all_envelopes()
    path = paths.envelope_path(RUN, "toloka")
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
    assert not paths.merged_path(RUN).exists()


def test_merge_writes_validating_document(project, microworkers_record):
    write_all_envelopes({"microworkers": [microworkers_record, microworkers_record]})
    summary = merge.merge(RUN)
    merged_path = paths.merged_path(RUN)
    merged = json.loads(merged_path.read_text())
    schema.validate_merged(merged)
    assert summary == {
        "run_id": RUN,
        "merged_path": str(merged_path),
        "sites": {name: ("ok" if name == "microworkers" else "no_account") for name in SITES},
        "task_count": 2,
    }
    assert merged["run_id"] == RUN
    assert set(merged["sites"]) == set(SITES)
    assert merged["sites"]["microworkers"] == {
        "status": "ok", "error": None,
        "fetched_at": merged["sites"]["microworkers"]["fetched_at"], "task_count": 2}
    assert merged["sites"]["toloka"]["error"] == "fixture"
    assert [task["task_id"] for task in merged["tasks"]] == [
        str(microworkers_record["campaign_id"])] * 2


def test_cli_merge_prints_summary(project, runner):
    write_all_envelopes()
    outcome = runner.invoke(app, ["merge", RUN])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout)["task_count"] == 0


def test_cli_merge_missing_run_exits_2(project, runner):
    outcome = runner.invoke(app, ["merge", "never-ran"])
    assert outcome.exit_code == 2, outcome.output
    assert "no envelope for" in outcome.output
