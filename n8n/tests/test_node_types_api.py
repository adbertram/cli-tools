"""Unit tests for node-definition fetching against the n8n 2.x REST API.

n8n 2.x removed the legacy GET /types/nodes.json static endpoint. Node
descriptions are now served by POST /rest/node-types (which returns full
descriptions for a list of {name, version} identifiers). These tests pin the
client to that endpoint and to the clear error raised when bulk enumeration is
requested.
"""
import pytest

from n8n_cli.n8n_api import N8nApiClient, N8nApiError


def _client():
    return N8nApiClient(base_url="http://example.test/api/v1", api_key="test-key")


def test_fetch_node_types_posts_to_rest_node_types_endpoint():
    client = _client()
    recorded = {}

    def fake_rest_request(method, path, **kwargs):
        recorded["method"] = method
        recorded["path"] = path
        recorded["kwargs"] = kwargs
        return {"data": [{"name": "webhook", "displayName": "Webhook", "properties": []}]}

    client._rest_request = fake_rest_request

    result = client._fetch_node_types([{"name": "n8n-nodes-base.webhook", "version": 2}])

    assert result == [{"name": "webhook", "displayName": "Webhook", "properties": []}]
    assert recorded["method"] == "POST"
    assert recorded["path"] == "/rest/node-types"
    assert recorded["kwargs"]["json"] == {
        "nodeInfos": [{"name": "n8n-nodes-base.webhook", "version": 2}]
    }


def test_fetch_node_types_accepts_plain_list_envelope():
    client = _client()

    def fake_rest_request(method, path, **kwargs):
        return [{"name": "set"}]

    client._rest_request = fake_rest_request

    assert client._fetch_node_types([{"name": "n8n-nodes-base.set"}]) == [{"name": "set"}]


def test_get_node_type_queries_single_node():
    client = _client()
    calls = []

    def fake_fetch(node_infos):
        calls.append(node_infos)
        return [{"name": "webhook", "properties": [{"name": "url"}]}]

    client._fetch_node_types = fake_fetch

    node = client.get_node_type("n8n-nodes-base.webhook")

    assert node["name"] == "webhook"
    assert calls == [[{"name": "n8n-nodes-base.webhook"}]]


def test_get_node_type_passes_version_when_provided():
    client = _client()
    calls = []

    def fake_fetch(node_infos):
        calls.append(node_infos)
        return [{"name": "webhook", "properties": []}]

    client._fetch_node_types = fake_fetch

    client.get_node_type("n8n-nodes-base.webhook", version=2)

    assert calls == [[{"name": "n8n-nodes-base.webhook", "version": 2}]]


def test_get_node_type_returns_none_when_not_found():
    client = _client()
    client._fetch_node_types = lambda node_infos: []
    assert client.get_node_type("n8n-nodes-base.missing") is None


def test_get_node_credential_types_extracts_credential_names():
    client = _client()

    def fake_get_node_type(full_node_type):
        return {
            "name": "claudeCode",
            "credentials": [
                {"name": "claudeCodeApi", "displayName": "Claude Code API"},
                {"name": "claudeCodeBrowser", "displayName": "Claude Code Browser"},
                "not-a-dict",
            ],
        }

    client.get_node_type = fake_get_node_type

    assert client.get_node_credential_types("n8n-nodes-claudecode.claudeCode") == [
        "claudeCodeApi",
        "claudeCodeBrowser",
    ]


def test_get_node_credential_types_returns_empty_when_node_not_found():
    client = _client()
    client.get_node_type = lambda full_node_type: None
    assert client.get_node_credential_types("n8n-nodes-base.missing") == []


def test_fetch_all_node_definitions_raises_actionable_error():
    client = _client()
    with pytest.raises(N8nApiError) as exc_info:
        client._fetch_all_node_definitions()
    message = str(exc_info.value)
    assert "types/nodes.json" in message
    assert "get_node_type" in message
