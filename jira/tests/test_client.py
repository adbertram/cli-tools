import base64
from copy import deepcopy

import pytest

from cli_tools_shared.exceptions import ClientError
from jira_cli.client import JiraClient, combine_jql, filters_to_jql
from jira_cli.config import OAUTH_3LO_AUTH_TYPE, SCOPED_API_TOKEN_AUTH_TYPE, SITE_BASIC_AUTH_TYPE


SAMPLE_ISSUE = {
    "id": "10001",
    "key": "ENG-1",
    "self": "https://acme.atlassian.net/rest/api/3/issue/10001",
    "fields": {
        "summary": "Broken workflow",
        "status": {"name": "To Do", "statusCategory": {"name": "To Do"}},
        "issuetype": {"name": "Bug"},
        "project": {"key": "ENG", "name": "Engineering"},
        "assignee": {"displayName": "Al"},
        "reporter": {"displayName": "Adam"},
        "priority": {"name": "High"},
        "created": "2026-06-01T12:00:00.000+0000",
        "updated": "2026-06-02T12:00:00.000+0000",
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "First line"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "Second line"},
                    ],
                },
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Bullet one"}],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Bullet two"}],
                                },
                                {
                                    "type": "orderedList",
                                    "content": [
                                        {
                                            "type": "listItem",
                                            "content": [
                                                {
                                                    "type": "paragraph",
                                                    "content": [{"type": "text", "text": "Nested item"}],
                                                }
                                            ],
                                        }
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        },
        "labels": ["automation"],
    },
}

SAMPLE_TRANSITION = {
    "id": "31",
    "name": "Done",
    "to": {
        "name": "Done",
        "statusCategory": {"name": "Done"},
    },
}

SAMPLE_PROJECT = {
    "id": "10000",
    "key": "ENG",
    "name": "Engineering",
    "self": "https://acme.atlassian.net/rest/api/3/project/ENG",
    "style": "classic",
    "simplified": False,
    "projectTypeKey": "software",
    "description": "Engineering work",
    "url": "https://example.com/eng",
    "projectCategory": {
        "id": "10010",
        "name": "Internal",
        "self": "https://acme.atlassian.net/rest/api/3/projectCategory/10010",
    },
    "lead": {"displayName": "Al"},
    "insight": {
        "totalIssueCount": 42,
        "lastIssueUpdateTime": "2026-06-02T12:00:00.000+0000",
    },
}


class DummyConfig:
    CREDENTIAL_TYPES = []

    def __init__(
        self,
        *,
        auth_type: str = SITE_BASIC_AUTH_TYPE,
        base_url: str = "https://acme.atlassian.net",
        cloud_id: str = "1324a887-45db-1bf4-1e99-ef0ff456d421",
    ):
        self.auth_type = auth_type
        self.base_url = base_url
        self.cloud_id = cloud_id
        self.username = "adam@example.com"
        self.password = "jira-api-token"
        self.client_id = "client-id"
        self.client_secret = "client-secret"
        self.access_token = "oauth-access-token"
        self.refresh_token = "oauth-refresh-token"
        self.token_expires_at = "9999999999"
        self.redirect_uri = "http://localhost"

    def has_credentials(self) -> bool:
        return True

    def get_missing_credentials(self) -> list[str]:
        return []

    @property
    def OAUTH_TOKEN_URL(self) -> str:
        if self.auth_type == OAUTH_3LO_AUTH_TYPE:
            return "https://auth.atlassian.com/oauth/token"
        return ""

    @property
    def OAUTH_AUTH_URL(self) -> str:
        if self.auth_type == OAUTH_3LO_AUTH_TYPE:
            return "https://auth.atlassian.com/authorize"
        return ""

    OAUTH_REDIRECT_URI = "http://localhost"
    OAUTH_TOKEN_AUTH = "body"


class FakeResponse:
    def __init__(self, *, status_code: int = 200, json_data=None, text: str = "", headers=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data


def _capture_request(monkeypatch, responses):
    calls = []

    def fake_request(method, url, headers=None, json=None, params=None):
        calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "json": deepcopy(json),
                "params": deepcopy(params),
            }
        )
        return responses.pop(0)

    monkeypatch.setattr("jira_cli.client.requests.request", fake_request)
    return calls


def test_client_should_fail_for_placeholder_base_url():
    with pytest.raises(ClientError, match="BASE_URL"):
        JiraClient(config=DummyConfig(base_url="https://your-domain.atlassian.net"))


def test_client_should_use_basic_auth_with_email_and_api_token():
    client = JiraClient(config=DummyConfig())
    expected = base64.b64encode(b"adam@example.com:jira-api-token").decode("ascii")
    assert client.headers["Authorization"] == f"Basic {expected}"


def test_client_should_use_gateway_url_for_scoped_api_tokens():
    client = JiraClient(config=DummyConfig(auth_type=SCOPED_API_TOKEN_AUTH_TYPE))

    assert client.base_url == "https://api.atlassian.com/ex/jira/1324a887-45db-1bf4-1e99-ef0ff456d421"
    assert client.headers["Authorization"].startswith("Basic ")


def test_client_should_use_bearer_auth_for_oauth_3lo():
    client = JiraClient(config=DummyConfig(auth_type=OAUTH_3LO_AUTH_TYPE))

    assert client.base_url == "https://api.atlassian.com/ex/jira/1324a887-45db-1bf4-1e99-ef0ff456d421"
    assert client.headers["Authorization"] == "Bearer oauth-access-token"


def test_filters_to_jql_should_translate_supported_filters():
    assert filters_to_jql(["status:eq:To Do", "project:ENG", "priority:in:High|Medium"]) == [
        'status = "To Do"',
        'project = "ENG"',
        'priority in ("High", "Medium")',
    ]


def test_filters_to_jql_should_fail_for_unsupported_filter_field():
    with pytest.raises(ClientError, match="Unsupported Jira filter field"):
        filters_to_jql(["component:eq:API"])


def test_combine_jql_should_use_default_order_when_no_query():
    assert combine_jql(None, None) == "updated >= -30d ORDER BY updated DESC"


def test_combine_jql_should_preserve_raw_jql_with_order_by():
    assert combine_jql("project = ENG ORDER BY updated DESC", None) == "project = ENG ORDER BY updated DESC"


def test_combine_jql_should_append_filters_before_raw_order_by():
    assert combine_jql("project = ENG ORDER BY updated DESC", ["status:eq:To Do"]) == (
        '(project = ENG) AND (status = "To Do") ORDER BY updated DESC'
    )


def test_list_tickets_should_post_enhanced_search_and_normalize_results(monkeypatch):
    calls = _capture_request(
        monkeypatch,
        [FakeResponse(json_data={"issues": [deepcopy(SAMPLE_ISSUE)]})],
    )
    client = JiraClient(config=DummyConfig())

    issues = client.list_tickets(
        limit=25,
        next_page_token="token-1",
        jql="project = ENG",
        filters=["status:eq:To Do"],
    )

    assert issues[0]["key"] == "ENG-1"
    assert issues[0]["summary"] == "Broken workflow"
    assert issues[0]["status"] == "To Do"
    assert issues[0]["issue_type"] == "Bug"
    assert issues[0]["project"] == "ENG"
    assert issues[0]["assignee"] == "Al"
    assert issues[0]["description"] == "First line\nSecond line\n\n- Bullet one\n- Bullet two\n  1. Nested item"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/search/jql"
    assert calls[0]["json"]["maxResults"] == 25
    assert calls[0]["json"]["nextPageToken"] == "token-1"
    assert "(project = ENG)" in calls[0]["json"]["jql"]
    assert 'status = "To Do"' in calls[0]["json"]["jql"]


def test_get_ticket_should_fetch_issue_detail(monkeypatch):
    calls = _capture_request(monkeypatch, [FakeResponse(json_data=deepcopy(SAMPLE_ISSUE))])
    client = JiraClient(config=DummyConfig())

    issue = client.get_ticket("ENG-1")

    assert issue["key"] == "ENG-1"
    assert issue["summary"] == "Broken workflow"
    assert issue["description"] == "First line\nSecond line\n\n- Bullet one\n- Bullet two\n  1. Nested item"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/issue/ENG-1"


def test_list_projects_should_get_paginated_projects_and_normalize_results(monkeypatch):
    calls = _capture_request(
        monkeypatch,
        [
            FakeResponse(
                json_data={
                    "values": [deepcopy(SAMPLE_PROJECT)],
                    "maxResults": 25,
                    "startAt": 0,
                    "total": 1,
                    "isLast": True,
                }
            )
        ],
    )
    client = JiraClient(config=DummyConfig())

    projects = client.list_projects(limit=25, query="Eng")

    assert projects == [
        {
            "id": "10000",
            "key": "ENG",
            "name": "Engineering",
            "project_type": "software",
            "style": "classic",
            "simplified": False,
            "category": "Internal",
            "category_id": "10010",
            "lead": "Al",
            "description": "Engineering work",
            "url": "https://example.com/eng",
            "total_issue_count": 42,
            "last_issue_update_time": "2026-06-02T12:00:00.000+0000",
            "self": "https://acme.atlassian.net/rest/api/3/project/ENG",
        }
    ]
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/project/search"
    assert calls[0]["params"] == {"maxResults": 25, "query": "Eng"}


def test_get_project_should_fetch_project_detail(monkeypatch):
    calls = _capture_request(monkeypatch, [FakeResponse(json_data=deepcopy(SAMPLE_PROJECT))])
    client = JiraClient(config=DummyConfig())

    project = client.get_project("ENG")

    assert project["key"] == "ENG"
    assert project["name"] == "Engineering"
    assert project["project_type"] == "software"
    assert project["category"] == "Internal"
    assert project["lead"] == "Al"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/project/ENG"


def test_create_ticket_should_post_issue_and_fetch_created_ticket(monkeypatch):
    calls = _capture_request(
        monkeypatch,
        [
            FakeResponse(json_data={"id": "10001", "key": "ENG-1", "self": "https://acme.atlassian.net/rest/api/3/issue/10001"}),
            FakeResponse(json_data=deepcopy(SAMPLE_ISSUE)),
        ],
    )
    client = JiraClient(config=DummyConfig())

    issue = client.create_ticket(
        project="ENG",
        issue_type="Bug",
        summary="Broken workflow",
        description="Details here",
        labels=["automation"],
    )

    assert issue["key"] == "ENG-1"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/issue"
    assert calls[0]["json"]["fields"]["summary"] == "Broken workflow"
    assert calls[0]["json"]["fields"]["description"]["type"] == "doc"


def test_update_ticket_should_put_issue_and_fetch_updated_ticket(monkeypatch):
    calls = _capture_request(
        monkeypatch,
        [
            FakeResponse(status_code=204, json_data={}),
            FakeResponse(json_data=deepcopy(SAMPLE_ISSUE)),
        ],
    )
    client = JiraClient(config=DummyConfig())

    issue = client.update_ticket("ENG-1", summary="Updated summary")

    assert issue["key"] == "ENG-1"
    assert calls[0]["method"] == "PUT"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/issue/ENG-1"
    assert calls[0]["json"]["fields"]["summary"] == "Updated summary"


def test_update_ticket_should_fail_without_updates():
    client = JiraClient(config=DummyConfig())

    with pytest.raises(ClientError, match="No ticket updates"):
        client.update_ticket("ENG-1")


def test_delete_ticket_should_delete_issue(monkeypatch):
    calls = _capture_request(monkeypatch, [FakeResponse(status_code=204, json_data={})])
    client = JiraClient(config=DummyConfig())

    result = client.delete_ticket("ENG-1")

    assert result == {"key": "ENG-1", "deleted": True}
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/issue/ENG-1"
    assert calls[0]["params"] is None


def test_delete_ticket_should_pass_delete_subtasks(monkeypatch):
    calls = _capture_request(monkeypatch, [FakeResponse(status_code=204, json_data={})])
    client = JiraClient(config=DummyConfig())

    result = client.delete_ticket("ENG-1", delete_subtasks=True)

    assert result == {"key": "ENG-1", "deleted": True}
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["params"] == {"deleteSubtasks": "true"}


def test_add_comment_should_post_comment_document(monkeypatch):
    calls = _capture_request(
        monkeypatch,
        [
            FakeResponse(
                json_data={
                    "id": "20001",
                    "body": {"type": "doc", "version": 1, "content": []},
                }
            )
        ],
    )
    client = JiraClient(config=DummyConfig())

    comment = client.add_comment("ENG-1", "Looking into it")

    assert comment["id"] == "20001"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/issue/ENG-1/comment"
    assert calls[0]["json"]["body"]["type"] == "doc"


def test_list_transitions_should_return_transition_array(monkeypatch):
    _capture_request(
        monkeypatch,
        [FakeResponse(json_data={"transitions": [deepcopy(SAMPLE_TRANSITION)]})],
    )
    client = JiraClient(config=DummyConfig())

    transitions = client.list_transitions("ENG-1")

    assert transitions == [
        {
            "id": "31",
            "name": "Done",
            "to_name": "Done",
            "status_category": "Done",
        }
    ]


def test_transition_ticket_should_post_transition_and_fetch_ticket(monkeypatch):
    calls = _capture_request(
        monkeypatch,
        [
            FakeResponse(status_code=204, json_data={}),
            FakeResponse(json_data=deepcopy(SAMPLE_ISSUE)),
        ],
    )
    client = JiraClient(config=DummyConfig())

    issue = client.transition_ticket("ENG-1", "31", comment="Resolved")

    assert issue["key"] == "ENG-1"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://acme.atlassian.net/rest/api/3/issue/ENG-1/transitions"
    assert calls[0]["json"]["transition"] == {"id": "31"}
    assert "comment" in calls[0]["json"]["update"]
