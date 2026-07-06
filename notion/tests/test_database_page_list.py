import json

from typer.testing import CliRunner

from notion_cli.commands import database as database_cmd


class EmptyPagesClient:
    def __init__(self):
        self.calls = []

    def query_database_all(self, **kwargs):
        self.calls.append(kwargs)
        return []


class SinglePageClient:
    def __init__(self):
        self.calls = []

    def query_database_all(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {
                "id": "page-1",
                "url": "https://notion.so/page-1",
                "properties": {
                    "Name": {
                        "type": "title",
                        "title": [{"plain_text": "Acme"}],
                    },
                    "Website": {
                        "type": "url",
                        "url": "https://example.com",
                    },
                    "Contact Email": {
                        "type": "email",
                        "email": "person@example.com",
                    },
                    "Status": {
                        "type": "status",
                        "status": {"name": "New"},
                    },
                },
            }
        ]


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


def test_page_list_properties_accepts_quoted_comma_list_with_spaced_name(monkeypatch):
    client = SinglePageClient()
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app,
        [
            "list",
            "-d",
            "db-leads",
            "--properties",
            "id,Name,Website,Contact Email",
            "--limit",
            "10",
        ],
    )

    assert result.exit_code == 0
    rows = json.loads(result.stdout)
    assert rows == [
        {
            "id": "page-1",
            "url": "https://notion.so/page-1",
            "Name": "Acme",
            "Website": "https://example.com",
            "Contact Email": "person@example.com",
        }
    ]
    assert "Status" not in rows[0]
    assert client.calls == [
        {
            "database_id": "db-leads",
            "filter_obj": None,
            "sorts": None,
            "limit": 10,
            "data_source_id": None,
        }
    ]
