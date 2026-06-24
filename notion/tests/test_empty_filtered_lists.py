import json

from typer.testing import CliRunner

from notion_cli.commands import database as database_cmd
from notion_cli.commands import page as page_cmd


class SearchClient:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search_all(self, **kwargs):
        self.calls.append(kwargs)
        return self.results


def test_pages_list_filtered_zero_results_exits_success_with_empty_json(monkeypatch):
    client = SearchClient(
        [
            {
                "object": "page",
                "id": "page-1",
                "properties": {
                    "title": {
                        "type": "title",
                        "title": [{"plain_text": "Other Page"}],
                    }
                },
                "parent": {"type": "workspace"},
                "url": "https://example.com/page-1",
                "last_edited_time": "2026-06-20T00:00:00.000Z",
            }
        ]
    )
    monkeypatch.setattr(page_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        page_cmd.app,
        [
            "list",
            "--filter",
            "title:like:%ATA Blog%",
            "--properties",
            "id,title,parent_type,parent_id,url,last_edited",
            "--limit",
            "25",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
    assert "No pages found matching filter." not in result.stdout
    assert "Error: 0" not in result.stderr
    assert "0 page(s) found." in result.stderr
    assert client.calls == [
        {
            "query": None,
            "filter_type": "page",
            "sort_direction": None,
            "limit": 25,
        }
    ]


def test_database_list_filtered_zero_results_exits_success_with_empty_json(monkeypatch):
    client = SearchClient(
        [
            {
                "id": "data-source-1",
                "title": [{"plain_text": "Other Database"}],
                "parent": {"type": "workspace"},
                "url": "https://example.com/data-source-1",
                "last_edited_time": "2026-06-20T00:00:00.000Z",
            }
        ]
    )
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.app,
        [
            "list",
            "--filter",
            "title:eq:Post Performance Snapshots",
            "--limit",
            "10",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
    assert "No databases found matching filter." not in result.stdout
    assert "Error: 0" not in result.stderr
    assert "0 database(s) found." in result.stderr
    assert client.calls == [
        {
            "query": None,
            "filter_type": "data_source",
            "sort_direction": None,
            "limit": 10,
        }
    ]
