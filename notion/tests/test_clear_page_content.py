"""Regression tests for safe page-content clearing."""

from notion_cli.client import NotionClient


def test_clear_page_content_archives_only_top_level_blocks_sequentially(monkeypatch):
    """Nested descendants must be left to Notion's parent archive cascade."""
    client = object.__new__(NotionClient)
    calls = []

    def fake_get_all(page_id, recursive=True):
        calls.append(("list", page_id, recursive))
        return [
            {"id": "parent", "has_children": True},
            {"id": "sibling", "has_children": False},
        ]

    def fake_delete(block_id):
        calls.append(("delete", block_id))
        return block_id == "parent"

    monkeypatch.setattr(client, "get_block_children_all", fake_get_all)
    monkeypatch.setattr(client, "delete_block_if_present", fake_delete)

    result = client.clear_page_content("page-id")

    assert calls == [
        ("list", "page-id", False),
        ("delete", "parent"),
        ("delete", "sibling"),
    ]
    assert result == {
        "page_id": "page-id",
        "blocks_archived": 1,
        "blocks_already_archived": 1,
    }
