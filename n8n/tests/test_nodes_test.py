import pytest
import typer

from n8n_cli.commands import test as test_command


class FakeApi:
    def __init__(self):
        self.created_nodes = None

    def resolve_node_type(self, _node_name):
        return "n8n-nodes-example.example"

    def get_node_credential_types(self, _node_type):
        return []

    def create_workflow(self, name, nodes, connections):
        self.created_nodes = nodes
        return {
            "id": "workflow-1",
            "name": name,
            "nodes": nodes,
            "connections": connections,
        }

    def deactivate_workflow(self, _workflow_id):
        return None

    def delete_workflow(self, _workflow_id):
        return None


def test_node_test_preserves_case_sensitive_resource_and_operation(monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(test_command, "get_n8n_api_client", lambda: api)
    monkeypatch.setattr(test_command, "_check_ui_visibility", lambda *_args: [])
    monkeypatch.setattr(test_command.health_mod, "run_health_checks", lambda *_args, **_kwargs: [object()])
    monkeypatch.setattr(test_command.health_mod, "has_failures", lambda _findings: True)
    monkeypatch.setattr(test_command, "_print_findings_table", lambda _findings: None)

    with pytest.raises(typer.Exit):
        test_command.test_node(
            node_name="example",
            resource="pullRequest",
            operation="findPullRequest",
            timeout=1,
            no_cleanup=False,
            params='{"owner":"adbertram","repo":"issue-manager","head":"feature"}',
            credentials=None,
            node_type=None,
            username=None,
            password=None,
            workflow_id=None,
            node_filter=None,
            strict=False,
            as_json=False,
        )

    assert api.created_nodes[1]["parameters"] == {
        "resource": "pullRequest",
        "operation": "findPullRequest",
        "owner": "adbertram",
        "repo": "issue-manager",
        "head": "feature",
    }
