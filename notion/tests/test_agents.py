"""Agent API wiring, versions, pagination, and mutation guards."""

import json

from typer.testing import CliRunner

from notion_cli.commands import admin_agents, agents
from notion_cli.client import NotionClient
from notion_cli.main import app


runner = CliRunner()


def test_agent_commands_use_public_version_and_all_pages(monkeypatch):
    calls = []

    class Client:
        def _make_request(self, method, endpoint, data=None, params=None, version=None):
            calls.append((method, endpoint, data, version))
            if len(calls) == 1:
                return {"results": [{"id": "first"}], "has_more": True, "next_cursor": "next"}
            return {"results": [{"id": "second"}], "has_more": False}

    monkeypatch.setattr(agents, "get_client", Client)
    result = runner.invoke(app, ["agents", "list"])
    assert result.exit_code == 0, result.output
    assert [x["id"] for x in json.loads(result.stdout)] == ["first", "second"]
    assert calls[0] == ("POST", "/agents/query", {}, "2026-03-11")
    assert calls[1][2] == {"start_cursor": "next"}


def test_public_agent_status_and_credit_limit(monkeypatch):
    calls = []

    class Client:
        def _make_request(self, method, endpoint, data=None, params=None, version=None):
            calls.append((method, endpoint, data, version))
            return {"ok": True}

    monkeypatch.setattr(agents, "get_client", Client)
    assert runner.invoke(app, ["agents", "status", "agent-id", "disabled"]).exit_code == 0
    assert runner.invoke(app, ["agents", "credit-limit", "agent-id", "--limit", "50"]).exit_code == 0
    assert calls == [
        ("PATCH", "/agents/agent-id/status", {"status": "disabled"}, "2026-03-11"),
        ("PATCH", "/agents/agent-id/credit_limit", {"credit_limit": 50}, "2026-03-11"),
    ]


def test_session_send_and_approval_payloads(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(agents, "_request", lambda method, endpoint, body=None, params=None: calls.append((method, endpoint, body)) or {"id": "session"})
    assert runner.invoke(app, ["agents", "sessions", "send", "Hello", "--agent-id", "agent-id"]).exit_code == 0
    body_file = tmp_path / "approval.json"
    body_file.write_text(json.dumps({"session_id": "session", "actions": [{"action_id": "action", "option_id": "approve"}]}))
    assert runner.invoke(app, ["agents", "sessions", "submit", "--body-file", str(body_file)]).exit_code == 0
    assert calls[0] == ("POST", "/sessions", {"message": "Hello", "agent_id": "agent-id"})
    assert calls[1][2]["actions"][0]["option_id"] == "approve"


def test_delete_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(agents, "_request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("request sent")))
    result = runner.invoke(app, ["agents", "delete", "agent-id"])
    assert result.exit_code != 0
    assert "without --yes" in result.output


def test_admin_uses_separate_org_token_and_version(monkeypatch):
    calls = []

    class Client:
        def __init__(self, token):
            assert token == "org-token"

        def _make_request(self, method, endpoint, **kwargs):
            calls.append((method, endpoint, kwargs))
            return {"status": "disabled"}

    monkeypatch.setattr(admin_agents, "read_cli_tool_secret", lambda name: "org-token" if name == "notion-admin-token" else None)
    monkeypatch.setattr(admin_agents, "NotionClient", Client)
    result = runner.invoke(app, ["admin-agents", "status", "space-id", "agent-id", "disabled"])
    assert result.exit_code == 0, result.output
    assert calls[0][0:2] == ("PATCH", "/spaces/space-id/agents/agent-id/status")
    assert calls[0][2]["data"] == {"admin_status": "disabled"}
    assert calls[0][2]["version"] == "2026-06-01"
    assert calls[0][2]["base_url"] == "https://api.notion.com/admin/v1"


def test_stream_accepts_action_submission_and_has_no_read_timeout(monkeypatch, tmp_path):
    calls = []

    class Client:
        base_url = "https://api.notion.com/v1"
        headers = {"Authorization": "Bearer test"}

    class Response:
        ok = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_lines(self, decode_unicode):
            yield "data: {}"

    monkeypatch.setattr(agents, "get_client", Client)
    monkeypatch.setattr(agents.requests, "post", lambda url, **kwargs: calls.append((url, kwargs)) or Response())
    body_file = tmp_path / "actions.json"
    body_file.write_text(json.dumps({"session_id": "session", "actions": [{"action_id": "action", "option_id": "approve"}]}))
    result = runner.invoke(app, ["agents", "sessions", "stream", "--body-file", str(body_file)])
    assert result.exit_code == 0, result.output
    assert result.stdout == "data: {}\n"
    assert calls[0][1]["timeout"] == (10, None)
    assert calls[0][1]["headers"]["Notion-Version"] == "2026-03-11"


def test_admin_token_works_without_public_integration_token(monkeypatch):
    class Config:
        api_token = None
        api_version = "2025-09-03"

    class Response:
        ok = True
        status_code = 200
        content = b"{}"

        def json(self):
            return {}

    calls = []
    monkeypatch.setattr("notion_cli.client.requests.request", lambda **kwargs: calls.append(kwargs) or Response())
    client = NotionClient(config=Config(), token="admin-token")
    client._make_request("GET", "/spaces/space/agents", version="2026-06-01", base_url="https://api.notion.com/admin/v1")
    assert calls[0]["url"] == "https://api.notion.com/admin/v1/spaces/space/agents"
    assert calls[0]["headers"]["Authorization"] == "Bearer admin-token"
