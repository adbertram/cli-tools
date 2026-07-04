import json

from typer.testing import CliRunner

from copilot_cli.client import DataverseClient
from copilot_cli.commands import agent_flow


def test_get_agent_flow_can_include_clientdata_from_unpublished_endpoint(monkeypatch):
    client = DataverseClient("https://example.crm.dynamics.com", "token")
    calls = []

    def fake_get(endpoint):
        calls.append(endpoint)
        return {"workflowid": "flow-123", "clientdata": "{}"}

    monkeypatch.setattr(client, "get", fake_get)

    result = client.get_agent_flow("flow-123", expand_definition=True)

    assert result == {"workflowid": "flow-123", "clientdata": "{}"}
    assert calls == [
        "workflows(flow-123)/Microsoft.Dynamics.CRM.RetrieveUnpublished()"
        "?$select=workflowid,name,description,clientdata,statecode,statuscode,type,"
        "parentworkflowid,createdon,modifiedon"
    ]


def test_agent_flow_create_from_existing_flow_clones_definition(monkeypatch):
    source_definition = {
        "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
        "contentVersion": "1.0.0.0",
        "triggers": {"manual": {"type": "Request"}},
        "actions": {},
        "parameters": {},
        "outputs": {},
    }
    captured = {}

    class FakeClient:
        def get_agent_flow(self, workflow_id, expand_definition=False):
            captured["get_agent_flow"] = {
                "workflow_id": workflow_id,
                "expand_definition": expand_definition,
            }
            return {
                "clientdata": json.dumps(
                    {"properties": {"definition": source_definition}}
                )
            }

        def create_agent_flow(
            self,
            name,
            definition=None,
            connection_references=None,
            description=None,
        ):
            captured["create_agent_flow"] = {
                "name": name,
                "definition": definition,
                "connection_references": connection_references,
                "description": description,
            }
            return {"workflowid": "new-flow-123"}

    monkeypatch.setattr(agent_flow, "get_client", lambda: FakeClient())

    runner = CliRunner()
    result = runner.invoke(
        agent_flow.app,
        ["create", "--name", "Copied Flow", "--from", "source-flow-123"],
    )

    assert result.exit_code == 0, result.output
    assert captured["get_agent_flow"] == {
        "workflow_id": "source-flow-123",
        "expand_definition": True,
    }
    assert captured["create_agent_flow"] == {
        "name": "Copied Flow",
        "definition": source_definition,
        "connection_references": None,
        "description": None,
    }
    assert json.loads(result.stdout) == {
        "workflowid": "new-flow-123",
        "name": "Copied Flow",
        "status": "Draft",
    }
