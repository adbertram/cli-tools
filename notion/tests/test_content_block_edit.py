"""Tests for non-destructive, block-level content edits on database pages.

Covers `notion database page content update-block` (in-place PATCH of a single
block, preserving its block ID and thus its anchored comments) and
`notion database page content list-blocks` (map paragraphs to block IDs).
"""
import pytest

from notion_cli.commands import database as database_cmd
from notion_cli.commands import page as page_cmd


def block(block_id, block_type="paragraph", text="", has_children=False, **extra):
    """Build a minimal raw Notion block as the API returns it."""
    content = {"rich_text": [{"plain_text": text}]} if text else {"rich_text": []}
    content.update(extra)
    return {
        "id": block_id,
        "type": block_type,
        "has_children": has_children,
        block_type: content,
    }


class FakeUpdateBlockClient:
    def __init__(self, current_block):
        self._current_block = current_block
        self.update_calls = []

    def get_block(self, block_id):
        assert block_id == self._current_block["id"]
        return self._current_block

    def update_block(self, block_id, block_data):
        self.update_calls.append((block_id, block_data))
        # Echo back an updated block reflecting the patch, keeping the SAME id.
        # Notion returns rich_text entries carrying plain_text, so mirror the
        # patched text.content into plain_text the way the real API does.
        block_type = self._current_block["type"]
        updated = dict(self._current_block)
        merged = dict(self._current_block.get(block_type, {}))
        patch = block_data.get(block_type, {})
        if "rich_text" in patch:
            merged["rich_text"] = [
                {"plain_text": rt.get("text", {}).get("content", ""), **rt}
                for rt in patch["rich_text"]
            ]
        for key, value in patch.items():
            if key != "rich_text":
                merged[key] = value
        updated[block_type] = merged
        return updated


def test_update_block_patches_in_place_preserving_block_id(monkeypatch):
    """--text issues a PATCH that keeps the same block ID (so comments survive)."""
    original = block("block-A", "paragraph", "Old text.")
    client = FakeUpdateBlockClient(original)
    printed = []

    monkeypatch.setattr(database_cmd, "get_client", lambda: client)
    monkeypatch.setattr(database_cmd, "print_json", printed.append)
    monkeypatch.setattr(database_cmd, "print_success", lambda *a, **k: None)

    database_cmd.content_update_block(
        block_id="block-A",
        text="New text.",
        checked=None,
        table=False,
    )

    assert len(client.update_calls) == 1
    patched_id, patch = client.update_calls[0]
    # Same block ID is targeted -> Notion preserves the block and its comments.
    assert patched_id == "block-A"
    assert patch["paragraph"]["rich_text"][0]["text"]["content"] == "New text."
    # The displayed result still carries the original block ID.
    assert printed[0]["id"] == "block-A"
    assert printed[0]["text"] == "New text."


def test_update_block_to_do_checked_flag(monkeypatch):
    """--checked updates the to_do checked state in place."""
    original = block("todo-1", "to_do", "A task", checked=False)
    client = FakeUpdateBlockClient(original)

    monkeypatch.setattr(database_cmd, "get_client", lambda: client)
    monkeypatch.setattr(database_cmd, "print_json", lambda *a, **k: None)
    monkeypatch.setattr(database_cmd, "print_success", lambda *a, **k: None)

    database_cmd.content_update_block(
        block_id="todo-1",
        text=None,
        checked=True,
        table=False,
    )

    patched_id, patch = client.update_calls[0]
    assert patched_id == "todo-1"
    assert patch["to_do"]["checked"] is True


def test_update_block_rejects_uneditable_type(monkeypatch):
    """Block types without a single editable rich_text array are refused."""
    original = block("img-1", "image")
    client = FakeUpdateBlockClient(original)
    warnings = []

    monkeypatch.setattr(database_cmd, "get_client", lambda: client)
    monkeypatch.setattr(database_cmd, "print_warning", warnings.append)

    with pytest.raises(Exception):  # typer.Exit
        database_cmd.content_update_block(
            block_id="img-1",
            text="cannot edit",
            checked=None,
            table=False,
        )

    # No PATCH is attempted for an uneditable type.
    assert client.update_calls == []
    assert warnings and "image" in warnings[0]


def test_update_block_requires_text_or_checked(monkeypatch):
    """Calling with neither --text nor --checked is a usage error, no API call."""
    client = FakeUpdateBlockClient(block("block-A", "paragraph", "Old"))
    warnings = []

    monkeypatch.setattr(database_cmd, "get_client", lambda: client)
    monkeypatch.setattr(database_cmd, "print_warning", warnings.append)

    with pytest.raises(Exception):  # typer.Exit
        database_cmd.content_update_block(
            block_id="block-A",
            text=None,
            checked=None,
            table=False,
        )

    assert client.update_calls == []
    assert warnings


def test_update_block_checked_rejected_on_non_todo(monkeypatch):
    """--checked only applies to to_do; other types are refused before PATCH."""
    client = FakeUpdateBlockClient(block("p-1", "paragraph", "text"))
    warnings = []

    monkeypatch.setattr(database_cmd, "get_client", lambda: client)
    monkeypatch.setattr(database_cmd, "print_warning", warnings.append)

    with pytest.raises(Exception):  # typer.Exit
        database_cmd.content_update_block(
            block_id="p-1",
            text=None,
            checked=True,
            table=False,
        )

    assert client.update_calls == []
    assert warnings


def test_pages_blocks_update_markdown_builds_rich_text(monkeypatch):
    """pages blocks update --markdown PATCHes parsed rich_text in place."""
    client = FakeUpdateBlockClient(block("block-A", "paragraph", "Old text."))

    monkeypatch.setattr(page_cmd, "get_client", lambda: client)
    monkeypatch.setattr(page_cmd, "print_json", lambda *a, **k: None)
    monkeypatch.setattr(page_cmd, "print_success", lambda *a, **k: None)

    page_cmd.blocks_update(
        block_id="block-A",
        text=None,
        markdown="Read [Demo Overview](https://example.com/demo) and `code`.",
        md_file=None,
        checked=None,
        json_data=None,
        json_file=None,
        toggleable=None,
        no_nest=False,
    )

    patched_id, patch = client.update_calls[0]
    rich_text = patch["paragraph"]["rich_text"]
    assert patched_id == "block-A"
    assert rich_text[1]["text"]["content"] == "Demo Overview"
    assert rich_text[1]["text"]["link"]["url"] == "https://example.com/demo"
    assert rich_text[3]["text"]["content"] == "code"
    assert rich_text[3]["annotations"]["code"] is True


def test_pages_blocks_update_md_file_builds_rich_text(monkeypatch, tmp_path):
    """pages blocks update --md-file reads Markdown and PATCHes parsed rich_text."""
    markdown_file = tmp_path / "block.md"
    markdown_file.write_text("Read **Demo Overview**.", encoding="utf-8")
    client = FakeUpdateBlockClient(block("block-A", "paragraph", "Old text."))

    monkeypatch.setattr(page_cmd, "get_client", lambda: client)
    monkeypatch.setattr(page_cmd, "print_json", lambda *a, **k: None)
    monkeypatch.setattr(page_cmd, "print_success", lambda *a, **k: None)

    page_cmd.blocks_update(
        block_id="block-A",
        text=None,
        markdown=None,
        md_file=str(markdown_file),
        checked=None,
        json_data=None,
        json_file=None,
        toggleable=None,
        no_nest=False,
    )

    rich_text = client.update_calls[0][1]["paragraph"]["rich_text"]
    assert rich_text[1]["text"]["content"] == "Demo Overview"
    assert rich_text[1]["annotations"]["bold"] is True


class FakeListBlocksClient:
    def __init__(self, blocks):
        self._blocks = blocks
        self.calls = []

    def get_block_children_all(self, block_id, recursive=True, limit=None):
        self.calls.append({"block_id": block_id, "recursive": recursive, "limit": limit})
        return self._blocks


def test_list_blocks_returns_id_type_and_text(monkeypatch):
    """list-blocks maps each block to its ID, type, and text for targeted edits."""
    blocks = [
        block("block-A", "paragraph", "Block A original text."),
        block("block-B", "paragraph", "Block B original text."),
        block("h", "heading_2", "A heading"),
    ]
    client = FakeListBlocksClient(blocks)
    printed = []

    monkeypatch.setattr(database_cmd, "get_client", lambda: client)
    monkeypatch.setattr(database_cmd, "print_json", printed.append)

    database_cmd.content_list_blocks(
        page_id="page-1",
        recursive=False,
        table=False,
        limit=None,
        filter=None,
        properties=None,
    )

    result = printed[0]
    assert [b["id"] for b in result] == ["block-A", "block-B", "h"]
    assert [b["type"] for b in result] == ["paragraph", "paragraph", "heading_2"]
    assert result[0]["text"] == "Block A original text."


def test_list_blocks_filter_by_type(monkeypatch):
    """--filter narrows the listing client-side."""
    blocks = [
        block("block-A", "paragraph", "para"),
        block("h", "heading_2", "head"),
    ]
    client = FakeListBlocksClient(blocks)
    printed = []

    monkeypatch.setattr(database_cmd, "get_client", lambda: client)
    monkeypatch.setattr(database_cmd, "print_json", printed.append)

    database_cmd.content_list_blocks(
        page_id="page-1",
        recursive=False,
        table=False,
        limit=None,
        filter=["type:eq:heading_2"],
        properties=None,
    )

    result = printed[0]
    assert [b["id"] for b in result] == ["h"]
