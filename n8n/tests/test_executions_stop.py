"""Behavior tests for `n8n executions stop`.

The public n8n API has no stop endpoint, so the command posts to the internal
REST endpoint /rest/executions/{id}/stop. Live n8n 2.10.0 returns the stop
result inside a `data` envelope on success and HTTP 500 with a JSON `message`
when the execution is finished or missing.
"""
import json

import pytest
from typer.testing import CliRunner

import n8n_cli.commands.executions as executions_module
import n8n_cli.n8n_api as n8n_api_module
from n8n_cli.n8n_api import N8nApiClient, N8nApiError


STOP_RESULT = {
    "mode": "manual",
    "startedAt": "2026-09-16T16:54:01.011Z",
    "stoppedAt": "2026-09-16T16:54:05.289Z",
    "finished": False,
    "status": "canceled",
}


def _client():
    return N8nApiClient(base_url="http://example.test/api/v1", api_key="test-key")


def test_should_post_to_internal_stop_endpoint_and_unwrap_data():
    client = _client()
    calls = []

    def fake_rest(method, path, **kwargs):
        calls.append((method, path))
        return {"data": STOP_RESULT}

    client._rest_request = fake_rest

    assert client.stop_execution("20635") == STOP_RESULT
    assert calls == [("POST", "/rest/executions/20635/stop")]


def test_should_raise_when_stop_response_has_no_data_object():
    client = _client()
    client._rest_request = lambda method, path, **kwargs: {"unexpected": True}

    with pytest.raises(N8nApiError, match="did not include a data object"):
        client.stop_execution("20635")


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.ok = status_code < 400


def test_should_include_server_message_when_rest_request_fails(monkeypatch):
    client = _client()
    client._get_session_cookie = lambda: "n8n-auth=cookie"
    body = '{"code":0,"message":"Only running or waiting executions can be stopped and 20618 is currently success"}'
    monkeypatch.setattr(
        n8n_api_module.requests, "request", lambda *args, **kwargs: FakeResponse(500, body)
    )

    with pytest.raises(N8nApiError) as excinfo:
        client.stop_execution("20618")

    assert "(500) POST /rest/executions/20618/stop" in str(excinfo.value)
    assert "Only running or waiting executions can be stopped" in str(excinfo.value)


class FakeStopApi:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.ids = []

    def stop_execution(self, execution_id):
        self.ids.append(execution_id)
        if self.error is not None:
            raise self.error
        return self.result


def _invoke_stop(monkeypatch, api):
    monkeypatch.setattr(executions_module, "get_n8n_api_client", lambda: api)
    return CliRunner().invoke(executions_module.app, ["stop", "20635"])


def test_should_print_stop_result_json_on_stdout(monkeypatch):
    api = FakeStopApi(result=STOP_RESULT)

    result = _invoke_stop(monkeypatch, api)

    assert result.exit_code == 0, result.stderr
    assert result.stdout == json.dumps(STOP_RESULT, indent=2) + "\n"
    assert api.ids == ["20635"]


def test_should_exit_nonzero_with_error_on_stderr_when_stop_fails(monkeypatch):
    api = FakeStopApi(error=N8nApiError("Failed to find execution to stop"))

    result = _invoke_stop(monkeypatch, api)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Failed to find execution to stop" in result.stderr
