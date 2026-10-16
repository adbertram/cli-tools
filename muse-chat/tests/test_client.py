from __future__ import annotations

import pytest

from cli_tools_shared.exceptions import ClientError
from muse_chat_cli import client as client_module
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

    def evaluate(self, _script):
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
