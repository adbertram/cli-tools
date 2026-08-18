"""Tests for `notion comments create --mention` and the `notion users` group.

A Notion mention is its own rich_text object. A literal "@Name" string in the
comment body renders as plain text and notifies nobody, so every path that could
degrade a mention into text has to fail loudly instead:

  * an email that matches no user
  * an email that matches more than one user
  * a resolved user of type ``bot`` (Notion rejects the whole request)
  * a value that is neither a UUID nor an email

These tests also pin the mention placement contract (mentions lead the rich_text
array, each followed by a single space, then the body) and the full cursor walk
of ``GET /v1/users``, which has no server-side name/email filter.
"""
import pytest
import typer

from notion_cli.client import ClientError, NotFoundError, NotionClient
from notion_cli.commands import comments as comments_cmd
from notion_cli.commands import users as users_cmd
from notion_cli import mentions as mentions_mod


ADAM_ID = "3b7c12c5-a309-4dbc-aa45-c80dc25075bc"
MANDY_ID = "fe60dca0-d16a-42d0-a41d-c3491dc972e6"
BOT_ID = "817db75f-835b-4389-9509-da60bb309e65"


def person(user_id, name, email):
    return {
        "object": "user",
        "id": user_id,
        "name": name,
        "type": "person",
        "avatar_url": None,
        "person": {"email": email, "email_verified": True},
    }


def bot(user_id, name):
    return {
        "object": "user",
        "id": user_id,
        "name": name,
        "type": "bot",
        "avatar_url": None,
        "bot": {},
    }


WORKSPACE_USERS = [
    person(ADAM_ID, "Adam Bertram", "adbertram@gmail.com"),
    person(MANDY_ID, "Mandy Mowers", "mandymowers@gmail.com"),
    bot(BOT_ID, "Claude Code"),
]


class FakeUserClient:
    """Client stub exposing only the two user reads mention resolution uses."""

    def __init__(self, users=None):
        self.users = list(WORKSPACE_USERS if users is None else users)
        self.list_calls = 0
        self.get_calls = []

    def list_users_all(self, limit=None):
        self.list_calls += 1
        return self.users if limit is None else self.users[:limit]

    def get_user(self, user_id):
        self.get_calls.append(user_id)
        for user in self.users:
            if user["id"] == user_id:
                return user
        raise NotFoundError(f"Could not find user with ID: {user_id}")


class FakeMentionCommentClient(FakeUserClient):
    """Adds comment creation that echoes the submitted rich_text like Notion."""

    def __init__(self, users=None):
        super().__init__(users)
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
        return {
            "id": "comment-1",
            "rich_text": [_echo_part(part, self.users) for part in rich_text],
            "parent": {"type": "page_id", "page_id": page_id or "page-1"},
            "discussion_id": discussion_id or "discussion-1",
            "created_time": "2026-08-18T00:00:00.000Z",
            "created_by": {"id": BOT_ID},
        }


def _echo_part(part, users):
    """Return the part with the plain_text Notion would add on the way back."""
    if part["type"] == "mention":
        user_id = part["mention"]["user"]["id"]
        name = next((u["name"] for u in users if u["id"] == user_id), "Unknown")
        return {
            "type": "mention",
            "mention": {"type": "user", "user": {"object": "user", "id": user_id}},
            "plain_text": f"@{name}",
        }
    return {
        "type": "text",
        "text": part["text"],
        "plain_text": part["text"]["content"],
    }


# --- Resolution -------------------------------------------------------------


def test_email_resolves_to_user_id():
    client = FakeUserClient()

    assert mentions_mod.resolve_mention_user_id(client, "mandymowers@gmail.com") == MANDY_ID
    assert client.list_calls == 1
    assert client.get_calls == []


def test_email_match_is_case_insensitive():
    client = FakeUserClient()

    assert mentions_mod.resolve_mention_user_id(client, "MandyMowers@Gmail.com") == MANDY_ID


def test_uuid_passes_through_without_listing_users():
    client = FakeUserClient()

    assert mentions_mod.resolve_mention_user_id(client, ADAM_ID) == ADAM_ID
    assert client.get_calls == [ADAM_ID]
    assert client.list_calls == 0


def test_undashed_uuid_passes_through():
    client = FakeUserClient()
    undashed = ADAM_ID.replace("-", "")

    # The user read is what canonicalizes the ID; the returned ID is dashed.
    client.users = [dict(u, id=undashed) if u["id"] == ADAM_ID else u for u in client.users]

    assert mentions_mod.resolve_mention_user_id(client, undashed) == undashed
    assert client.get_calls == [undashed]
    assert client.list_calls == 0


def test_unknown_email_is_an_error_naming_the_email():
    client = FakeUserClient()

    with pytest.raises(ClientError) as exc:
        mentions_mod.resolve_mention_user_id(client, "mandy.mowers@progress.com")

    assert "mandy.mowers@progress.com" in str(exc.value)
    assert "matches no user" in str(exc.value)


def test_ambiguous_email_is_an_error_listing_every_match():
    duplicate_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    client = FakeUserClient(
        WORKSPACE_USERS + [person(duplicate_id, "Mandy M", "mandymowers@gmail.com")]
    )

    with pytest.raises(ClientError) as exc:
        mentions_mod.resolve_mention_user_id(client, "mandymowers@gmail.com")

    message = str(exc.value)
    assert "matches 2 users" in message
    assert MANDY_ID in message
    assert duplicate_id in message


def test_bot_user_is_rejected_before_any_comment_call():
    client = FakeUserClient()

    with pytest.raises(ClientError) as exc:
        mentions_mod.resolve_mention_user_id(client, BOT_ID)

    message = str(exc.value)
    assert "Only person users can be mentioned" in message
    assert "bot" in message


def test_value_that_is_neither_uuid_nor_email_is_an_error():
    client = FakeUserClient()

    with pytest.raises(ClientError) as exc:
        mentions_mod.resolve_mention_user_id(client, "Mandy Mowers")

    assert "neither a Notion user UUID nor an email address" in str(exc.value)
    assert client.list_calls == 0
    assert client.get_calls == []


def test_missing_uuid_is_an_error_naming_the_id():
    client = FakeUserClient()
    missing = "00000000-0000-0000-0000-000000000000"

    with pytest.raises(ClientError) as exc:
        mentions_mod.resolve_mention_user_id(client, missing)

    assert missing in str(exc.value)
    assert "does not exist" in str(exc.value)


def test_resolve_preserves_order_of_multiple_mentions():
    client = FakeUserClient()

    resolved = mentions_mod.resolve_mention_user_ids(
        client, ["mandymowers@gmail.com", ADAM_ID]
    )

    assert resolved == [MANDY_ID, ADAM_ID]


# --- rich_text placement ----------------------------------------------------


def test_mentions_lead_rich_text_each_followed_by_one_space():
    rich_text = comments_cmd.build_comment_rich_text(
        "please review", mention_user_ids=[MANDY_ID, ADAM_ID]
    )

    assert rich_text[0] == {
        "type": "mention",
        "mention": {"type": "user", "user": {"id": MANDY_ID, "object": "user"}},
    }
    assert rich_text[1] == {"type": "text", "text": {"content": " "}}
    assert rich_text[2] == {
        "type": "mention",
        "mention": {"type": "user", "user": {"id": ADAM_ID, "object": "user"}},
    }
    assert rich_text[3] == {"type": "text", "text": {"content": " "}}
    assert rich_text[4] == {"type": "text", "text": {"content": "please review"}}
    assert len(rich_text) == 5


def test_no_mention_rich_text_is_unchanged():
    assert comments_cmd.build_comment_rich_text("plain body") == [
        {"type": "text", "text": {"content": "plain body"}}
    ]


def test_comment_create_sends_mention_objects_and_reports_them(monkeypatch):
    client = FakeMentionCommentClient()
    printed_json = []

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)
    monkeypatch.setattr(comments_cmd, "print_json", printed_json.append)

    comments_cmd.comment_create(
        text="please review",
        text_file=None,
        page_id="page-1",
        block_id=None,
        discussion_id=None,
        mention=["mandymowers@gmail.com", ADAM_ID],
        table=False,
    )

    sent = client.calls[0]["rich_text"]
    assert [p["type"] for p in sent] == ["mention", "text", "mention", "text", "text"]
    assert sent[0]["mention"]["user"]["id"] == MANDY_ID
    assert sent[2]["mention"]["user"]["id"] == ADAM_ID
    assert printed_json[0]["mentions"] == [MANDY_ID, ADAM_ID]
    assert printed_json[0]["text"] == "@Mandy Mowers @Adam Bertram please review"


def test_comment_create_aborts_without_posting_when_email_is_unknown(monkeypatch):
    client = FakeMentionCommentClient()

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)

    with pytest.raises(ClientError):
        comments_cmd.comment_create.__wrapped__(
            text="must not post",
            text_file=None,
            page_id="page-1",
            block_id=None,
            discussion_id=None,
            mention=["nobody@example.com"],
            table=False,
        )

    assert client.calls == []


def test_comment_create_aborts_without_posting_for_a_bot_mention(monkeypatch):
    client = FakeMentionCommentClient()

    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)

    with pytest.raises(ClientError):
        comments_cmd.comment_create.__wrapped__(
            text="must not post",
            text_file=None,
            page_id="page-1",
            block_id=None,
            discussion_id=None,
            mention=[BOT_ID],
            table=False,
        )

    assert client.calls == []


def test_comment_create_fails_when_returned_mentions_do_not_match(monkeypatch, capsys):
    class DroppingMentionClient(FakeMentionCommentClient):
        def create_comment(self, rich_text, page_id=None, block_id=None, discussion_id=None):
            created = super().create_comment(rich_text, page_id, block_id, discussion_id)
            created["rich_text"] = [
                part for part in created["rich_text"] if part["type"] != "mention"
            ]
            return created

    client = DroppingMentionClient()
    monkeypatch.setattr(comments_cmd, "get_client", lambda: client)

    with pytest.raises(typer.Exit):
        comments_cmd.comment_create(
            text="please review",
            text_file=None,
            page_id="page-1",
            block_id=None,
            discussion_id=None,
            mention=[ADAM_ID],
            table=False,
        )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "user mentions are []" in captured.err
    assert "would not notify the intended user" in captured.err


# --- users list pagination --------------------------------------------------


class FakePaginatedUsersClient(NotionClient):
    """NotionClient with only the HTTP layer replaced."""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def _make_request(self, method, endpoint, data=None, params=None, retry=True):
        self.requests.append((method, endpoint, dict(params or {})))
        cursor = (params or {}).get("start_cursor")
        for page in self.pages:
            if page["cursor"] == cursor:
                return page["response"]
        raise AssertionError(f"unexpected cursor {cursor!r}")


def _users_page(count, offset, *, cursor, next_cursor):
    return {
        "cursor": cursor,
        "response": {
            "object": "list",
            "results": [
                person(f"user-{offset + i}", f"User {offset + i}", f"u{offset + i}@x.com")
                for i in range(count)
            ],
            "has_more": next_cursor is not None,
            "next_cursor": next_cursor,
        },
    }


def test_list_users_all_walks_every_cursor_page():
    client = FakePaginatedUsersClient(
        [
            _users_page(100, 0, cursor=None, next_cursor="cursor-1"),
            _users_page(100, 100, cursor="cursor-1", next_cursor="cursor-2"),
            _users_page(37, 200, cursor="cursor-2", next_cursor=None),
        ]
    )

    users = client.list_users_all()

    assert len(users) == 237
    assert users[0]["id"] == "user-0"
    assert users[-1]["id"] == "user-236"
    assert [req[2].get("start_cursor") for req in client.requests] == [
        None,
        "cursor-1",
        "cursor-2",
    ]
    assert all(req[1] == "/users" for req in client.requests)


def test_list_users_all_stops_at_an_explicit_limit():
    client = FakePaginatedUsersClient(
        [
            _users_page(100, 0, cursor=None, next_cursor="cursor-1"),
            _users_page(100, 100, cursor="cursor-1", next_cursor=None),
        ]
    )

    users = client.list_users_all(limit=100)

    assert len(users) == 100
    assert len(client.requests) == 1


def test_list_users_all_fails_when_has_more_has_no_cursor():
    client = FakePaginatedUsersClient(
        [
            {
                "cursor": None,
                "response": {"results": [], "has_more": True, "next_cursor": None},
            }
        ]
    )

    with pytest.raises(ClientError) as exc:
        client.list_users_all()

    assert "has_more without a next_cursor" in str(exc.value)


def test_users_list_command_returns_every_page(monkeypatch):
    client = FakePaginatedUsersClient(
        [
            _users_page(100, 0, cursor=None, next_cursor="cursor-1"),
            _users_page(5, 100, cursor="cursor-1", next_cursor=None),
        ]
    )
    printed_json = []

    monkeypatch.setattr(users_cmd, "get_client", lambda: client)
    monkeypatch.setattr(users_cmd, "print_json", printed_json.append)

    users_cmd.users_list(table=False, limit=None, filter=None, properties=None)

    assert len(printed_json[0]) == 105
    assert printed_json[0][0]["email"] == "u0@x.com"


def test_users_list_filters_on_nested_person_email(monkeypatch):
    class FakeListClient:
        def list_users_all(self, limit=None):
            return WORKSPACE_USERS

    printed_json = []
    monkeypatch.setattr(users_cmd, "get_client", lambda: FakeListClient())
    monkeypatch.setattr(users_cmd, "print_json", printed_json.append)

    users_cmd.users_list(
        table=False,
        limit=None,
        filter=["person.email:eq:mandymowers@gmail.com"],
        properties=None,
    )

    assert [u["id"] for u in printed_json[0]] == [MANDY_ID]
