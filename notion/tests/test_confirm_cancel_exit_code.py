"""Declining a destructive-command confirmation must exit 0, not surface as an error.

Regression tests for typer.Exit(0) raised inside a command's try block being
swallowed by the broad `except Exception` handler, which printed "Error: 0"
and exited 1.
"""
from typer.testing import CliRunner

from notion_cli.commands import database as database_cmd
from notion_cli.commands import page as page_cmd


class UnusedClient:
    """Client stub for paths that must exit before any API call."""


def test_pages_delete_cancel_exits_zero(monkeypatch):
    monkeypatch.setattr(page_cmd, "get_client", lambda: UnusedClient())

    result = CliRunner().invoke(page_cmd.app, ["delete", "page-1"], input="n\n")

    assert result.exit_code == 0
    assert "Cancelled." in result.stdout
    assert "Error: 0" not in result.stderr


def test_database_page_delete_cancel_exits_zero(monkeypatch):
    monkeypatch.setattr(database_cmd, "get_client", lambda: UnusedClient())

    result = CliRunner().invoke(
        database_cmd.app, ["page", "delete", "page-1"], input="n\n"
    )

    assert result.exit_code == 0
    assert "Cancelled." in result.stdout
    assert "Error: 0" not in result.stderr
