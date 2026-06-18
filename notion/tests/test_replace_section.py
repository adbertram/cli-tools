import copy

import pytest

from notion_cli.client import NotionClient
from notion_cli.commands import page


def heading(block_id, text, has_children=False):
    return {
        "id": block_id,
        "type": "heading_2",
        "has_children": has_children,
        "heading_2": {
            "rich_text": [{"plain_text": text}],
        },
    }


def paragraph(block_id, text):
    return {
        "id": block_id,
        "type": "paragraph",
        "has_children": False,
        "paragraph": {
            "rich_text": [{"plain_text": text}],
        },
    }


class FakeClient:
    def __init__(self):
        self.top_level_blocks = [
            heading("first-heading", "First"),
            paragraph("first-body", "old"),
            heading("second-heading", "Second", has_children=True),
            paragraph("after-second", "keep"),
        ]
        self.second_heading_children = [
            paragraph("second-child", "nested"),
        ]
        self.deleted = []
        self.uploads = []
        self.children_calls = []

    def get_block_children_all(self, block_id, recursive=True):
        self.children_calls.append((block_id, recursive))
        if block_id == "parent-block" and recursive is False:
            return copy.deepcopy(self.top_level_blocks)
        if block_id == "second-heading" and recursive is True:
            return copy.deepcopy(self.second_heading_children)
        raise AssertionError(f"Unexpected children call: {block_id}, recursive={recursive}")

    def _clean_block_for_creation(self, block):
        cleaned = {
            "type": block["type"],
            block["type"]: copy.deepcopy(block[block["type"]]),
        }
        if "children" in block:
            cleaned["children"] = copy.deepcopy(block["children"])
        return cleaned

    def delete_block(self, block_id):
        self.deleted.append(block_id)

    def delete_block_if_present(self, block_id):
        # Mirror the real client: idempotent delete delegates to delete_block.
        # OrderRecordingClient overrides delete_block, so its event recording
        # still fires through this path.
        self.delete_block(block_id)
        return True

    def _upload_blocks_with_nesting(self, parent_id, blocks, progress_callback=None, after=None):
        self.uploads.append(
            {
                "parent_id": parent_id,
                "blocks": copy.deepcopy(blocks),
                "after": after,
            }
        )
        return len(blocks), [f"new-{len(self.uploads)}-{i}" for i, _block in enumerate(blocks)]

    def clear_page_content(self, page_id):
        raise AssertionError("replace-section must not call page-only clear_page_content")


def test_replace_section_from_first_child_keeps_following_blocks_in_place(monkeypatch):
    client = FakeClient()
    printed_json = []
    replacement_blocks = [heading("replacement-heading", "First"), paragraph("replacement-body", "new")]

    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "text_to_blocks", lambda content, image_uploads=None: copy.deepcopy(replacement_blocks))
    monkeypatch.setattr(page, "print_success", lambda message: None)
    monkeypatch.setattr(page, "print_json", printed_json.append)

    page.content_replace_section(
        "parent-block",
        heading="## First",
        text="## First\n\nnew",
        file=None,
        dry_run=False,
    )

    assert client.children_calls == [
        ("parent-block", False),
    ]
    assert sorted(client.deleted) == [
        "first-body",
        "first-heading",
    ]
    assert len(client.uploads) == 1
    assert client.uploads[0]["parent_id"] == "parent-block"
    assert client.uploads[0]["after"] == "first-body"
    assert client.uploads[0]["blocks"] == replacement_blocks
    assert printed_json == [
        {
            "page_id": "parent-block",
            "section_heading": "## First",
            "section_blocks_replaced": 2,
            "blocks_deleted": 2,
            "blocks_created": 2,
            "first_child_rewrite": False,
            "following_blocks_recreated": 0,
        }
    ]


def test_replace_section_dry_run_reports_surgical_first_child_replace(monkeypatch):
    client = FakeClient()
    printed_json = []

    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "text_to_blocks", lambda content, image_uploads=None: [heading("replacement-heading", "First")])
    monkeypatch.setattr(page, "print_json", printed_json.append)

    page.content_replace_section(
        "parent-block",
        heading="## First",
        text="## First",
        file=None,
        dry_run=True,
    )

    assert client.deleted == []
    assert client.uploads == []
    assert printed_json == [
        {
            "page_id": "parent-block",
            "section_heading": "## First",
            "section_blocks_to_replace": 2,
            "blocks_to_delete": 2,
            "blocks_to_insert": 1,
            "first_child_rewrite": False,
            "following_blocks_to_recreate": 0,
            "after_block_id": "first-body",
            "dry_run": True,
        }
    ]


def test_replace_section_uploads_local_images_from_file(monkeypatch, tmp_path):
    client = FakeClient()
    section_file = tmp_path / "section.md"
    section_file.write_text("## First\n\n![Logo](logo.png)\n", encoding="utf-8")
    printed_json = []
    uploaded_images = {"logo.png": "file-upload-id"}
    captured_uploads = []

    def fake_text_to_blocks(content, image_uploads=None):
        captured_uploads.append(image_uploads)
        return [heading("replacement-heading", "First")]

    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "text_to_blocks", fake_text_to_blocks)
    monkeypatch.setattr(page, "print_success", lambda message: None)
    monkeypatch.setattr(page, "print_json", printed_json.append)

    from notion_cli.commands import database

    monkeypatch.setattr(database, "_process_markdown_images", lambda content, file, client: uploaded_images)

    page.content_replace_section(
        "parent-block",
        heading="## First",
        text=None,
        file=str(section_file),
        dry_run=False,
    )

    assert captured_uploads == [uploaded_images]
    assert client.uploads[0]["blocks"] == [heading("replacement-heading", "First")]


def test_replace_section_dry_run_does_not_upload_local_images(monkeypatch, tmp_path):
    client = FakeClient()
    section_file = tmp_path / "section.md"
    section_file.write_text("## First\n\n![Logo](logo.png)\n", encoding="utf-8")
    processed_images = []

    def fake_text_to_blocks(content, image_uploads=None):
        assert image_uploads == {}
        return [heading("replacement-heading", "First")]

    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "text_to_blocks", fake_text_to_blocks)
    monkeypatch.setattr(page, "print_json", lambda data: None)

    from notion_cli.commands import database

    monkeypatch.setattr(
        database,
        "_process_markdown_images",
        lambda content, file, client: processed_images.append(file),
    )

    page.content_replace_section(
        "parent-block",
        heading="## First",
        text=None,
        file=str(section_file),
        dry_run=True,
    )

    assert processed_images == []
    assert client.uploads == []


class OrderRecordingClient(FakeClient):
    """FakeClient that records the relative order of insert vs. delete calls.

    replace-section is not atomic (it inserts the new section, then deletes the
    old one). These tests prove the full new payload is transformed + validated
    BEFORE any mutating call, so a pre-checkable failure can never leave the
    section half-written with a duplicate heading.
    """

    def __init__(self):
        super().__init__()
        self.events = []

    def delete_block(self, block_id):
        self.events.append(("delete", block_id))
        super().delete_block(block_id)

    def _upload_blocks_with_nesting(self, parent_id, blocks, progress_callback=None, after=None):
        self.events.append(("insert", parent_id))
        return super()._upload_blocks_with_nesting(
            parent_id, blocks, progress_callback=progress_callback, after=after
        )


def test_replace_section_does_not_mutate_when_block_cannot_be_made_valid(monkeypatch):
    """An unfixable oversize block aborts BEFORE any insert or delete.

    enforce_block_limits handles real markdown, so -- mirroring test_block_limits
    -- we force the post-transform validator to report an unfixable block and
    assert the section is left completely untouched (no insert, no delete).
    """
    client = OrderRecordingClient()
    warnings = []

    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(
        page, "text_to_blocks", lambda content, image_uploads=None: [heading("h", "First")]
    )
    monkeypatch.setattr(page, "print_warning", warnings.append)
    # Force the pre-mutation validator to report an unfixable oversize block.
    monkeypatch.setattr(
        page,
        "_find_oversize_rich_text",
        lambda blocks: "blocks[0].paragraph.rich_text[0].text.content is 9999 chars (limit 2000)",
    )

    with pytest.raises(page.typer.Exit) as exc:
        page.content_replace_section(
            "parent-block",
            heading="## First",
            text="## First\n\nnew",
            file=None,
            dry_run=False,
        )

    assert exc.value.exit_code == 1
    # CRITICAL: neither the delete nor the insert ran -- the section is intact.
    assert client.events == []
    assert client.deleted == []
    assert client.uploads == []
    # The page was never even fetched for mutation -- validation gated everything.
    assert client.children_calls == []
    assert any("left untouched" in w for w in warnings)


def test_replace_section_normalizes_unsupported_code_language_before_any_delete(monkeypatch):
    """A ```kql block in the new content is normalized to "plain text".

    This exercises the REAL transform path (text_to_blocks + enforce_block_limits)
    -- text_to_blocks is not stubbed -- so it proves BUG 1 (unsupported language)
    and BUG 2 (atomic validation) together: the payload Notion receives is valid,
    and the new payload is fully normalized before the first delete runs.
    """
    client = OrderRecordingClient()
    printed_json = []

    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(page, "print_success", lambda message: None)
    monkeypatch.setattr(page, "print_json", printed_json.append)

    page.content_replace_section(
        "parent-block",
        heading="## First",
        text="## First\n\n```kql\nStormEvents | take 10\n```",
        file=None,
        dry_run=False,
    )

    # The inserted payload carries a normalized, Notion-accepted code language.
    assert len(client.uploads) == 1
    code_blocks = [b for b in client.uploads[0]["blocks"] if b.get("type") == "code"]
    assert code_blocks, "expected a code block in the replacement payload"
    assert code_blocks[0]["code"]["language"] == "plain text"

    # Insert ran before any delete (documented order), and both ran exactly once
    # set -- proving the section was replaced cleanly with no leftover duplicate.
    insert_idx = client.events.index(("insert", "parent-block"))
    delete_indexes = [i for i, e in enumerate(client.events) if e[0] == "delete"]
    assert delete_indexes, "old section blocks should have been deleted"
    assert insert_idx < min(delete_indexes)
    assert sorted(client.deleted) == ["first-body", "first-heading"]


class _FakeResponse:
    """Minimal stand-in for requests.Response for _make_request unit tests."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = "x"  # non-empty so _make_request parses json()
        self.headers = {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


def _make_client():
    client = NotionClient.__new__(NotionClient)
    client.base_url = "https://api.notion.com/v1"
    client.headers = {}
    client.max_retries = 0  # no retry loop for these unit tests
    client.base_delay = 0
    client.max_delay = 0
    client.jitter = 0
    return client


def test_make_request_raises_block_already_archived_on_400(monkeypatch):
    """The exact 400 'Can't edit block that is archived' maps to the subclass."""
    from notion_cli import client as client_mod

    client = _make_client()
    response = _FakeResponse(
        400,
        {
            "object": "error",
            "status": 400,
            "code": "validation_error",
            "message": "Can't edit block that is archived. You must unarchive the block before editing.",
        },
    )
    monkeypatch.setattr(client_mod.requests, "request", lambda **kwargs: response)

    with pytest.raises(client_mod.BlockAlreadyArchivedError):
        client._make_request("DELETE", "/blocks/abc")


def test_make_request_other_400_stays_generic_client_error(monkeypatch):
    """A different 400 is NOT swallowed as already-archived (fail-fast preserved)."""
    from notion_cli import client as client_mod

    client = _make_client()
    response = _FakeResponse(
        400,
        {"object": "error", "status": 400, "code": "validation_error", "message": "body failed validation"},
    )
    monkeypatch.setattr(client_mod.requests, "request", lambda **kwargs: response)

    with pytest.raises(client_mod.ClientError) as exc:
        client._make_request("DELETE", "/blocks/abc")
    assert not isinstance(exc.value, client_mod.BlockAlreadyArchivedError)


def test_delete_block_if_present_treats_already_archived_as_gone(monkeypatch):
    """delete_block_if_present returns False (already gone) for the archived 400,
    True when it actually archived, and re-raises any other error."""
    from notion_cli import client as client_mod

    client = _make_client()

    calls = {"n": 0}

    def fake_delete(block_id):
        calls["n"] += 1
        if block_id == "already-archived":
            raise client_mod.BlockAlreadyArchivedError("API request failed: 400 - ... block that is archived ...")
        if block_id == "boom":
            raise client_mod.ClientError("API request failed: 409 - conflict")
        return {"id": block_id}

    monkeypatch.setattr(client, "delete_block", fake_delete)

    assert client.delete_block_if_present("fresh") is True
    assert client.delete_block_if_present("already-archived") is False
    with pytest.raises(client_mod.ClientError):
        client.delete_block_if_present("boom")
    assert calls["n"] == 3


class ArchivedCascadeClient(FakeClient):
    """replace-section client where deleting one section block reports it was
    already archived (the auto-archive cascade). The command must still finish
    cleanly (no raise) instead of aborting after the content was swapped."""

    def __init__(self, already_archived_id):
        super().__init__()
        self._already_archived_id = already_archived_id
        self.attempted_deletes = []

    def delete_block_if_present(self, block_id):
        self.attempted_deletes.append(block_id)
        if block_id == self._already_archived_id:
            return False  # already gone (cascade) — benign
        self.delete_block(block_id)
        return True


def test_replace_section_succeeds_when_a_block_is_already_archived(monkeypatch):
    """The reported failure: a delete in the cleanup step finds an already
    archived block. With the idempotent delete the command completes (no raise)
    and still reports the swap, rather than exiting non-zero after a correct
    replacement."""
    client = ArchivedCascadeClient(already_archived_id="first-body")
    printed_json = []

    monkeypatch.setattr(page, "get_client", lambda: client)
    monkeypatch.setattr(
        page, "text_to_blocks", lambda content, image_uploads=None: [heading("replacement-heading", "First")]
    )
    monkeypatch.setattr(page, "print_success", lambda message: None)
    monkeypatch.setattr(page, "print_json", printed_json.append)

    # Must NOT raise even though one section block was already archived.
    page.content_replace_section(
        "parent-block",
        heading="## First",
        text="## First\n\nnew",
        file=None,
        dry_run=False,
    )

    # Both section blocks were attempted; the already-archived one was tolerated.
    assert sorted(client.attempted_deletes) == ["first-body", "first-heading"]
    assert client.deleted == ["first-heading"]  # only the live one truly deleted
    assert printed_json and printed_json[0]["blocks_deleted"] == 2


def test_clean_block_for_creation_strips_type_icon_from_non_tab_blocks():
    client = NotionClient.__new__(NotionClient)
    block = {
        "id": "paragraph-with-tab-icon",
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": "Body"}}],
            "icon": {"type": "emoji", "emoji": "x"},
        },
    }

    cleaned = client._clean_block_for_creation(block)

    assert "id" not in cleaned
    assert "object" not in cleaned
    assert cleaned == {
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": "Body"}}],
        },
    }
