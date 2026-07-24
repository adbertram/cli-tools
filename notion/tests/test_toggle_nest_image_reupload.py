"""Regression tests for `notion pages blocks update BLOCK_ID --toggleable`.

Bug: converting a heading to a toggle heading re-parents the heading's section
siblings as children of the toggle. That re-parent path ran the section blocks
straight through `_clean_blocks_recursive`, which rewrites a Notion-hosted
`image.file` block to `image.external` using the signed, EXPIRING S3 URL. Notion
rejects that on create (400 `image.file_upload should be defined` at depth-2) or
silently empties the image to `![]()` (depth-1) — destroying the image.

Fix: `_nest_section_under_heading` now calls `client._reupload_file_blocks`
AFTER hydrating children and BEFORE cleaning, mirroring the proven
`pages duplicate` path. Hosted files are downloaded and re-uploaded via the File
Upload API and recreated as native `file_upload` images inside the toggle.

Fail behavior: `_reupload_file_blocks` fails loud (raises `ClientError`) when a
re-upload fails instead of degrading to a broken expiring external URL, and the
original section blocks are left untouched (never deleted) on failure.
"""

import copy

import pytest

from notion_cli.client import ClientError, NotionClient
from notion_cli.commands.page import _nest_section_under_heading


HEADING_ID = "heading-1"
PAGE_ID = "page-1"
HOSTED_URL = (
    "https://prod-files-secure.s3.us-west-2.amazonaws.com/"
    "abc/def/local.png?X-Amz-Signature=expiring"
)


# ---------------------------------------------------------------------------
# Block builders (raw API shape)
# ---------------------------------------------------------------------------

def raw_heading():
    return {
        "id": HEADING_ID,
        "object": "block",
        "type": "heading_2",
        "has_children": False,
        "parent": {"type": "page_id", "page_id": PAGE_ID},
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "Section"}, "plain_text": "Section"}],
            "is_toggleable": True,
        },
    }


def raw_hosted_image(block_id="img-1"):
    return {
        "id": block_id,
        "object": "block",
        "type": "image",
        "has_children": False,
        "image": {
            "type": "file",
            "file": {"url": HOSTED_URL},
            "caption": [],
        },
    }


def raw_toggle_with_image(block_id="toggle-1"):
    return {
        "id": block_id,
        "object": "block",
        "type": "toggle",
        "has_children": True,
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "Details"}, "plain_text": "Details"}]
        },
    }


# ---------------------------------------------------------------------------
# Fake client: real re-upload/clean/nesting logic, stubbed network boundaries.
# ---------------------------------------------------------------------------

class FakeClient(NotionClient):
    def __init__(self, siblings, flat_children=None, upload_ok=True):
        # Bypass NotionClient.__init__ (no config/auth needed for these tests).
        self._siblings = siblings
        self._flat_children = flat_children or {}
        self._upload_ok = upload_ok
        self.uploaded_payload = None
        self.deleted_ids = []
        self.upload_file_calls = 0

    # --- network boundaries -------------------------------------------------
    def get_block(self, block_id):
        return raw_heading()

    def get_block_children_all(self, parent_id, recursive=False):
        return copy.deepcopy(self._siblings)

    def _fetch_block_children_flat(self, block_id):
        return copy.deepcopy(self._flat_children.get(block_id, []))

    def upload_file(self, path):
        self.upload_file_calls += 1
        if not self._upload_ok:
            raise ClientError("File upload failed: 400 - simulated")
        return "file-upload-abc"

    def _upload_blocks_with_nesting(self, parent_id, blocks, progress_callback=None, after=None, _depth=1):
        self.uploaded_payload = copy.deepcopy(blocks)
        return (len(blocks), [f"srv-{i}" for i in range(len(blocks))])

    def delete_block_if_present(self, block_id):
        self.deleted_ids.append(block_id)


@pytest.fixture(autouse=True)
def _mock_download(monkeypatch):
    """Stub requests.get so the hosted-file download returns a tiny PNG."""

    class FakeResp:
        content = b"\x89PNG\r\n\x1a\n"
        headers = {"content-type": "image/png"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr("requests.get", lambda url, timeout=30: FakeResp())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_nest_reuploads_depth1_hosted_image_before_cleaning():
    """A hosted image sibling is recreated as file_upload, not expiring external."""
    siblings = [raw_heading(), raw_hosted_image()]
    client = FakeClient(siblings)

    created, deleted = _nest_section_under_heading(client, HEADING_ID)

    assert client.upload_file_calls == 1
    assert client.uploaded_payload is not None
    image = client.uploaded_payload[0]
    assert image["type"] == "image"
    # Re-uploaded to a native file_upload reference — NOT a broken external URL.
    assert image["image"]["type"] == "file_upload"
    assert image["image"]["file_upload"] == {"id": "file-upload-abc"}
    assert "external" not in image["image"]
    assert created == 1
    assert deleted == 1
    assert client.deleted_ids == ["img-1"]


def test_nest_reuploads_depth2_nested_hosted_image():
    """A hosted image nested inside a section container survives re-parenting."""
    toggle = raw_toggle_with_image()
    siblings = [raw_heading(), toggle]
    flat = {toggle["id"]: [raw_hosted_image("img-nested")]}
    client = FakeClient(siblings, flat_children=flat)

    _nest_section_under_heading(client, HEADING_ID)

    assert client.upload_file_calls == 1
    payload_toggle = client.uploaded_payload[0]
    assert payload_toggle["type"] == "toggle"
    nested_children = payload_toggle["toggle"]["children"]
    nested_image = nested_children[0]
    assert nested_image["type"] == "image"
    assert nested_image["image"]["type"] == "file_upload"
    assert nested_image["image"]["file_upload"] == {"id": "file-upload-abc"}
    assert "external" not in nested_image["image"]


def test_nest_fails_loud_when_reupload_fails_and_keeps_originals():
    """A failed re-upload raises and never deletes the source blocks."""
    siblings = [raw_heading(), raw_hosted_image()]
    client = FakeClient(siblings, upload_ok=False)

    with pytest.raises(ClientError) as exc_info:
        _nest_section_under_heading(client, HEADING_ID)

    assert "re-upload" in str(exc_info.value).lower()
    # Fail-fast: nothing uploaded, nothing deleted — the original image is safe.
    assert client.uploaded_payload is None
    assert client.deleted_ids == []
