"""Publish-state handling for agent flow export/import.

Covers the two defects around unpublished web-designer drafts:

1. ``agent-flow import`` must detect the Dataverse ``ActiveUnpublished`` state
   before it PATCHes, and fail with an actionable message instead of leaking the
   raw solution-layer HTTP 400.
2. ``agent-flow export --draft`` must return the real unpublished definition, or
   fail loudly. It must never label published content as ``draft``.
"""
import json

import pytest

from copilot_cli.client import (
    ClientError,
    DataverseClient,
    is_active_unpublished_conflict,
)

WORKFLOW_ID = "45346655-e989-f111-ab0f-70a8a5b0df05"

PUBLISHED_DEFINITION = {
    "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
    "contentVersion": "1.0.0.0",
    "triggers": {"manual": {"type": "Request", "kind": "CopilotStudioAgent"}},
    "actions": {"Compose_Published": {"type": "Compose", "inputs": "published"}},
}

DRAFT_DEFINITION = {
    "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
    "contentVersion": "1.0.0.0",
    "triggers": {"manual": {"type": "Request", "kind": "CopilotStudioAgent"}},
    "actions": {
        "Compose_Published": {"type": "Compose", "inputs": "published"},
        "Run_a_prompt": {"type": "Compose", "inputs": "draft only"},
    },
}

DATAVERSE_ACTIVE_UNPUBLISHED_400 = (
    "HTTP 400: You are attempting to do a published update of publishable "
    "component in an unmodified active context when there exists an unpublished "
    "active row. This is not allowed context.IsModified =False Component Type: 29 "
    f"Object Id: {WORKFLOW_ID} CurrentState=ActiveUnpublished"
)


def _clientdata(definition, connection_references=None):
    return json.dumps(
        {
            "properties": {
                "definition": definition,
                "connectionReferences": connection_references or {},
            },
            "schemaVersion": "1.0.0.0",
        }
    )


class FakeDataverse:
    """Minimal Dataverse stand-in that models published vs unpublished rows."""

    def __init__(self, published_definition, unpublished_definition, latest_operation=2):
        self.published_clientdata = (
            None if published_definition is None else _clientdata(published_definition)
        )
        self.unpublished_clientdata = _clientdata(unpublished_definition)
        self.latest_operation = latest_operation
        self.patches = []
        self.posts = []

    def install(self, client, monkeypatch):
        monkeypatch.setattr(client, "get", self.get)
        monkeypatch.setattr(client, "patch", self.patch)
        monkeypatch.setattr(client, "post", self.post)
        monkeypatch.setattr(
            client, "_auto_associate_workflow_connection_references", lambda *a, **k: None
        )
        return self

    def get(self, endpoint, params=None):
        if "componentversionnrddatasourceset" in endpoint:
            if self.latest_operation is None:
                return {"value": []}
            return {
                "value": [
                    {
                        "componentversionnrddatasourceid": "cv-1",
                        "operation": self.latest_operation,
                        "createdon": "2026-07-27T18:00:00Z",
                        "componentversionname": "v1.0.0.0",
                    }
                ]
            }
        if "RetrieveUnpublished()" in endpoint:
            return {
                "workflowid": WORKFLOW_ID,
                "name": "ATABlog-Screenshots",
                "description": "",
                "clientdata": self.unpublished_clientdata,
                "statecode": 1,
                "type": 1,
            }
        if self.published_clientdata is None:
            raise ClientError(
                f"HTTP 404: Entity 'workflow' With Id = {WORKFLOW_ID} Does Not Exist"
            )
        return {
            "workflowid": WORKFLOW_ID,
            "name": "ATABlog-Screenshots",
            "description": "",
            "clientdata": self.published_clientdata,
            "statecode": 1,
            "type": 1,
        }

    def patch(self, endpoint, data):
        self.patches.append((endpoint, data))
        return {}

    def post(self, endpoint, data, return_id=False):
        self.posts.append((endpoint, data))
        if endpoint == "PublishXml":
            # Publishing promotes the unpublished row to the published row.
            self.published_clientdata = self.unpublished_clientdata
            self.latest_operation = 2
        return None


@pytest.fixture
def client():
    return DataverseClient("https://example.crm.dynamics.com", "token")


# --- detection ------------------------------------------------------------


def test_publish_state_reports_no_draft_when_rows_match(client, monkeypatch):
    FakeDataverse(PUBLISHED_DEFINITION, PUBLISHED_DEFINITION).install(client, monkeypatch)

    state = client.get_agent_flow_publish_state(WORKFLOW_ID)

    assert state["has_unpublished_draft"] is False
    assert state["draft_evidence"] == ""
    assert state["published_exists"] is True


def test_publish_state_detects_diverging_unpublished_row(client, monkeypatch):
    FakeDataverse(PUBLISHED_DEFINITION, DRAFT_DEFINITION).install(client, monkeypatch)

    state = client.get_agent_flow_publish_state(WORKFLOW_ID)

    assert state["has_unpublished_draft"] is True
    assert "RetrieveUnpublished" in state["draft_evidence"]


def test_publish_state_detects_unpublished_newest_component_version(client, monkeypatch):
    # Rows match, but the newest version was only saved (Update), never published.
    FakeDataverse(
        PUBLISHED_DEFINITION, PUBLISHED_DEFINITION, latest_operation=1
    ).install(client, monkeypatch)

    state = client.get_agent_flow_publish_state(WORKFLOW_ID)

    assert state["has_unpublished_draft"] is True
    assert state["latest_version_operation_label"] == "Update"
    assert "Update" in state["draft_evidence"]


def test_publish_state_ignores_published_newest_component_version(client, monkeypatch):
    FakeDataverse(
        PUBLISHED_DEFINITION, PUBLISHED_DEFINITION, latest_operation=2
    ).install(client, monkeypatch)

    assert client.get_agent_flow_publish_state(WORKFLOW_ID)["has_unpublished_draft"] is False


def test_is_active_unpublished_conflict_matches_dataverse_400():
    assert is_active_unpublished_conflict(DATAVERSE_ACTIVE_UNPUBLISHED_400) is True
    assert is_active_unpublished_conflict("HTTP 400: some other failure") is False


# --- import ---------------------------------------------------------------


def test_import_refuses_when_unpublished_draft_exists(client, monkeypatch):
    fake = FakeDataverse(PUBLISHED_DEFINITION, DRAFT_DEFINITION).install(client, monkeypatch)

    with pytest.raises(ClientError) as excinfo:
        client.import_agent_flow(WORKFLOW_ID, DRAFT_DEFINITION)

    message = str(excinfo.value)
    assert "unpublished draft" in message
    assert "component type 29" in message
    assert "--discard-draft" in message
    assert "export" in message and "--draft" in message
    # The blocked import must not touch the flow.
    assert fake.patches == []


def test_import_succeeds_when_no_draft_exists(client, monkeypatch):
    fake = FakeDataverse(PUBLISHED_DEFINITION, PUBLISHED_DEFINITION).install(client, monkeypatch)

    result = client.import_agent_flow(WORKFLOW_ID, DRAFT_DEFINITION)

    assert result["status"] == "updated"
    assert len(fake.patches) == 1
    assert fake.posts == []


def test_import_with_discard_draft_publishes_then_patches(client, monkeypatch):
    fake = FakeDataverse(PUBLISHED_DEFINITION, DRAFT_DEFINITION).install(client, monkeypatch)

    result = client.import_agent_flow(WORKFLOW_ID, PUBLISHED_DEFINITION, discard_draft=True)

    assert result["status"] == "updated"
    assert [endpoint for endpoint, _ in fake.posts] == ["PublishXml"]
    assert (
        f"<workflow>{WORKFLOW_ID}</workflow>" in fake.posts[0][1]["ParameterXml"]
    )
    assert len(fake.patches) == 1


def test_import_with_publish_publishes_after_patch(client, monkeypatch):
    fake = FakeDataverse(PUBLISHED_DEFINITION, PUBLISHED_DEFINITION).install(client, monkeypatch)

    result = client.import_agent_flow(WORKFLOW_ID, DRAFT_DEFINITION, publish=True)

    assert result["status"] == "updated and published"
    assert len(fake.patches) == 1
    assert [endpoint for endpoint, _ in fake.posts] == ["PublishXml"]


def test_import_translates_dataverse_active_unpublished_400(client, monkeypatch):
    fake = FakeDataverse(PUBLISHED_DEFINITION, PUBLISHED_DEFINITION).install(client, monkeypatch)

    def failing_patch(endpoint, data):
        raise ClientError(DATAVERSE_ACTIVE_UNPUBLISHED_400)

    monkeypatch.setattr(client, "patch", failing_patch)

    with pytest.raises(ClientError) as excinfo:
        client.import_agent_flow(WORKFLOW_ID, DRAFT_DEFINITION)

    message = str(excinfo.value)
    assert "unpublished draft" in message
    assert "--discard-draft" in message
    # The original Dataverse detail is preserved, not swallowed.
    assert "CurrentState=ActiveUnpublished" in message
    assert fake.posts == []


def test_import_reraises_unrelated_patch_errors(client, monkeypatch):
    FakeDataverse(PUBLISHED_DEFINITION, PUBLISHED_DEFINITION).install(client, monkeypatch)
    monkeypatch.setattr(
        client,
        "patch",
        lambda endpoint, data: (_ for _ in ()).throw(ClientError("HTTP 403: forbidden")),
    )

    with pytest.raises(ClientError, match="HTTP 403: forbidden"):
        client.import_agent_flow(WORKFLOW_ID, DRAFT_DEFINITION)


# --- export ---------------------------------------------------------------


def test_export_draft_returns_the_unpublished_definition(client, monkeypatch):
    FakeDataverse(PUBLISHED_DEFINITION, DRAFT_DEFINITION).install(client, monkeypatch)

    result = client.export_agent_flow(WORKFLOW_ID, draft=True)

    assert result["version"] == "draft"
    assert "Run_a_prompt" in result["definition"]["actions"]


def test_export_draft_fails_loudly_when_no_draft_exists(client, monkeypatch):
    FakeDataverse(PUBLISHED_DEFINITION, PUBLISHED_DEFINITION).install(client, monkeypatch)

    with pytest.raises(ClientError) as excinfo:
        client.export_agent_flow(WORKFLOW_ID, draft=True)

    assert "no unpublished draft" in str(excinfo.value)


def test_export_never_labels_published_content_as_draft(client, monkeypatch):
    """Regression: --draft used to return published actions labeled version: draft."""
    FakeDataverse(PUBLISHED_DEFINITION, PUBLISHED_DEFINITION).install(client, monkeypatch)

    with pytest.raises(ClientError):
        client.export_agent_flow(WORKFLOW_ID, draft=True)

    published = client.export_agent_flow(WORKFLOW_ID)
    assert published["version"] == "published"
    assert "Run_a_prompt" not in published["definition"]["actions"]


def test_export_published_flags_a_pending_draft(client, monkeypatch):
    FakeDataverse(PUBLISHED_DEFINITION, DRAFT_DEFINITION).install(client, monkeypatch)

    result = client.export_agent_flow(WORKFLOW_ID)

    assert result["version"] == "published"
    assert result["has_unpublished_draft"] is True
    assert "Run_a_prompt" not in result["definition"]["actions"]


def test_export_published_fails_when_flow_has_no_published_row(client, monkeypatch):
    FakeDataverse(None, DRAFT_DEFINITION).install(client, monkeypatch)

    with pytest.raises(ClientError) as excinfo:
        client.export_agent_flow(WORKFLOW_ID)

    assert "no published definition" in str(excinfo.value)


def test_publish_agent_flow_uses_publishxml(client, monkeypatch):
    fake = FakeDataverse(PUBLISHED_DEFINITION, DRAFT_DEFINITION).install(client, monkeypatch)

    result = client.publish_agent_flow(WORKFLOW_ID)

    assert result == {"workflowid": WORKFLOW_ID, "status": "published"}
    endpoint, data = fake.posts[0]
    assert endpoint == "PublishXml"
    assert data["ParameterXml"] == (
        "<importexportxml><workflows>"
        f"<workflow>{WORKFLOW_ID}</workflow>"
        "</workflows></importexportxml>"
    )
