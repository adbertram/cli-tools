"""`validate <file>`: autodetects envelope vs merged, exit 0 or 2."""

from __future__ import annotations

import json

from microworker_cli import envelope, merge, paths
from microworker_cli.main import app

RUN = "20260902T000000Z"


def test_validate_envelope(project, runner):
    path = paths.envelope_path(RUN, "humanrail")
    envelope.write(path, envelope.build("humanrail", envelope.NO_ACCOUNT, "x", []))
    outcome = runner.invoke(app, ["validate", str(path)])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout) == {"file": str(path), "kind": "envelope", "valid": True}


def test_validate_merged(project, runner):
    from conftest import SITES
    for name in SITES:
        envelope.write(paths.envelope_path(RUN, name),
                       envelope.build(name, envelope.NO_ACCOUNT, "x", []))
    merge.merge(RUN)
    outcome = runner.invoke(app, ["validate", str(paths.merged_path(RUN))])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout)["kind"] == "merged"


def test_invalid_envelope_exits_2_with_schema_message(project, runner, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"site": "x", "status": "ok", "fetched_at": "2026-09-02T00:00:00Z",
                                "error": "should be null", "tasks": []}))
    outcome = runner.invoke(app, ["validate", str(path)])
    assert outcome.exit_code == 2, outcome.output
    assert "does not match the envelope schema" in outcome.output
    assert "'error'" in outcome.output


def test_unknown_shape_exits_2(project, runner, tmp_path):
    path = tmp_path / "what.json"
    path.write_text(json.dumps({"hello": 1}))
    outcome = runner.invoke(app, ["validate", str(path)])
    assert outcome.exit_code == 2, outcome.output
    assert "neither an envelope" in outcome.output


def test_missing_file_exits_2(project, runner, tmp_path):
    outcome = runner.invoke(app, ["validate", str(tmp_path / "absent.json")])
    assert outcome.exit_code == 2, outcome.output
    assert "is not a file" in outcome.output


def test_extra_task_field_rejected(project, runner, tmp_path):
    path = tmp_path / "merged.json"
    path.write_text(json.dumps({
        "run_id": RUN, "merged_at": "2026-09-02T00:00:00Z",
        "sites": {"microworkers": {"status": "ok", "error": None,
                                   "fetched_at": "2026-09-02T00:00:00Z", "task_count": 1}},
        "tasks": [{"site": "microworkers", "task_id": "1", "title": None, "url": None,
                   "pay_amount": None, "pay_currency": None, "est_minutes": None,
                   "slots_open": None, "expires_at": None, "raw": {}, "extra": 1}],
    }))
    outcome = runner.invoke(app, ["validate", str(path)])
    assert outcome.exit_code == 2, outcome.output
    assert "extra" in outcome.output
