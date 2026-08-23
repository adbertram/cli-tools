"""Regression tests for `notion pages blocks list` pagination + `blocks append --after`.

Two bugs were pinned here:

  Bug 1 (data loss on read): `pages blocks list` returned only the first 100
  child blocks. The Notion children endpoint (`GET /v1/blocks/{id}/children`)
  defaults to page_size=100 and returns `has_more` + `next_cursor`. The client's
  `get_block_children_all` already paginates fully when given `limit=None`, but
  the command hard-coded `--limit` to 100 AND re-sliced `[:limit]`, capping the
  default result at 100 even on pages with >100 blocks. The fix makes `--limit`
  default to None (return the COMPLETE list) and only cap when explicitly set.

  Bug 2 (miscounted, NOT lost, on `--after`): `pages blocks append --after`
  sends a single PATCH with `after`. Notion's response `results` contains EVERY
  child after the insertion point (the existing tail re-listed), so counting
  `len(results)` reported far more "created" than were inserted. No blocks are
  dropped (the CLI never re-fetches/recreates the tail), but the count was
  wrong. The fix reports `len(blocks)` -- the number actually inserted.

These tests assert the FULL block set is returned/preserved across >100-block
pages with multi-page has_more/next_cursor responses.
"""
import json

import pytest
import typer

from notion_cli.client import NotionClient
from notion_cli.commands import page


def _block(block_id, *, block_type="paragraph"):
    return {
        "id": block_id,
        "object": "block",
        "type": block_type,
        "has_children": False,
        block_type: {"rich_text": [{"plain_text": block_id}]},
    }


def _paginated_children_responses(total, page_size=100):
    """Build the sequence of `/blocks/{id}/children` responses for `total`
    blocks, split into pages of `page_size`, each with has_more/next_cursor
    exactly like the real Notion API.
    """
    blocks = [_block(f"b{i:04d}") for i in range(total)]
    responses = []
    for start in range(0, total, page_size):
        chunk = blocks[start:start + page_size]
        is_last = (start + page_size) >= total
        responses.append({
            "object": "list",
            "results": chunk,
            "has_more": not is_last,
            "next_cursor": None if is_last else f"cursor-{start + page_size}",
        })
    return blocks, responses


def _client_with_children(total, page_size=100):
    """A NotionClient whose `get_block_children` walks a multi-page response
    sequence, recording the page_size + start_cursor it was called with.
    """
    blocks, responses = _paginated_children_responses(total, page_size)
    client = NotionClient.__new__(NotionClient)

    state = {"calls": []}

    def fake_get_block_children(block_id, page_size=100, start_cursor=None):
        state["calls"].append({"page_size": page_size, "start_cursor": start_cursor})
        # Map the cursor back to the right page. First call has no cursor.
        if start_cursor is None:
            return responses[0]
        index = int(start_cursor.split("-")[1]) // 100
        return responses[index]

    client.get_block_children = fake_get_block_children
    return client, blocks, state


# ---------------------------------------------------------------------------
# Client-level: get_block_children_all paginates ALL children by default
# ---------------------------------------------------------------------------

def test_get_block_children_all_returns_every_block_across_pages():
    """117 blocks span two children pages; with no limit ALL must be returned."""
    client, blocks, state = _client_with_children(total=117)

    result = client.get_block_children_all("page-x", recursive=False, limit=None)

    assert len(result) == 117, "every block across all has_more pages must return"
    assert [b["id"] for b in result] == [b["id"] for b in blocks]
    # Two pages fetched (100 + 17): pagination actually followed next_cursor.
    assert len(state["calls"]) == 2
    assert state["calls"][0]["start_cursor"] is None
    assert state["calls"][1]["start_cursor"] == "cursor-100"


def test_get_block_children_all_explicit_limit_caps_and_stops_early():
    """An explicit limit caps the result and avoids fetching extra pages."""
    client, _blocks, state = _client_with_children(total=250)

    result = client.get_block_children_all("page-x", recursive=False, limit=100)

    assert len(result) == 100
    # Only the first page was needed to satisfy a 100 limit.
    assert len(state["calls"]) == 1


# ---------------------------------------------------------------------------
# Command-level: `pages blocks list` returns the COMPLETE list by default
# ---------------------------------------------------------------------------

class _ListCommandClient:
    """Records the limit `blocks_list` passes to get_block_children_all and
    returns a >100-block list so the command's own slice logic is exercised."""

    def __init__(self, total=117):
        self.blocks = [_block(f"b{i:04d}") for i in range(total)]
        self.calls = []

    def get_block_children_all(self, page_id, recursive=True, limit=None):
        self.calls.append({"recursive": recursive, "limit": limit})
        # Mirror the real client: None == all; a number caps.
        if limit is None:
            return list(self.blocks)
        return self.blocks[:limit]


def _run_blocks_list(client, monkeypatch, **overrides):
    printed = []
    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "print_json", printed.append)
    kwargs = dict(
        page_id="page-x",
        recursive=False,
        table=False,
        markdown=False,
        limit=None,
        filter=None,
        properties=None,
    )
    kwargs.update(overrides)
    page.blocks_list(**kwargs)
    return printed


def test_blocks_list_default_returns_all_blocks_over_100(monkeypatch):
    """Default (no --limit) returns the full >100-block list, uncapped."""
    client = _ListCommandClient(total=117)
    printed = _run_blocks_list(client, monkeypatch)

    assert client.calls == [{"recursive": False, "limit": None}], (
        "default must fetch with limit=None (full pagination), not a 100 cap"
    )
    assert len(printed) == 1
    assert len(printed[0]) == 117, "all 117 blocks must reach output, not 100"


def test_blocks_list_explicit_limit_caps_output(monkeypatch):
    """An explicit --limit caps both the fetch and the printed result."""
    client = _ListCommandClient(total=117)
    printed = _run_blocks_list(client, monkeypatch, limit=50)

    assert client.calls == [{"recursive": False, "limit": 50}]
    assert len(printed[0]) == 50


def test_blocks_list_recursive_fetches_all_top_level(monkeypatch):
    """--recursive must fetch every top-level block (limit=None), never capped
    at 100 even though --limit defaults to None now."""
    client = _ListCommandClient(total=117)
    printed = _run_blocks_list(client, monkeypatch, recursive=True)

    assert client.calls == [{"recursive": True, "limit": None}]
    assert len(printed[0]) == 117


# ---------------------------------------------------------------------------
# Command-level: `pages blocks append --after` count + no tail loss
# ---------------------------------------------------------------------------

def _make_request_recording_appends(recorded, tail_size):
    """Build a fake `_make_request` that mimics Notion's PATCH
    /blocks/{id}/children behavior under `after`: it records each append and
    returns the inserted blocks PLUS the entire existing tail re-listed (which
    is what makes len(results) overcount). Every block gets a fresh id so the
    real chunked uploader's id-extraction logic runs unchanged."""
    counter = {"n": 0}

    def fake_make_request(method, endpoint, data=None, params=None, retry=True):
        assert method == "PATCH"
        assert endpoint.endswith("/children")
        children = data["children"]
        after = data.get("after")
        recorded.append({"endpoint": endpoint, "n": len(children), "after": after})
        inserted = []
        for _ in children:
            counter["n"] += 1
            inserted.append(_block(f"created-{counter['n']}"))
        tail = [_block(f"tail-{i}") for i in range(tail_size)]
        # Notion returns inserted + the repositioned tail when `after` is set.
        return {"object": "list", "results": inserted + (tail if after else [])}

    return fake_make_request


def _make_request_recording_payloads(recorded):
    """Record append payloads and return created IDs for each sent child."""
    counter = {"n": 0}

    def fake_make_request(method, endpoint, data=None, params=None, retry=True):
        assert method == "PATCH"
        assert endpoint.endswith("/children")
        recorded.append({"endpoint": endpoint, "data": data})
        inserted = []
        for child in data["children"]:
            counter["n"] += 1
            child_type = child["type"]
            inserted.append({
                "id": f"created-{counter['n']}",
                "object": "block",
                "type": child_type,
                child_type: child.get(child_type, {}),
            })
        return {"object": "list", "results": inserted}

    return fake_make_request


def test_blocks_append_after_reports_only_inserted_count(monkeypatch):
    """Inserting 3 flat blocks after a block on a 110-block tail must report 3,
    not len(results) (which would include the 110 re-listed tail blocks).

    The command routes --after through the chunked, nesting-aware uploader, so
    the count comes from blocks actually sent, never from Notion's response
    `results` (which echoes the full repositioned tail under `after`)."""
    recorded = []
    client = NotionClient.__new__(NotionClient)
    client._make_request = _make_request_recording_appends(recorded, tail_size=110)

    printed = []
    successes = []
    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "print_json", printed.append)
    monkeypatch.setattr(page, "print_success", successes.append)

    page.blocks_append(
        block_id="page-x",
        text="A\n\nB\n\nC",
        file=None,
        json_data=None,
        json_file=None,
        after="anchor-block-id",
        is_toggleable=False,
        synced=False,
        synced_from=None,
    )

    # The 3 flat input blocks were sent in a single chunk positioned by `after`.
    assert recorded == [{"endpoint": "/blocks/page-x/children", "n": 3, "after": "anchor-block-id"}]
    # Reported count is the 3 inserted -- NOT 113 (the re-listed tail).
    assert printed[-1] == {"blocks_created": 3, "parent_id": "page-x"}
    assert "Appended 3 block(s)" in successes[-1]


def test_blocks_append_after_chunks_past_100_without_dropping_tail(monkeypatch):
    """An --after insert of >100 blocks must chunk (Notion caps a single append
    at 100) and report every inserted block. The pre-fix raw single-call path
    would have failed the API call at 101 blocks and could drop the tail."""
    recorded = []
    client = NotionClient.__new__(NotionClient)
    client._make_request = _make_request_recording_appends(recorded, tail_size=130)

    printed = []
    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "print_json", printed.append)
    monkeypatch.setattr(page, "print_success", lambda msg: None)

    # 120 flat paragraphs -> must be chunked (>100), positioned after an anchor.
    body = "\n\n".join(f"P{i:03d}" for i in range(120))
    page.blocks_append(
        block_id="page-x",
        text=body,
        file=None,
        json_data=None,
        json_file=None,
        after="anchor-block-id",
        is_toggleable=False,
        synced=False,
        synced_from=None,
    )

    # Every append stayed within Notion's 100-block-per-call limit.
    assert recorded, "expected at least one append call"
    assert all(call["n"] <= 100 for call in recorded), recorded
    # All 120 input blocks were sent across chunks.
    assert sum(call["n"] for call in recorded) == 120
    # Only the FIRST chunk carries `after`; later chunks chain off created ids.
    assert recorded[0]["after"] == "anchor-block-id"
    assert all(call["after"] != "anchor-block-id" for call in recorded[1:])
    # Reported count is the 120 inserted, not inflated by the re-listed tail.
    assert printed[-1] == {"blocks_created": 120, "parent_id": "page-x"}


def test_blocks_append_synced_wraps_content_with_inline_children(monkeypatch):
    """An original synced block must send direct children in the creation payload.

    The Notion API does not allow updating synced block content later, so the
    command cannot create an empty synced_block and append content afterward.
    """
    recorded = []
    client = NotionClient.__new__(NotionClient)
    client._make_request = _make_request_recording_payloads(recorded)

    printed = []
    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "print_json", printed.append)
    monkeypatch.setattr(page, "print_success", lambda msg: None)

    page.blocks_append(
        block_id="page-x",
        text="A\n\nB",
        file=None,
        json_data=None,
        json_file=None,
        after=None,
        is_toggleable=False,
        synced=True,
        synced_from=None,
    )

    assert len(recorded) == 1
    sent_children = recorded[0]["data"]["children"]
    assert len(sent_children) == 1
    synced_block = sent_children[0]
    assert synced_block["type"] == "synced_block"
    assert synced_block["synced_block"]["synced_from"] is None
    assert [child["type"] for child in synced_block["synced_block"]["children"]] == [
        "paragraph",
        "paragraph",
    ]
    assert printed[-1] == {"blocks_created": 1, "parent_id": "page-x"}


def test_blocks_append_synced_from_creates_duplicate_synced_block(monkeypatch):
    recorded = []
    client = NotionClient.__new__(NotionClient)
    client._make_request = _make_request_recording_payloads(recorded)

    printed = []
    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "print_json", printed.append)
    monkeypatch.setattr(page, "print_success", lambda msg: None)

    page.blocks_append(
        block_id="page-x",
        text=None,
        file=None,
        json_data=None,
        json_file=None,
        after="anchor-block-id",
        is_toggleable=False,
        synced=False,
        synced_from="original-synced-block-id",
    )

    sent_children = recorded[0]["data"]["children"]
    assert sent_children == [{
        "object": "block",
        "type": "synced_block",
        "synced_block": {
            "synced_from": {
                "type": "block_id",
                "block_id": "original-synced-block-id",
            },
        },
    }]
    assert recorded[0]["data"]["after"] == "anchor-block-id"
    assert printed[-1] == {"blocks_created": 1, "parent_id": "page-x"}


def test_blocks_append_synced_from_rejects_content_inputs(monkeypatch):
    warnings = []
    monkeypatch.setattr(page, "get_client", lambda: pytest.fail("client should not be created"))
    monkeypatch.setattr(page, "print_warning", warnings.append)

    with pytest.raises(typer.Exit):
        page.blocks_append(
            block_id="page-x",
            text="A",
            file=None,
            json_data=None,
            json_file=None,
            after=None,
            is_toggleable=False,
            synced=False,
            synced_from="original-synced-block-id",
        )

    assert warnings == ["--synced-from cannot be combined with --synced or content inputs"]


def test_blocks_append_synced_requires_one_content_input(monkeypatch):
    warnings = []
    monkeypatch.setattr(page, "get_client", lambda: pytest.fail("client should not be created"))
    monkeypatch.setattr(page, "print_warning", warnings.append)

    with pytest.raises(typer.Exit):
        page.blocks_append(
            block_id="page-x",
            text=None,
            file=None,
            json_data=None,
            json_file=None,
            after=None,
            is_toggleable=False,
            synced=True,
            synced_from=None,
        )

    assert warnings == ["--synced requires exactly one content input: --text, --file, --json, or --json-file"]
