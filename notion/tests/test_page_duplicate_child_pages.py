"""Regression coverage for complete child-page duplication."""

import copy

import pytest

from notion_cli.client import ClientError, NotionClient


def paragraph(text):
    return {
        "id": f"source-{text}",
        "type": "paragraph",
        "has_children": False,
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}]
        },
    }


def child_page(page_id, title, children):
    return {
        "id": page_id,
        "type": "child_page",
        "has_children": bool(children),
        "child_page": {"title": title},
        "children": children,
    }


def rich_text(block):
    block_type = block["type"]
    return "".join(
        item.get("text", {}).get("content", "")
        for item in block[block_type].get("rich_text", [])
    )


def test_duplicate_recursively_creates_child_pages_and_preserves_content_order(monkeypatch):
    client = NotionClient.__new__(NotionClient)
    uploads = []
    created_pages = []

    source = [
        paragraph("before"),
        child_page(
            "source-child",
            "Child",
            [
                paragraph("child content"),
                child_page(
                    "source-grandchild",
                    "Grandchild",
                    [paragraph("grandchild content")],
                ),
            ],
        ),
        paragraph("after"),
    ]

    def fake_upload(parent_id, blocks, progress_callback=None):
        uploads.append((parent_id, copy.deepcopy(blocks)))
        return len(blocks), [f"created-block-{len(uploads)}"] * len(blocks)

    def fake_create(parent_page_id, title, icon=None, cover=None, children=None):
        page_id = f"created-{title.lower()}"
        created_pages.append((parent_page_id, title, page_id))
        return {"id": page_id}

    monkeypatch.setattr(client, "_upload_blocks_with_nesting", fake_upload)
    monkeypatch.setattr(client, "create_standalone_page", fake_create)

    client._validate_duplicate_source_blocks(source)
    block_count, page_count = client._upload_duplicate_page_children(
        "created-root", copy.deepcopy(source)
    )

    assert created_pages == [
        ("created-root", "Child", "created-child"),
        ("created-child", "Grandchild", "created-grandchild"),
    ]
    assert [(parent, [rich_text(block) for block in blocks]) for parent, blocks in uploads] == [
        ("created-root", ["before"]),
        ("created-child", ["child content"]),
        ("created-grandchild", ["grandchild content"]),
        ("created-root", ["after"]),
    ]
    assert block_count == 4
    assert page_count == 2


def test_duplicate_preflight_rejects_uncreatable_blocks_before_page_creation(monkeypatch):
    client = NotionClient.__new__(NotionClient)
    created = []
    monkeypatch.setattr(
        client,
        "get_page",
        lambda _page_id: {
            "parent": {"type": "page_id", "page_id": "source-parent"},
            "properties": {
                "title": {
                    "type": "title",
                    "title": [{"plain_text": "Source"}],
                }
            },
        },
    )
    monkeypatch.setattr(
        client,
        "get_block_children_all",
        lambda *_args, **_kwargs: [
            {"id": "database-block", "type": "child_database", "child_database": {}}
        ],
    )
    monkeypatch.setattr(
        client,
        "create_standalone_page",
        lambda **kwargs: created.append(kwargs),
    )

    with pytest.raises(
        ClientError,
        match="Cannot completely duplicate block type 'child_database'",
    ):
        client.duplicate_page("source-page")

    assert created == []


def test_recursive_fetch_propagates_child_page_read_failure(monkeypatch):
    client = NotionClient.__new__(NotionClient)
    blocks = [
        {
            "id": "source-child",
            "type": "child_page",
            "has_children": True,
            "child_page": {"title": "Child"},
        }
    ]

    def fail_read(_block_id):
        raise RuntimeError("child page content read failed")

    monkeypatch.setattr(client, "_fetch_block_children_flat", fail_read)

    with pytest.raises(RuntimeError, match="child page content read failed"):
        client._fetch_children_parallel(blocks, max_workers=1)

    assert "children" not in blocks[0]
