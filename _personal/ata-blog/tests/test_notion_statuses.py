"""Regression tests for live Notion status discovery."""

from __future__ import annotations

import json
import subprocess

from typer.testing import CliRunner

from ata_blog_cli.client import AtaBlogClient
from ata_blog_cli.commands import notion_page


def test_get_valid_statuses_reads_live_notion_schema_options():
    client = object.__new__(AtaBlogClient)
    client.config = type("Config", (), {"notion_database_id": "database-id"})()

    schema = {
        "properties": {
            "Status": {
                "type": "status",
                "options": [
                    "Idea",
                    "Final Human Review",
                    "Ready to Publish",
                    "Published",
                ],
            }
        }
    }

    calls = []

    def fake_run_notion(args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(schema), stderr="")

    client._run_notion = fake_run_notion

    assert client.get_valid_statuses() == [
        "Idea",
        "Final Human Review",
        "Ready to Publish",
        "Published",
    ]
    assert calls == [["database", "schema", "database-id"]]


def test_notion_page_statuses_command_uses_client_live_statuses(monkeypatch):
    class FakeClient:
        def get_valid_statuses(self):
            return ["Ready to Publish", "Published"]

    monkeypatch.setattr(notion_page, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(notion_page.app, ["statuses", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == ["Ready to Publish", "Published"]
