"""Regression tests for Notion's per-block 2000-char rich_text limit.

These cover the data-loss hazard where `content set` cleared a page and then
failed mid-upload on a >2000-char paragraph, leaving the page empty. The fix:

1. enforce_block_limits splits any oversize rich_text segment into valid blocks
   end-to-end through the upload path (no segment > 2000 chars; original text
   preserved across the split).
2. content_set transforms + validates the whole payload BEFORE the destructive
   clear, so a genuinely invalid block is rejected before any data is destroyed.
"""
import copy

import pytest

from notion_cli.block_limits import (
    MAX_RICH_TEXT_CONTENT,
    enforce_block_limits,
    find_oversize_rich_text,
)
from notion_cli.client import NotionClient
from notion_cli.commands import page


def _paragraph(content):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
    }


def _all_text(block):
    """Concatenate every text.content segment in a paragraph block."""
    return "".join(
        seg["text"]["content"] for seg in block["paragraph"]["rich_text"]
    )


# ---------------------------------------------------------------------------
# (a) no resulting block/segment exceeds 2000 chars
# (b) the original text is preserved across the split (round-trips)
# ---------------------------------------------------------------------------


def test_oversize_paragraph_splits_into_valid_segments_and_round_trips():
    # ~3000 chars with whitespace so it splits on a word boundary.
    original = ("word " * 600).strip()
    assert len(original) > MAX_RICH_TEXT_CONTENT

    out = enforce_block_limits([_paragraph(original)])

    # Stays a single block (segments split, block not overflowed at this size).
    assert len(out) == 1
    segments = out[0]["paragraph"]["rich_text"]
    assert len(segments) > 1
    # (a) every segment is within the limit
    assert all(len(s["text"]["content"]) <= MAX_RICH_TEXT_CONTENT for s in segments)
    # (b) concatenation reproduces the original exactly
    assert _all_text(out[0]) == original
    # validator agrees the payload is now safe
    assert find_oversize_rich_text(out) is None


def test_single_token_longer_than_limit_hard_splits_and_round_trips():
    original = "x" * 5000  # no whitespace -> forced hard split
    out = enforce_block_limits([_paragraph(original)])

    segments = out[0]["paragraph"]["rich_text"]
    assert all(len(s["text"]["content"]) <= MAX_RICH_TEXT_CONTENT for s in segments)
    assert _all_text(out[0]) == original
    assert find_oversize_rich_text(out) is None


def test_split_preserves_annotations_and_links_on_every_segment():
    original = "a " * 1500  # > 2000 chars
    block = {
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": original, "link": {"url": "https://example.com"}},
                    "annotations": {"bold": True},
                }
            ]
        },
    }

    out = enforce_block_limits([block])
    segments = out[0]["paragraph"]["rich_text"]

    assert len(segments) > 1
    assert all(s["annotations"]["bold"] is True for s in segments)
    assert all(s["text"]["link"]["url"] == "https://example.com" for s in segments)
    assert _all_text(out[0]) == original


def test_array_over_100_elements_overflows_into_sibling_blocks():
    # 130 chunks of ~2000 chars each -> >100 segments after splitting, which
    # exceeds Notion's 100-element rich_text array cap, forcing sibling blocks.
    original = ("x" * 2000 + " ") * 130
    out = enforce_block_limits([_paragraph(original)])

    assert len(out) > 1  # split into sibling blocks
    assert all(
        len(b["paragraph"]["rich_text"]) <= 100 for b in out
    )
    # Concatenating segments across all sibling blocks round-trips the original.
    joined = "".join(_all_text(b) for b in out)
    assert joined == original
    assert find_oversize_rich_text(out) is None


def test_oversize_content_in_nested_children_is_split():
    block = {
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "Toggle"}}],
            "children": [_paragraph("b " * 1500)],
        },
    }

    out = enforce_block_limits([block])
    child = out[0]["toggle"]["children"][0]
    assert len(child["paragraph"]["rich_text"]) > 1
    assert find_oversize_rich_text(out) is None


def test_enforce_does_not_mutate_input():
    original = ("word " * 600).strip()
    block = _paragraph(original)
    snapshot = copy.deepcopy(block)

    enforce_block_limits([block])

    assert block == snapshot  # input untouched


def test_non_text_segments_pass_through_untouched():
    block = {
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "mention", "mention": {"type": "page", "page": {"id": "x"}}}]
        },
    }
    out = enforce_block_limits([block])
    assert out[0]["paragraph"]["rich_text"][0]["type"] == "mention"


def test_find_oversize_rich_text_detects_invalid_segment():
    bad = _paragraph("z" * 3000)
    where = find_oversize_rich_text([bad])
    assert where is not None
    assert "2000" in where


# ---------------------------------------------------------------------------
# (c) content set must transform/validate BEFORE the destructive clear, and the
#     clear must not happen when a block is genuinely invalid.
# ---------------------------------------------------------------------------


class RecordingClient:
    """Mock NotionClient that records the order of clear vs. upload calls."""

    def __init__(self, fail_validation=False):
        self.events = []
        self.uploaded_blocks = None
        self._fail_validation = fail_validation

    def clear_page_content(self, page_id):
        self.events.append(("clear", page_id))

    def _upload_blocks_with_nesting(self, parent_id, blocks, progress_callback=None):
        self.events.append(("upload", parent_id))
        self.uploaded_blocks = copy.deepcopy(blocks)
        # The real client runs enforce_block_limits internally; assert the
        # payload it receives is already safe to upload.
        assert find_oversize_rich_text(blocks) is None
        return len(blocks), [f"id-{i}" for i in range(len(blocks))]


def test_content_set_splits_oversize_paragraph_before_clearing(monkeypatch, tmp_path):
    """End-to-end: a >2000-char markdown paragraph is split, then uploaded.

    Asserts the clear happens before the upload (real order) but only AFTER the
    payload has been transformed to a valid shape, and that every uploaded
    segment is within the 2000-char limit.
    """
    client = RecordingClient()
    md = tmp_path / "big.md"
    md.write_text(("word " * 600).strip(), encoding="utf-8")

    printed = []
    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "print_success", lambda msg: None)
    monkeypatch.setattr(page, "print_json", printed.append)

    page.content_set(
        "page-123",
        text=None,
        file=str(md),
        json_file=None,
        is_toggleable=False,
    )

    # Clear happened, upload happened, and the uploaded payload is valid.
    assert ("clear", "page-123") in client.events
    assert ("upload", "page-123") in client.events
    assert client.events.index(("clear", "page-123")) < client.events.index(
        ("upload", "page-123")
    )
    assert find_oversize_rich_text(client.uploaded_blocks) is None
    assert printed and printed[0]["page_id"] == "page-123"


def test_content_set_does_not_clear_when_block_cannot_be_made_valid(monkeypatch, tmp_path):
    """If a block stays oversize after transform, the page is NOT cleared.

    enforce_block_limits handles real markdown, so to exercise the pre-clear
    guard we feed a --json-file block whose transform is bypassed by forcing the
    validator to report it as invalid. The clear must never run.
    """
    client = RecordingClient()
    blocks_json = tmp_path / "blocks.json"
    blocks_json.write_text("[{\"type\": \"paragraph\", \"paragraph\": {\"rich_text\": []}}]", encoding="utf-8")

    warnings = []
    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "print_warning", warnings.append)
    # Force the post-transform validator to report an unfixable oversize block.
    monkeypatch.setattr(
        page, "_find_oversize_rich_text", lambda blocks: "blocks[0].paragraph.rich_text[0].text.content is 9999 chars (limit 2000)"
    )

    with pytest.raises(page.typer.Exit) as exc:
        page.content_set(
            "page-456",
            text=None,
            file=None,
            json_file=str(blocks_json),
            is_toggleable=False,
        )

    assert exc.value.exit_code == 1
    # CRITICAL: the destructive clear must NOT have run.
    assert all(event[0] != "clear" for event in client.events)
    assert any("left untouched" in w for w in warnings)


def test_create_standalone_page_enforces_limits_on_inline_children():
    """Page-create with oversize inline children does not send an invalid block.

    create_standalone_page posts children directly (not via the append path), so
    it must enforce the per-block limit itself.
    """
    client = NotionClient.__new__(NotionClient)
    captured = {}

    def fake_make_request(method, endpoint, data=None, params=None, retry=True):
        captured["data"] = data
        return {"id": "new-page"}

    client._make_request = fake_make_request

    oversize = _paragraph(("word " * 600).strip())
    client.create_standalone_page(
        parent_page_id="parent",
        title="T",
        children=[oversize],
    )

    sent_children = captured["data"]["children"]
    assert find_oversize_rich_text(sent_children) is None
    assert len(sent_children[0]["paragraph"]["rich_text"]) > 1


def test_content_set_reports_partial_state_on_upload_failure(monkeypatch, tmp_path):
    """A true mid-upload failure AFTER the clear surfaces an explicit error."""

    class FailingUploadClient(RecordingClient):
        def _upload_blocks_with_nesting(self, parent_id, blocks, progress_callback=None):
            self.events.append(("upload", parent_id))
            raise RuntimeError("network drop")

    client = FailingUploadClient()
    md = tmp_path / "small.md"
    md.write_text("hello world", encoding="utf-8")

    warnings = []
    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "print_warning", warnings.append)

    with pytest.raises(page.typer.Exit) as exc:
        page.content_set(
            "page-789",
            text=None,
            file=str(md),
            json_file=None,
            is_toggleable=False,
        )

    assert exc.value.exit_code == 1
    # The clear ran (it's the documented behavior) and the failure is explicit.
    assert ("clear", "page-789") in client.events
    assert any("may now be empty or partially populated" in w for w in warnings)
