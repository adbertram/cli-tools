"""Regression tests for database page creation."""

import copy
import json

from typer.testing import CliRunner

from notion_cli.client import NotionClient
from notion_cli.commands import database as database_cmd


def test_content_file_over_100_blocks_uses_chunked_upload(monkeypatch, tmp_path):
    markdown_file = tmp_path / "content.md"
    markdown_file.write_text(
        "\n\n".join(f"Paragraph {index}" for index in range(198)),
        encoding="utf-8",
    )

    client = NotionClient.__new__(NotionClient)
    page_posts = []
    uploaded = []

    client.get_database = lambda database_id: {
        "properties": {"Name": {"type": "title"}}
    }
    client.get_data_source_id = lambda database_id, data_source_id=None: "data-source-1"

    def fake_make_request(method, endpoint, data=None, params=None, retry=True):
        assert method == "POST"
        assert endpoint == "/pages"
        page_posts.append(copy.deepcopy(data))
        return {"id": "page-1", "url": "https://notion.so/page-1"}

    def fake_upload(parent_id, blocks, progress_callback=None):
        uploaded.append((parent_id, copy.deepcopy(blocks)))
        return len(blocks), [f"block-{index}" for index in range(len(blocks))]

    client._make_request = fake_make_request
    client._upload_blocks_with_nesting = fake_upload
    monkeypatch.setattr(database_cmd, "get_client", lambda: client)

    result = CliRunner().invoke(
        database_cmd.page_app,
        [
            "create",
            "database-1",
            "--title",
            "Large page",
            "--content-file",
            str(markdown_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "id": "page-1",
        "url": "https://notion.so/page-1",
    }
    assert "Page created successfully: https://notion.so/page-1" in result.stderr
    assert len(page_posts) == 1
    assert "children" not in page_posts[0]
    assert len(uploaded) == 1
    assert uploaded[0][0] == "page-1"
    assert len(uploaded[0][1]) == 198
