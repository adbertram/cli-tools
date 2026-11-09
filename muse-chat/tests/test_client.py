from __future__ import annotations

import pytest

from cli_tools_shared.exceptions import ClientError
from muse_chat_cli import client as client_module
from muse_chat_cli.browser import AUTH_STATE_JS
from muse_chat_cli.client import CHAT_SNAPSHOT_JS, MuseChatClient
from muse_chat_cli.parsers import normalize_threads


class FakeComposer:
    def __init__(self):
        self.filled = []
        self.pressed = []

    def fill(self, value):
        self.filled.append(value)

    def press(self, key):
        self.pressed.append(key)


class SequencePage:
    def __init__(self, snapshots, url="https://muse.ai/"):
        self.snapshots = list(snapshots)
        self.url = url
        self.composer = FakeComposer()

    def evaluate(self, script):
        if script == AUTH_STATE_JS:
            return ""
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]

    def wait_for_timeout(self, _milliseconds):
        return None

    def locator(self, _selector):
        return self.composer


def snapshot(messages=None, *, typing=False, working=False, approvals=None):
    return {
        "messages": messages or [],
        "typing": typing,
        "working": working,
        "approvals": approvals or [],
    }


def test_send_ack_normalizes_multiline_message_without_retry():
    page = SequencePage(
        [
            snapshot(),
            snapshot([
                {
                    "role": "user",
                    "text": "first line second line",
                    "dom_index": 2,
                    "message_id": "user-2",
                },
            ]),
        ]
    )
    result = MuseChatClient._send_on_page(
        MuseChatClient.__new__(MuseChatClient),
        page,
        "first line\n  second line",
        monitor=False,
        timeout=10,
    )
    assert result["status"] == "sent"
    assert page.composer.filled == ["first line\n  second line"]
    assert page.composer.pressed == ["Enter"]


def test_monitor_waits_until_streaming_and_stop_control_are_gone():
    page = SequencePage(
        [
            snapshot(
                [
                    {"role": "user", "text": "prompt", "dom_index": 2, "message_id": "user-2"},
                    {"role": "assistant", "text": "partial", "dom_index": 3, "message_id": "assistant-3"},
                ],
                typing=False,
                working=True,
            ),
            snapshot(
                [
                    {"role": "user", "text": "prompt", "dom_index": 2, "message_id": "user-2"},
                    {"role": "assistant", "text": "full response", "dom_index": 3, "message_id": "assistant-3"},
                ],
                typing=False,
                working=False,
            ),
        ],
        url="https://muse.ai/thread/eb431c8c-6348-4ba9-9aed-11908cf2d0ed",
    )
    result = MuseChatClient._monitor_turn(
        page, "eb431c8c-6348-4ba9-9aed-11908cf2d0ed", 2, 10, "user-2"
    )
    assert result["status"] == "completed"
    assert result["response"] == "full response"


def test_monitor_timeout_is_structured_and_never_cancels(monkeypatch):
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(client_module.time, "monotonic", lambda: next(ticks))
    page = SequencePage([
        snapshot([{"role": "user", "text": "prompt", "dom_index": 0, "message_id": "user-0"}])
    ])
    result = MuseChatClient._monitor_turn(page, "main", 0, 1, "user-0")
    assert result == {
        "status": "timeout",
        "chat_id": "main",
        "turn_message_id": "user-0",
        "url": "https://muse.ai/",
        "response": None,
        "timeout_seconds": 1,
        "remote_task_cancelled": False,
    }


def test_monitor_reports_approval_after_correlated_turn():
    page = SequencePage([
        snapshot(
            [{"role": "user", "text": "buy", "dom_index": 3, "message_id": "user-3"}],
            approvals=[{"name": "Approve purchase", "dom_index": 4}],
        )
    ])
    result = MuseChatClient._monitor_turn(page, "main", 3, 10, "user-3")
    assert result["status"] == "approval_required"
    assert result["approval"] == "Approve purchase"


def test_thread_parser_requires_durable_uuid_and_deduplicates():
    rows = normalize_threads(
        [
            {
                "href": "https://muse.ai/thread/eb431c8c-6348-4ba9-9aed-11908cf2d0ed",
                "thread_id": "",
                "title": "Codex headless test",
            },
            {
                "href": "",
                "thread_id": "eb431c8c-6348-4ba9-9aed-11908cf2d0ed",
                "title": "duplicate",
            },
            {"href": "/thread/new", "thread_id": "", "title": "draft"},
        ]
    )
    assert rows == [
        {
            "id": "eb431c8c-6348-4ba9-9aed-11908cf2d0ed",
            "title": "Codex headless test",
            "url": "https://muse.ai/thread/eb431c8c-6348-4ba9-9aed-11908cf2d0ed",
            "kind": "side",
        }
    ]


def test_message_parser_requires_durable_message_id():
    from muse_chat_cli.parsers import normalize_messages

    with pytest.raises(ClientError, match="durable message ID"):
        normalize_messages([{"role": "user", "text": "prompt", "dom_index": 0}])


def test_user_echo_refuses_two_new_identical_turns():
    page = SequencePage([
        snapshot(
            [
                {"role": "user", "text": "same prompt", "dom_index": 1, "message_id": "cli-turn"},
                {"role": "user", "text": "same prompt", "dom_index": 2, "message_id": "other-turn"},
            ]
        )
    ])
    with pytest.raises(ClientError, match="multiple new user turns"):
        MuseChatClient._wait_for_user_echo(page, set(), -1, "same prompt")


def test_press_failure_reports_ambiguous_send_without_retry():
    class FailingComposer(FakeComposer):
        def press(self, key):
            self.pressed.append(key)
            raise RuntimeError("connection reset after key dispatch")

    page = SequencePage([snapshot()])
    page.composer = FailingComposer()
    with pytest.raises(ClientError, match="send outcome is ambiguous"):
        MuseChatClient._send_on_page(
            MuseChatClient.__new__(MuseChatClient),
            page,
            "one send",
            monitor=False,
            timeout=10,
        )
    assert page.composer.pressed == ["Enter"]


def test_compacted_user_fallback_strips_accessibility_prefix():
    assert ".replace(/^User message:\\s*/i, '')" in CHAT_SNAPSHOT_JS


SIDE_ID = "282cc7b4-3813-4ed2-84df-bca90531113b"
DRAFT_TURN_ID = "8c575612-9951-42f8-baea-9d557e0a80f3"
SAVED_TURN_ID = "1f76ec71-ea1c-4501-8418-23b70f9d358c"
SIDE_MESSAGE = "Set up a daily monitor.\n\nWhat to watch: the app review."


class SideDraftPage(SequencePage):
    """Recorded 2026-10-16 shape: the draft echo carries a temporary message ID
    that Muse replaces with the server ID once the thread URL is assigned."""

    def __init__(self, saved_messages):
        super().__init__(
            [
                snapshot(),
                snapshot([
                    {
                        "role": "user",
                        "text": SIDE_MESSAGE,
                        "dom_index": 1,
                        "message_id": DRAFT_TURN_ID,
                        "turn_id": DRAFT_TURN_ID,
                    }
                ]),
                snapshot(saved_messages),
            ],
            url="https://muse.ai/thread/new",
        )

    def evaluate(self, script):
        result = super().evaluate(script)
        if len(self.snapshots) == 1:
            self.url = f"https://muse.ai/thread/{SIDE_ID}"
        return result

    def wait_for_selector(self, _selector, timeout=None):
        return None


def side_client(page):
    client = MuseChatClient.__new__(MuseChatClient)
    client._browser = type("Browser", (), {"get_page": lambda _self, _url: page})()
    return client


def saved_user(text=SIDE_MESSAGE, *, dom_index=1, message_id=SAVED_TURN_ID):
    return {
        "role": "user",
        "text": text,
        "dom_index": dom_index,
        "message_id": message_id,
        "turn_id": message_id,
    }


def test_side_create_monitor_follows_draft_turn_to_saved_server_id():
    page = SideDraftPage([
        saved_user(),
        {
            "role": "assistant",
            "text": "Confirmed, monitor is running.",
            "dom_index": 2,
            "message_id": "assistant-msg-87430a82-ce7f-4953-bcc6-d9ff28043091",
            "turn_id": "assistant-msg-87430a82-ce7f-4953-bcc6-d9ff28043091",
        },
    ])
    result = side_client(page).create_side(SIDE_MESSAGE, monitor=True, timeout=10)
    assert result["status"] == "completed"
    assert result["chat_id"] == SIDE_ID
    assert result["response"] == "Confirmed, monitor is running."
    assert result["turn_message_id"] == SAVED_TURN_ID
    assert page.composer.pressed == ["Enter"]


@pytest.mark.parametrize(
    "saved_messages",
    [
        [saved_user("A different prompt")],
        [saved_user(), saved_user(dom_index=3, message_id="other-user-turn")],
    ],
    ids=["text-mismatch", "second-user-turn"],
)
def test_side_create_monitor_refuses_unprovable_saved_turn(saved_messages):
    saved_messages = [
        *saved_messages,
        {"role": "assistant", "text": "reply", "dom_index": 4, "message_id": "a-reply"},
    ]
    page = SideDraftPage(saved_messages)
    with pytest.raises(ClientError, match="refused to match another response"):
        side_client(page).create_side(SIDE_MESSAGE, monitor=True, timeout=10)


def test_existing_chat_send_never_reanchors_replaced_turn_id():
    page = SequencePage([
        snapshot(),
        snapshot([saved_user(message_id=DRAFT_TURN_ID)]),
        snapshot([
            saved_user(),
            {"role": "assistant", "text": "reply", "dom_index": 2, "message_id": "a-reply"},
        ]),
    ], url=f"https://muse.ai/thread/{SIDE_ID}")
    with pytest.raises(ClientError, match="refused to match another response"):
        MuseChatClient._send_on_page(
            MuseChatClient.__new__(MuseChatClient),
            page,
            SIDE_MESSAGE,
            monitor=True,
            timeout=10,
        )
