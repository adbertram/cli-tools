"""An empty list result is success: exit 0, `[]` for JSON, no stderr message."""

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from google_cli.commands import analytics, calendar, chat, gmail
from google_cli.main import app


def _client(monkeypatch, module, getter, service):
    client = MagicMock()
    getattr(client, getter).return_value = service
    monkeypatch.setattr(module, "get_client", lambda profile=None: client)


def _calendar_service():
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {"items": []}
    return service


def _analytics_service():
    service = MagicMock()
    service.accountSummaries.return_value.list.return_value.execute.return_value = {}
    service.properties.return_value.runReport.return_value.execute.return_value = {}
    return service


def _chat_service():
    service = MagicMock()
    service.spaces.return_value.list.return_value.execute.return_value = {}
    service.spaces.return_value.messages.return_value.list.return_value.execute.return_value = {}
    return service


def _gmail_service():
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {}
    return service


CASES = [
    (calendar, "get_calendar_service", _calendar_service, ["calendar", "list"]),
    (calendar, "get_calendar_service", _calendar_service, ["calendar", "search", "nothing"]),
    (calendar, "get_calendar_service", _calendar_service, ["calendar", "today"]),
    (analytics, "get_analytics_admin_service", _analytics_service, ["analytics", "accounts"]),
    (analytics, "get_analytics_admin_service", _analytics_service, ["analytics", "properties"]),
    (chat, "get_chat_service", _chat_service, ["chat", "spaces", "list"]),
    (chat, "get_chat_service", _chat_service, ["chat", "messages", "list", "--space", "AAAA"]),
    (gmail, "get_gmail_service", _gmail_service, ["gmail", "list"]),
    (gmail, "get_gmail_service", _gmail_service, ["gmail", "search", "nothing"]),
]


@pytest.mark.parametrize("module,getter,make_service,args", CASES, ids=[" ".join(c[3]) for c in CASES])
def test_empty_list_is_success_json(monkeypatch, module, getter, make_service, args):
    _client(monkeypatch, module, getter, make_service())

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []


@pytest.mark.parametrize("module,getter,make_service,args", CASES, ids=[" ".join(c[3]) for c in CASES])
def test_empty_list_is_success_table(monkeypatch, module, getter, make_service, args):
    _client(monkeypatch, module, getter, make_service())

    result = CliRunner().invoke(app, [*args, "--table"])

    assert result.exit_code == 0, result.output
