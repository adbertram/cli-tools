"""Workflow PUT must remain a single attempt through the public command boundary."""
import json
from unittest.mock import Mock

import pytest
import requests
from typer.testing import CliRunner

from n8n_cli.commands import workflows
from n8n_cli.n8n_api import N8nApiClient, N8nApiError


BODY = {"name": "Fixture", "nodes": [], "connections": {}, "settings": {}}


@pytest.fixture
def client(monkeypatch):
    value = N8nApiClient(base_url="https://fixture.invalid/api/v1", api_key="fixture-only")
    value.session = Mock()
    monkeypatch.setattr("n8n_cli.n8n_api.time.sleep", lambda _: None)
    return value


@pytest.mark.parametrize("failure", [requests.Timeout, requests.ConnectionError])
def test_update_workflow_does_not_replay_ambiguous_put(client, failure):
    client.session.request.side_effect = failure("fixture response lost")
    with pytest.raises(N8nApiError, match="fixture response lost"):
        client.update_workflow("fixture", BODY)
    client.session.request.assert_called_once_with(
        "PUT", "https://fixture.invalid/api/v1/workflows/fixture", json=BODY,
    )


def test_public_update_file_preserves_error_and_sends_one_put(client, monkeypatch, tmp_path):
    workflow_file = tmp_path / "workflow.json"
    workflow_file.write_text(json.dumps(BODY))
    current = Mock(status_code=200)
    current.json.return_value = {"id": "fixture", "active": False, **BODY}
    client.session.request.side_effect = [current, requests.Timeout("fixture response lost")]
    monkeypatch.setattr(workflows, "get_n8n_api_client", lambda: client)

    result = CliRunner().invoke(workflows.app, ["update", "fixture", "--file", str(workflow_file)])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "fixture response lost" in result.stderr
    assert "fixture-only" not in result.output
    assert [call.args[0] for call in client.session.request.call_args_list] == ["GET", "PUT"]


def test_update_workflow_keeps_success_payload(client):
    response = Mock(status_code=200)
    response.json.return_value = {"id": "fixture", **BODY}
    client.session.request.return_value = response
    assert client.update_workflow("fixture", BODY) == {"id": "fixture", **BODY}
    client.session.request.assert_called_once_with(
        "PUT", "https://fixture.invalid/api/v1/workflows/fixture", json=BODY,
    )
