"""Behavior tests for `n8n workflows create` preserving explicit workflow settings."""

import json

from typer.testing import CliRunner

import n8n_cli.commands.workflows as workflows_module
from n8n_cli.n8n_api import N8nApiClient


class FakeCreateApi:
    """Record create_workflow kwargs without touching an n8n server."""

    def __init__(self):
        self.create_kwargs = None

    def create_workflow(self, **kwargs):
        self.create_kwargs = kwargs
        return {"id": "wf-new", "name": kwargs["name"]}

    def activate_workflow(self, workflow_id):
        return {"id": workflow_id, "name": "ignored"}


def _invoke_create(monkeypatch, api, args):
    monkeypatch.setattr(workflows_module, "get_n8n_api_client", lambda: api)
    return CliRunner().invoke(workflows_module.app, args)


def test_create_preserves_explicit_settings_and_tags(tmp_path, monkeypatch):
    workflow_file = tmp_path / "workflow.json"
    workflow_file.write_text(
        json.dumps(
            {
                "name": "Agent Task Overseer",
                "nodes": [],
                "connections": {},
                "settings": {
                    "timezone": "America/Chicago",
                    "executionTimeout": 3000,
                },
                "tags": [{"id": "tag-1", "name": "automation"}],
            }
        )
    )

    api = FakeCreateApi()
    result = _invoke_create(monkeypatch, api, ["create", str(workflow_file)])

    assert result.exit_code == 0, result.stderr
    assert api.create_kwargs["settings"]["timezone"] == "America/Chicago"
    assert api.create_kwargs["settings"]["executionTimeout"] == 3000
    assert api.create_kwargs["tags"] == [{"id": "tag-1", "name": "automation"}]


def test_create_passes_no_settings_when_none_supplied(tmp_path, monkeypatch):
    workflow_file = tmp_path / "workflow.json"
    workflow_file.write_text(
        json.dumps({"name": "Minimal", "nodes": [], "connections": {}})
    )

    api = FakeCreateApi()
    result = _invoke_create(monkeypatch, api, ["create", str(workflow_file)])

    assert result.exit_code == 0, result.stderr
    assert api.create_kwargs["settings"] is None
    assert api.create_kwargs["tags"] is None


def test_create_workflow_payload_includes_settings_and_tags():
    client = N8nApiClient(base_url="http://example.test/api/v1", api_key="test-key")
    recorded = {}

    def fake_request(method, endpoint, **kwargs):
        recorded["method"] = method
        recorded["endpoint"] = endpoint
        recorded["kwargs"] = kwargs
        return {"id": "wf-new", "name": "Workflow"}

    client._request = fake_request

    client.create_workflow(
        "Workflow",
        [],
        {},
        settings={"timezone": "America/Chicago", "executionTimeout": 3000},
        tags=[{"id": "tag-1", "name": "automation"}],
    )

    payload = recorded["kwargs"]["json"]
    assert recorded["method"] == "POST"
    assert recorded["endpoint"] == "/workflows"
    assert payload["settings"]["timezone"] == "America/Chicago"
    assert payload["settings"]["executionTimeout"] == 3000
    assert payload["settings"]["saveManualExecutions"] is True
    assert payload["settings"]["saveDataSuccessExecution"] == "all"
    assert payload["settings"]["saveDataErrorExecution"] == "all"
    assert payload["tags"] == [{"id": "tag-1", "name": "automation"}]


def test_create_workflow_payload_omits_tags_when_not_supplied():
    client = N8nApiClient(base_url="http://example.test/api/v1", api_key="test-key")
    recorded = {}

    def fake_request(method, endpoint, **kwargs):
        recorded["kwargs"] = kwargs
        return {"id": "wf-new", "name": "Workflow"}

    client._request = fake_request

    client.create_workflow("Workflow", [], {})

    payload = recorded["kwargs"]["json"]
    assert "tags" not in payload
