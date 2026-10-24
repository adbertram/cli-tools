"""Regression tests for Notion page JSON output."""

from __future__ import annotations

import json
import subprocess

from typer.testing import CliRunner

from ata_blog_cli.client import AtaBlogClient
from ata_blog_cli.commands import notion_page


def test_list_articles_accepts_raw_control_characters_from_notion(monkeypatch):
    """Notion list output with raw text controls should be normalized by ATA Blog."""

    client = object.__new__(AtaBlogClient)
    client.config = type("Config", (), {"notion_database_id": "database-id"})()

    raw_stdout = '[{"id":"page-id","Title":"Line one\nLine two\u001fEnd"}]'

    def fake_run_notion(args):
        assert args == [
            "database",
            "page",
            "list",
            "-d",
            "database-id",
            "--limit",
            "100",
        ]
        return subprocess.CompletedProcess(args, 0, stdout=raw_stdout, stderr="")

    monkeypatch.setattr(client, "_run_notion", fake_run_notion)

    articles = client.list_articles()

    assert articles == [{"id": "page-id", "Title": "Line one\nLine two\u001fEnd"}]


def test_notion_page_list_prints_valid_json_with_control_characters(monkeypatch):
    """The CLI boundary must emit JSON that Python json.loads can parse."""

    class FakeClient:
        def list_articles(self, status=None, limit=100, filters=None):
            assert status is None
            assert limit == 100
            assert filters is None
            return [
                {
                    "id": "page-id",
                    "Title": "Line one\nLine two\u001fEnd",
                    "Status": "Draft",
                    "Excerpt": "Paragraph\r\nNext",
                    "Category": "IT Ops",
                    "Keywords": "json, notion",
                    "Tags": "automation",
                    "Schema Type": "TechArticle",
                }
            ]

    monkeypatch.setattr(notion_page, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(
        notion_page.app,
        [
            "list",
            "--properties",
            "id,Title,Status,Category,Keywords,Tags,Excerpt,Schema Type",
        ],
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed[0]["Title"] == "Line one\nLine two\u001fEnd"
    assert "\\u001f" in result.output


def test_notion_page_search_no_match_emits_empty_json_and_succeeds(monkeypatch):
    """An expected search miss remains valid structured output for automation."""

    class FakeClient:
        def search_articles(self, query, status=None, limit=100):
            assert query == "certification"
            assert status is None
            assert limit == 100
            return []

    monkeypatch.setattr(notion_page, "get_client", lambda: FakeClient())

    result = CliRunner().invoke(
        notion_page.app,
        ["search", "certification", "--limit", "100"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
    assert "NO_MATCH: No articles found matching 'certification'" in result.stderr
