"""NaN and Infinity are rejected at every boundary they can cross.

Python's `json` accepts and emits `NaN`/`Infinity`, neither of which is JSON, so
without an explicit refusal a non-finite number crosses three boundaries in a
row: a site CLI prints one, `discover` writes it into an envelope file that
`microworker validate` calls valid and `JSON.parse` rejects, and `merge` binds
it to SQLite -- where NaN becomes SQL NULL, so a task the site priced reads back
as `pay_amount: null` with its currency still attached.

Both spellings are covered: the bare literal (`NaN`), which `parse_constant`
catches, and the overflow (`1e999`), which Python silently converts to infinity
inside `parse_float` and never reports.
"""

from __future__ import annotations

import json

import pytest

from conftest import SITES
from microworker_cli import db, discover, envelope, jsonio, merge, paths, runner, schema
from microworker_cli.main import app

RUN = "20260902T000000Z"
TIMEOUT = 7
AUTH = ("microworkers", "auth", "status")


def raw_record(**overrides) -> dict:
    record = {"campaign_id": "abc123", "title": "t",
              "url": "https://microworkers.com/jobs.php?id=1", "payment": "$0.10",
              "ttf_minutes": 5, "positions_done": 1, "positions_total": 3}
    record.update(overrides)
    return record


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_site_stdout_with_a_non_finite_number_is_an_error_envelope(
        project, monkeypatch, literal):
    stdout = '[{"campaign_id": "abc", "payout": %s}]' % literal

    def fake_run(argv, timeout):
        key = tuple(argv)
        code, out = (0, "") if key == AUTH else (0, stdout)
        return runner.RunResult(argv=key, returncode=code, stdout=out, stderr="")

    monkeypatch.setattr(runner, "run", fake_run)
    summary = discover.discover("microworkers", RUN, TIMEOUT)
    assert summary["status"] == "error" and summary["task_count"] == 0
    data = json.loads(paths.envelope_path(RUN, "microworkers").read_text())
    assert "non-finite" in data["error"]


def test_envelope_write_refuses_a_non_finite_number(project):
    """The write fails rather than producing a file no strict parser accepts."""
    data = envelope.build("microworkers", envelope.OK, None,
                          [raw_record(payout=float("nan"))])
    with pytest.raises(jsonio.NonFiniteNumberError):
        envelope.write(paths.envelope_path(RUN, "microworkers"), data)


def test_validate_task_rejects_a_nan_price(project):
    """NaN IS a JSON Schema `number`, so the schema alone lets it through."""
    task = {"site": "humanrail", "task_id": "1", "title": None, "url": None,
            "pay_amount": float("nan"), "pay_currency": "SATS",
            "est_minutes": None, "slots_open": None, "expires_at": None, "raw": {}}
    schema.validate(task, schema.TASK, "task")  # the schema is satisfied
    with pytest.raises(jsonio.NonFiniteNumberError, match="pay_amount"):
        schema.validate_task(task)


def test_validate_task_rejects_a_non_finite_number_nested_in_raw(project):
    task = {"site": "humanrail", "task_id": "1", "title": None, "url": None,
            "pay_amount": None, "pay_currency": None, "est_minutes": None,
            "slots_open": None, "expires_at": None,
            "raw": {"quotes": [{"payout": float("inf")}]}}
    with pytest.raises(jsonio.NonFiniteNumberError, match="raw/quotes/0/payout"):
        schema.validate_task(task)


def test_merge_of_a_hand_written_nan_envelope_writes_nothing(project):
    """A file written outside this tool still cannot reach the database."""
    for name in SITES:
        envelope.write(paths.envelope_path(RUN, name),
                       envelope.build(name, envelope.NO_ACCOUNT, "fixture", []))
    path = paths.envelope_path(RUN, "microworkers")
    path.write_text(json.dumps({
        "site": "microworkers", "status": "ok",
        "fetched_at": "2026-09-02T00:00:00Z", "error": None,
        "tasks": [raw_record(payment="$1.00", extra=float("nan"))]}))

    with pytest.raises(jsonio.NonFiniteNumberError):
        merge.merge(RUN)
    assert not paths.db_path().exists()


def test_validate_command_rejects_a_nan_envelope(project, runner):
    """`validate` must not call a file valid that `JSON.parse` rejects."""
    path = paths.run_dir(RUN) / "handwritten.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "site": "microworkers", "status": "ok",
        "fetched_at": "2026-09-02T00:00:00Z", "error": None,
        "tasks": [{"payout": float("nan")}]}))
    outcome = runner.invoke(app, ["validate", str(path)])
    assert outcome.exit_code == 2, outcome.output
    assert "the literal NaN" in outcome.output


def test_stored_raw_is_serialized_strictly(project, microworkers_record):
    """`db` writes `raw` with allow_nan=False, so the column is always JSON."""
    with pytest.raises(jsonio.NonFiniteNumberError):
        jsonio.dumps({"payout": float("nan")})
    for name in SITES:
        data = (envelope.build(name, envelope.OK, None, [microworkers_record])
                if name == "microworkers"
                else envelope.build(name, envelope.NO_ACCOUNT, "fixture", []))
        envelope.write(paths.envelope_path(RUN, name), data)
    merge.merge(RUN)
    stored = db.get_task("microworkers", microworkers_record["campaign_id"])
    json.loads(jsonio.dumps(stored["raw"]))
