from typer.testing import CliRunner

from n8n_cli.commands import workflow_nodes


class FakeApi:
    def __init__(self, workflow):
        self.workflow = workflow
        self.update_called = False

    def get_workflow(self, workflow_id):
        return self.workflow

    def get_node_definition(self, node_type):
        return {"name": "n8n-nodes-base.set", "displayName": "Set", "defaultVersion": 3}

    def update_workflow(self, workflow_id, data):
        self.update_called = True
        return data


def archived_workflow():
    return {
        "id": "wf_1",
        "name": "Archived Workflow",
        "isArchived": True,
        "nodes": [
            {"id": "node_1", "name": "Source", "type": "n8n-nodes-base.set", "parameters": {}},
            {"id": "node_2", "name": "Target", "type": "n8n-nodes-base.set", "parameters": {}},
        ],
        "connections": {},
    }


def run_with_archived_workflow(monkeypatch, args):
    api = FakeApi(archived_workflow())
    monkeypatch.setattr(workflow_nodes, "get_n8n_api_client", lambda: api)

    result = CliRunner().invoke(workflow_nodes.app, args)

    assert result.exit_code == 1
    assert "Workflow 'wf_1' is archived; node changes cannot be saved." in result.output
    assert api.update_called is False


def test_node_add_fails_before_update_when_workflow_is_archived(monkeypatch):
    run_with_archived_workflow(monkeypatch, ["add", "wf_1", "set"])


def test_node_update_fails_before_update_when_workflow_is_archived(monkeypatch):
    run_with_archived_workflow(monkeypatch, ["update", "wf_1", "Source", "--params", '{"foo": "bar"}'])


def test_node_connect_fails_before_update_when_workflow_is_archived(monkeypatch):
    run_with_archived_workflow(
        monkeypatch,
        ["connect", "wf_1", "--from", "Source", "--to", "Target"],
    )
