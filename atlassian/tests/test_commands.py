import json

from typer.testing import CliRunner

from atlassian_cli.main import app
from atlassian_cli.models import create_item


class FakeClient:
    def __init__(self, items):
        self._items = items

    def list_items(self, limit=100, filters=None):
        return self._items[:limit]

    def close(self):
        return None


def test_search_list_outputs_json(monkeypatch):
    item = create_item(
        {
            "id": "atlassian-affiliate-program",
            "name": "Atlassian Affiliate Program",
            "description": "Join the Atlassian affiliate program.",
        }
    )
    monkeypatch.setattr("atlassian_cli.commands.get_client", lambda: FakeClient([item]))

    result = CliRunner().invoke(app, ["search", "list", "--limit", "1"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "id": "atlassian-affiliate-program",
            "name": "Atlassian Affiliate Program",
            "status": "active",
            "item_type": None,
            "description": "Join the Atlassian affiliate program.",
            "tags": [],
        }
    ]


def test_search_list_outputs_default_table(monkeypatch):
    item = create_item(
        {
            "id": "atlassian-affiliate-program",
            "name": "Atlassian Affiliate Program",
            "description": "Join the Atlassian affiliate program.",
        }
    )
    monkeypatch.setattr("atlassian_cli.commands.get_client", lambda: FakeClient([item]))

    result = CliRunner().invoke(app, ["search", "list", "--limit", "1", "--table"])

    assert result.exit_code == 0
    assert "Id" in result.stdout
    assert "Name" in result.stdout
    assert "Status" in result.stdout
    assert "atlassian-affiliate-program" in result.stdout
    assert "Atlassian Affiliate Program" in result.stdout
    assert "active" in result.stdout
