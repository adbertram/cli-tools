"""Regression tests for `n8n executions list`.

The n8n public API excludes currently-active executions from GET /executions
unless status=running is requested (the public-api executions handler passes
excludedExecutionsIds for every other request). The default list must merge a
status=running fetch so in-flight executions are not silently omitted, and the
client-side date filter must use startedAt because running executions have no
stoppedAt.
"""
import json

from typer.testing import CliRunner

import n8n_cli.commands.executions as executions_module
from n8n_cli.commands.executions import app as executions_app

runner = CliRunner()

IN_RANGE_ARGS = ["list", "--from", "2026-06-10", "--to", "2026-06-15"]


class FakeExecutionsApi:
    """Serves canned /executions pages keyed by the requested status param."""

    def __init__(self, pages_by_status):
        self.requests = []
        self._pages_by_status = {key: list(pages) for key, pages in pages_by_status.items()}

    def _request(self, method, endpoint, params=None):
        assert method == "GET"
        assert endpoint == "/executions"
        self.requests.append(dict(params))
        pages = self._pages_by_status[params.get("status")]
        return pages.pop(0)


def _execution(ex_id, status, started_at, stopped_at, workflow_id="wf123", mode="trigger"):
    return {
        "id": ex_id,
        "status": status,
        "mode": mode,
        "workflowId": workflow_id,
        "startedAt": started_at,
        "stoppedAt": stopped_at,
    }


def _invoke(monkeypatch, api, args):
    monkeypatch.setattr(executions_module, "get_n8n_api_client", lambda: api)
    result = runner.invoke(executions_app, args)
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_default_list_includes_running_executions(monkeypatch):
    finished = _execution(
        3048, "success", "2026-06-12T11:00:00.000Z", "2026-06-12T11:00:05.000Z"
    )
    running = _execution(3049, "running", "2026-06-12T12:00:00.000Z", None)
    api = FakeExecutionsApi({
        None: [{"data": [finished], "nextCursor": None}],
        "running": [{"data": [running], "nextCursor": None}],
    })

    output = _invoke(monkeypatch, api, IN_RANGE_ARGS)

    assert [ex["id"] for ex in output] == [3049, 3048]
    merged_running = next(ex for ex in output if ex["id"] == 3049)
    assert merged_running["status"] == "running"
    assert merged_running["stoppedAt"] is None

    assert len(api.requests) == 2
    assert "status" not in api.requests[0]
    assert api.requests[1]["status"] == "running"


def test_date_filter_uses_started_at_for_running_executions(monkeypatch):
    in_range = _execution(3049, "running", "2026-06-12T12:00:00.000Z", None)
    out_of_range = _execution(2000, "running", "2026-05-01T12:00:00.000Z", None)
    api = FakeExecutionsApi({
        None: [{"data": [], "nextCursor": None}],
        "running": [{"data": [in_range, out_of_range], "nextCursor": None}],
    })

    output = _invoke(monkeypatch, api, IN_RANGE_ARGS)

    assert [ex["id"] for ex in output] == [3049]
    assert output[0]["stoppedAt"] is None


def test_explicit_status_filter_makes_single_fetch(monkeypatch):
    errored = _execution(
        3001, "error", "2026-06-12T10:00:00.000Z", "2026-06-12T10:00:02.000Z"
    )
    api = FakeExecutionsApi({
        "error": [{"data": [errored], "nextCursor": None}],
    })

    output = _invoke(monkeypatch, api, IN_RANGE_ARGS + ["--status", "error"])

    assert [ex["id"] for ex in output] == [3001]
    assert len(api.requests) == 1
    assert api.requests[0]["status"] == "error"


def test_default_list_dedupes_overlapping_running_executions(monkeypatch):
    running = _execution(3049, "running", "2026-06-12T12:00:00.000Z", None)
    api = FakeExecutionsApi({
        None: [{"data": [running], "nextCursor": None}],
        "running": [{"data": [running], "nextCursor": None}],
    })

    output = _invoke(
        monkeypatch, api, IN_RANGE_ARGS + ["--workflow-id", "wf123"]
    )

    assert [ex["id"] for ex in output] == [3049]
    assert [req["workflowId"] for req in api.requests] == ["wf123", "wf123"]
