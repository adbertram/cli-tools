import json

from typer.testing import CliRunner

from notion_cli.commands import database as database_cmd


class EmptyPagesClient:
    def __init__(self):
        self.calls = []

    def query_database_all(self, **kwargs):
        self.calls.append(kwargs)
        return []


def test_page_list_zero_results_exits_success_with_empty_json(monkeypatch):
    client = EmptyPagesClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app,
        ["list", "-d", "db-empty", "--limit", "10"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
    assert "No pages found." not in result.stdout
    assert "Error: 0" not in result.stderr
    assert "0 page(s) found." in result.stderr
    assert client.calls == [
        {
            "database_id": "db-empty",
            "filter_obj": None,
            "sorts": None,
            "limit": 10,
            "data_source_id": None,
        }
    ]
