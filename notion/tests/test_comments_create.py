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


class FakeTextDroppingCommentClient(FakeCreateCommentClient):
    def create_comment(self, rich_text, page_id=None, block_id=None, discussion_id=None):
        super().create_comment(rich_text, page_id, block_id, discussion_id)
        return comment(
            "empty-comment-1",
            text="",
            parent_type="block_id",
            parent_id="deleted-block-1",
        )


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
        text_file=None,
        page_id="page-1",
        block_id=None,
        discussion_id=None,
        mention=None,
        table=False,
    )

    assert len(client.calls) == 1
    sent_rich_text = client.calls[0]["rich_text"]
    assert client.calls[0]["page_id"] == "page-1"
    assert all(len(part["text"]["content"]) <= 2000 for part in sent_rich_text)
    assert len(sent_rich_text) == 2
    assert "".join(part["text"]["content"] for part in sent_rich_text) == long_text
    assert printed_json[0]["text"] == long_text


def test_comment_create_reads_text_file_without_shell_interpretation(monkeypatch, tmp_path):
    client = FakeCreateCommentClient()
    printed_json = []
    comment_text = (
        "Processed this correction for target `deploy/instructions/developmental-reviewer.md`, "
        "not `deploy/instructions/security-reviewer-editor.md`.\n"
        "The email includes `ATA-TOPIC-<topic_id>`."
    )
    text_file = tmp_path / "reply.md"
    text_file.write_text(comment_text, encoding="utf-8")

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)
    monkeypatch.setattr(comments_cmd, "print_json", printed_json.append)

    comments_cmd.comment_create(
        text=None,
        text_file=text_file,
        page_id=None,
        block_id=None,
        discussion_id="discussion-1",
        mention=None,
        table=False,
    )

    assert len(client.calls) == 1
    sent_rich_text = client.calls[0]["rich_text"]
    assert client.calls[0]["discussion_id"] == "discussion-1"
    assert "".join(part["text"]["content"] for part in sent_rich_text) == comment_text
    assert printed_json[0]["text"] == comment_text


def test_comment_create_fails_when_api_drops_nonempty_reply_text(monkeypatch, tmp_path, capsys):
    client = FakeTextDroppingCommentClient()
    comment_text = "This reply must never be silently discarded."
    text_file = tmp_path / "reply.md"
    text_file.write_text(comment_text, encoding="utf-8")

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)

    try:
        comments_cmd.comment_create(
            text=None,
            text_file=text_file,
            page_id=None,
            block_id=None,
            discussion_id="orphaned-discussion-1",
            mention=None,
            table=False,
        )
    except Exception as exc:
        assert getattr(exc, "exit_code", None) == 1
    else:
        raise AssertionError("text-dropping response was reported as success")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "empty-comment-1" in captured.err
    assert "did not preserve the submitted text" in captured.err
    assert "submitted 44 characters, returned 0" in captured.err
    assert len(client.calls) == 1
    assert client.calls[0]["discussion_id"] == "orphaned-discussion-1"


def test_comment_create_rejects_unsupported_new_inline_discussion(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(
        comments_cmd,
        "get_client",
        lambda: (_ for _ in ()).throw(AssertionError("API must not be called")),
    )

    result = runner.invoke(
        comments_cmd.app,
        ["create", "Review this text", "--block-id", "block-1"],
    )

    assert result.exit_code == 1
    assert "cannot start an inline discussion" in result.output
    assert "not enumerable by List comments" in result.output
