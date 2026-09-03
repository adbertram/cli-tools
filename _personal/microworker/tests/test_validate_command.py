"""`validate <file>`: a site envelope, exit 0 or 2. There is no merged file."""

from __future__ import annotations

import json

from microworker_cli import envelope, paths
from microworker_cli.main import app

RUN = "20260902T000000Z"


def test_validate_envelope(project, runner):
    path = paths.envelope_path(RUN, "humanrail")
    envelope.write(path, envelope.build("humanrail", envelope.NO_ACCOUNT, "x", []))
    outcome = runner.invoke(app, ["validate", str(path)])
    assert outcome.exit_code == 0, outcome.output
    assert json.loads(outcome.stdout) == {"file": str(path), "kind": "envelope", "valid": True}


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
    assert "is not an envelope" in outcome.output


def test_former_merged_shape_is_no_longer_a_document_kind(project, runner, tmp_path):
    """The old merged.json is not an envelope, so `validate` rejects it."""
    path = tmp_path / "merged.json"
    path.write_text(json.dumps({
        "run_id": RUN, "merged_at": "2026-09-02T00:00:00Z", "sites": {}, "tasks": []}))
    outcome = runner.invoke(app, ["validate", str(path)])
    assert outcome.exit_code == 2, outcome.output
    assert "is not an envelope" in outcome.output


def test_missing_file_exits_2(project, runner, tmp_path):
    outcome = runner.invoke(app, ["validate", str(tmp_path / "absent.json")])
    assert outcome.exit_code == 2, outcome.output
    assert "is not a file" in outcome.output


def test_extra_envelope_field_rejected(project, runner, tmp_path):
    path = tmp_path / "extra.json"
    path.write_text(json.dumps({
        "site": "microworkers", "status": "ok", "fetched_at": "2026-09-02T00:00:00Z",
        "error": None, "tasks": [], "extra": 1}))
    outcome = runner.invoke(app, ["validate", str(path)])
    assert outcome.exit_code == 2, outcome.output
    assert "extra" in outcome.output
