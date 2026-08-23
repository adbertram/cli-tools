"""Behavior tests for `n8n workflows execute`."""

import json

from typer.testing import CliRunner

import n8n_cli.commands.workflows as workflows_module
from n8n_cli.n8n_api import N8nApiClient


EXPECTED_RESULT = {"executionId": "exec-42"}


class FakeWorkflowsApi:
    """Return a fixed trigger result without access to an n8n server."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.workflow_ids = []

    def execute_workflow(self, workflow_id):
        self.workflow_ids.append(workflow_id)
        if self.error is not None:
            raise self.error
        return self.result


def _invoke_execute(monkeypatch, api):
    monkeypatch.setattr(workflows_module, "get_n8n_api_client", lambda: api)
    return CliRunner().invoke(
        workflows_module.app,
        ["execute", "workflow-17"],
    )


def test_should_normalize_nested_result_when_api_executes_workflow():
    client = N8nApiClient(
        base_url="http://example.test/api/v1",
        api_key="test-key",
    )
    client.get_workflow = lambda workflow_id: {
        "id": workflow_id,
        "nodes": [],
        "connections": {},
    }
    client._rest_request = lambda method, path, **kwargs: {
        "data": EXPECTED_RESULT
    }

    result = client.execute_workflow("workflow-17")

    assert result == EXPECTED_RESULT


def test_should_print_execution_result_when_trigger_succeeds(monkeypatch, capsys):
    api = FakeWorkflowsApi(result=EXPECTED_RESULT)
    monkeypatch.setattr(workflows_module, "get_n8n_api_client", lambda: api)

    workflows_module.workflows_execute("workflow-17")

    captured = capsys.readouterr()
    assert captured.out == json.dumps(EXPECTED_RESULT, indent=2) + "\n", (
        "execution result must be JSON on stdout"
    )
    assert api.workflow_ids == ["workflow-17"]


def test_should_print_execution_result_at_command_boundary_when_trigger_succeeds(
    monkeypatch,
):
    api = FakeWorkflowsApi(result=EXPECTED_RESULT)

    result = _invoke_execute(monkeypatch, api)

    assert result.exit_code == 0, result.stderr
    assert result.stdout == json.dumps(EXPECTED_RESULT, indent=2) + "\n", (
        "execution result must be JSON on stdout"
    )
    assert api.workflow_ids == ["workflow-17"]


def test_should_report_clear_error_when_trigger_fails(monkeypatch):
    api = FakeWorkflowsApi(error=RuntimeError("fake trigger rejected"))

    result = _invoke_execute(monkeypatch, api)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error: fake trigger rejected" in result.stderr
    assert api.workflow_ids == ["workflow-17"]


def test_should_print_waiting_result_when_trigger_waits_for_webhook(monkeypatch):
    waiting_result = {"waitingForWebhook": True}
    api = FakeWorkflowsApi(result=waiting_result)

    result = _invoke_execute(monkeypatch, api)

    assert result.exit_code == 0, result.stderr
    assert result.stdout == json.dumps(waiting_result, indent=2) + "\n"
    assert "Workflow is waiting for webhook input" in result.stderr


def test_should_report_clear_error_when_trigger_result_has_no_identifier(
    monkeypatch,
):
    api = FakeWorkflowsApi(result={})

    result = _invoke_execute(monkeypatch, api)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert (
        "Error: Workflow execution response did not include an execution ID"
        in result.stderr
    )
