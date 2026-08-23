"""Regression tests for database page updates (repeatable --select/--status)."""

import json

from typer.testing import CliRunner

from notion_cli.client import NotionClient
from notion_cli.commands import database as database_cmd


def _client_capturing_updates(monkeypatch):
    """Build a fake client whose update_page captures the properties payload."""
    client = NotionClient.__new__(NotionClient)
    captured = {}

    def fake_update_page(page_id=None, properties=None, archived=None, **kwargs):
        captured.update(properties or {})
        return {"id": "page-1", "url": "https://notion.so/page-1"}

    client.update_page = fake_update_page
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)
    return captured


def test_page_update_two_select_flags_set_both_properties(monkeypatch):
    captured = _client_capturing_updates(monkeypatch)

    result = CliRunner().invoke(
        database_cmd.page_app,
        [
            "update",
            "page-1",
            "--select",
            "Client:Progress",
            "--select",
            "Contact:Mandy Mowers",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "Client": {"select": {"name": "Progress"}},
        "Contact": {"select": {"name": "Mandy Mowers"}},
    }
    # Success message belongs on stderr; stdout stays clean JSON.
    assert "Page page-1 updated successfully." in result.stderr


def test_page_update_two_status_flags_set_both_properties(monkeypatch):
    captured = _client_capturing_updates(monkeypatch)

    result = CliRunner().invoke(
        database_cmd.page_app,
        [
            "update",
            "page-1",
            "--status",
            "Phase:Pending",
            "--status",
            "Priority:High",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "Phase": {"status": {"name": "Pending"}},
        "Priority": {"status": {"name": "High"}},
    }


def test_page_update_select_without_colon_fails_cleanly(monkeypatch):
    captured = _client_capturing_updates(monkeypatch)

    result = CliRunner().invoke(
        database_cmd.page_app,
        ["update", "page-1", "--select", "MissingColon"],
    )

    assert result.exit_code == 1
    assert captured == {}
    assert "--select requires 'property:value' format" in result.stderr
