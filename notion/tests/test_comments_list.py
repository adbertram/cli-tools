from notion_cli.client import NotionClient
from notion_cli.commands import comments as comments_cmd
from typer.testing import CliRunner


def comment(comment_id, text="Test comment", parent_type="page_id", parent_id="page-1"):
    return {
        "id": comment_id,
        "rich_text": [{"plain_text": text}],
        "parent": {"type": parent_type, parent_type: parent_id},
        "discussion_id": "discussion-1",
        "created_time": "2026-05-01T00:00:00.000Z",
        "created_by": {"id": "user-1"},
    }


class FakeCommentsClient:
    def __init__(self):
        self.calls = []

    def list_comments_all(self, block_id=None, discussion_id=None, limit=None):
        self.calls.append(("list_comments_all", block_id, discussion_id, limit))
        return [comment("comment-1")]

    def list_comments_with_context(self, page_id, **kwargs):
        self.calls.append(("list_comments_with_context", page_id, kwargs))
        return [comment("comment-1")]


def test_comments_list_page_id_uses_direct_comment_lookup_without_context(monkeypatch):
    client = FakeCommentsClient()
    printed_json = []

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)
    monkeypatch.setattr(comments_cmd, "print_json", printed_json.append)

    comments_cmd.comments_list(
        page_id="page-1",
        block_id=None,
        discussion_id=None,
        with_context=False,
        table=False,
        limit=1,
        max_workers=5,
        filter=None,
    )

    assert client.calls == [("list_comments_all", "page-1", None, 1)]
    assert printed_json[0][0]["id"] == "comment-1"
    assert printed_json[0][0]["context"] == ""


def test_comments_list_page_id_with_context_passes_limit(monkeypatch):
    client = FakeCommentsClient()
    printed_json = []

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)
    monkeypatch.setattr(comments_cmd, "print_json", printed_json.append)

    comments_cmd.comments_list(
        page_id="page-1",
        block_id=None,
        discussion_id=None,
        with_context=True,
        table=False,
        limit=2,
        max_workers=25,
        filter=None,
    )

    assert client.calls == [("list_comments_with_context", "page-1", {"max_workers": 25, "limit": 2})]
    assert printed_json[0][0]["id"] == "comment-1"


def test_comments_list_page_id_with_context_passes_max_workers(monkeypatch):
    client = FakeCommentsClient()
    printed_json = []

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)
    monkeypatch.setattr(comments_cmd, "print_json", printed_json.append)

    comments_cmd.comments_list(
        page_id="page-1",
        block_id=None,
        discussion_id=None,
        with_context=True,
        table=False,
        limit=2,
        max_workers=25,
        filter=None,
    )

    assert client.calls == [("list_comments_with_context", "page-1", {"max_workers": 25, "limit": 2})]
    assert printed_json[0][0]["id"] == "comment-1"


def test_comments_list_empty_table_uses_table_output(monkeypatch):
    client = FakeCommentsClient()
    table_calls = []

    def empty_comments(block_id=None, discussion_id=None, limit=None):
        client.calls.append(("list_comments_all", block_id, discussion_id, limit))
        return []

    client.list_comments_all = empty_comments
    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)
    monkeypatch.setattr(comments_cmd, "print_json", lambda payload: (_ for _ in ()).throw(AssertionError(payload)))
    monkeypatch.setattr(comments_cmd, "print_table", lambda rows, columns=None: table_calls.append((rows, columns)))

    comments_cmd.comments_list(
        page_id="page-1",
        block_id=None,
        discussion_id=None,
        with_context=False,
        table=True,
        limit=1,
        max_workers=5,
        filter=None,
    )

    assert table_calls == [
        (
            [],
            ["id", "comment_type", "text", "parent_type", "parent_id", "created_time"],
        )
    ]


class FakePaginatedClient(NotionClient):
    def __init__(self):
        self.calls = []

    def list_comments(
        self,
        block_id=None,
        discussion_id=None,
        page_size=100,
        start_cursor=None,
    ):
        self.calls.append(
            {
                "block_id": block_id,
                "discussion_id": discussion_id,
                "page_size": page_size,
                "start_cursor": start_cursor,
            }
        )
        return {
            "results": [comment("comment-1"), comment("comment-2")],
            "has_more": True,
            "next_cursor": "next-page",
        }


def test_list_comments_all_stops_after_limit():
    client = FakePaginatedClient()

    results = client.list_comments_all(block_id="page-1", limit=1)

    assert [item["id"] for item in results] == ["comment-1"]
    assert client.calls == [
        {
            "block_id": "page-1",
            "discussion_id": None,
            "page_size": 1,
            "start_cursor": None,
        }
    ]


class FakeContextClient(NotionClient):
    def __init__(self):
        self.children_calls = []
        self.comment_calls = []

    def get_block_children_all(self, block_id, recursive=True, max_workers=5):
        self.children_calls.append((block_id, recursive, max_workers))
        return [
            {
                "id": "block-1",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": "Commented block text"}]},
            }
        ]

    def list_comments(self, block_id=None, discussion_id=None, page_size=100, start_cursor=None):
        self.comment_calls.append((block_id, discussion_id, page_size, start_cursor))
        if block_id == "page-1":
            return {
                "results": [comment("comment-1", text="Page comment", parent_type="page_id")],
                "has_more": False,
                "next_cursor": None,
            }
        if block_id == "block-1":
            return {
                "results": [
                    comment("comment-2", text="Inline comment", parent_type="block_id", parent_id="block-1")
                ],
                "has_more": False,
                "next_cursor": None,
            }
        raise AssertionError(f"Unexpected comments lookup for {block_id}")


def test_comments_list_page_id_with_context_defaults_to_fast_worker_count(monkeypatch):
    client = FakeCommentsClient()
    printed_json = []
    runner = CliRunner()

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)
    monkeypatch.setattr(comments_cmd, "print_json", printed_json.append)

    result = runner.invoke(
        comments_cmd.app,
        ["list", "--page-id", "page-1", "--with-context", "--limit", "2"],
    )

    assert result.exit_code == 0
    assert client.calls == [("list_comments_with_context", "page-1", {"max_workers": 25, "limit": 2})]
    assert printed_json[0][0]["id"] == "comment-1"


def test_list_comments_with_context_passes_worker_count_to_block_tree_fetch():
    client = FakeContextClient()

    results = client.list_comments_with_context("page-1", max_workers=25, limit=100)

    assert [item["id"] for item in results] == ["comment-1", "comment-2"]
    assert results[0]["context"] == ""
    assert results[1]["context"] == "Commented block text"
    assert results[1]["context_around"] == "Commented block text"
    assert client.children_calls == [("page-1", True, 25)]


class FakeFailingBlockCommentClient(FakeContextClient):
    def list_comments(self, block_id=None, discussion_id=None, page_size=100, start_cursor=None):
        if block_id == "block-1":
            raise RuntimeError("comment lookup failed")
        return super().list_comments(block_id, discussion_id, page_size, start_cursor)


def test_list_comments_with_context_does_not_suppress_block_comment_errors():
    client = FakeFailingBlockCommentClient()

    try:
        client.list_comments_with_context("page-1", max_workers=25, limit=100)
    except RuntimeError as exc:
        assert str(exc) == "comment lookup failed"
    else:
        raise AssertionError("Expected comment lookup failure to be raised")


def test_block_context_text_extracts_table_row_cells():
    block = {
        "id": "row-1",
        "type": "table_row",
        "table_row": {
            "cells": [
                [{"plain_text": "Step"}],
                [{"plain_text": "What you are doing"}],
                [{"plain_text": "Why it matters"}],
            ]
        },
    }

    assert NotionClient._get_block_context_text(block) == "Step | What you are doing | Why it matters"


def test_comments_list_uses_parent_block_as_selected_block(monkeypatch):
    client = FakeCommentsClient()
    printed_json = []

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)
    monkeypatch.setattr(comments_cmd, "print_json", printed_json.append)

    comments_cmd.comments_list(
        page_id="page-1",
        block_id=None,
        discussion_id=None,
        with_context=True,
        table=False,
        limit=1,
        max_workers=25,
        filter=None,
    )

    assert printed_json[0][0]["selected_block"] == ""
    assert printed_json[0][0]["selected_block_status"] == "not_available"


def test_format_comment_uses_context_as_selected_block():
    formatted = comments_cmd.format_comment_for_display(
        comment(
            "comment-1",
            parent_type="block_id",
            parent_id="block-1",
        ) | {"context": "Parent block text"}
    )

    assert formatted["selected_block"] == "Parent block text"
    assert formatted["selected_block_status"] == "available"
