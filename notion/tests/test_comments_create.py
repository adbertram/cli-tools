from notion_cli.commands import comments as comments_cmd


def comment(comment_id, text="Test comment", parent_type="page_id", parent_id="page-1"):
    return {
        "id": comment_id,
        "rich_text": [{"plain_text": text}],
        "parent": {"type": parent_type, parent_type: parent_id},
        "discussion_id": "discussion-1",
        "created_time": "2026-05-01T00:00:00.000Z",
        "created_by": {"id": "user-1"},
    }


class FakeCreateCommentClient:
    def __init__(self):
        self.calls = []

    def create_comment(self, rich_text, page_id=None, block_id=None, discussion_id=None):
        self.calls.append(
            {
                "rich_text": rich_text,
                "page_id": page_id,
                "block_id": block_id,
                "discussion_id": discussion_id,
            }
        )
        return comment("comment-1", text="".join(part["text"]["content"] for part in rich_text))


def test_build_comment_rich_text_splits_long_text_without_losing_content():
    long_text = ("A" * 1999) + "\n" + ("B" * 1200)

    rich_text = comments_cmd.build_comment_rich_text(long_text)

    assert len(rich_text) == 2
    assert all(part["type"] == "text" for part in rich_text)
    assert all(len(part["text"]["content"]) <= 2000 for part in rich_text)
    assert "".join(part["text"]["content"] for part in rich_text) == long_text


def test_comment_create_sends_chunked_rich_text_for_long_comments(monkeypatch):
    client = FakeCreateCommentClient()
    printed_json = []
    long_text = ("A" * 1999) + "\n" + ("B" * 1200)

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)
    monkeypatch.setattr(comments_cmd, "print_json", printed_json.append)

    comments_cmd.comment_create(
        text=long_text,
        page_id="page-1",
        block_id=None,
        discussion_id=None,
        table=False,
    )

    assert len(client.calls) == 1
    sent_rich_text = client.calls[0]["rich_text"]
    assert client.calls[0]["page_id"] == "page-1"
    assert all(len(part["text"]["content"]) <= 2000 for part in sent_rich_text)
    assert len(sent_rich_text) == 2
    assert "".join(part["text"]["content"] for part in sent_rich_text) == long_text
    assert printed_json[0]["text"] == long_text
