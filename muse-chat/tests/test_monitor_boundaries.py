"""Guard message targeting and response correlation at observable boundaries."""

from types import SimpleNamespace

import pytest

from cli_tools_shared.exceptions import ClientError
from muse_chat_cli.client import MuseChatClient


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://muse.ai.example.com/",
        "http://muse.ai/",
        "https://muse.ai/login",
        "https://muse.ai/thread/new",
    ],
)
def test_main_target_rejects_other_origins_and_paths(url):
    with pytest.raises(ClientError):
        MuseChatClient._require_target(SimpleNamespace(url=url), "main")


def test_main_target_accepts_actual_main_chat():
    MuseChatClient._require_target(SimpleNamespace(url="https://muse.ai/"), "main")


def test_side_target_rejects_same_uuid_on_another_origin():
    chat_id = "eb431c8c-6348-4ba9-9aed-11908cf2d0ed"
    with pytest.raises(ClientError):
        MuseChatClient._require_target(
            SimpleNamespace(url=f"https://example.com/thread/{chat_id}"), chat_id
        )


def test_monitor_ignores_old_reply_and_old_approval():
    old = {
        "role": "assistant",
        "text": "Old answer",
        "dom_index": 1,
        "message_id": "a-old",
    }
    turn = {
        "role": "user",
        "text": "Current prompt",
        "dom_index": 5,
        "message_id": "u-current",
    }
    fresh = {
        "role": "assistant",
        "text": "Fresh answer",
        "dom_index": 6,
        "message_id": "a-fresh",
    }
    snapshots = iter(
        [
            {
                "messages": [old, turn],
                "typing": False,
                "working": False,
                "approvals": [{"name": "Allow old request", "dom_index": 2}],
            },
            {
                "messages": [old, turn, fresh],
                "typing": False,
                "working": False,
                "approvals": [],
            },
        ]
    )
    waits = []
    page = SimpleNamespace(
        url="https://muse.ai/",
        evaluate=lambda _script: next(snapshots),
        wait_for_timeout=waits.append,
    )
    result = MuseChatClient._monitor_turn(page, "main", 5, 10, "u-current")
    assert result["status"] == "completed"
    assert result["response"] == "Fresh answer"
    assert len(waits) == 1


def test_monitor_preserves_multiline_response():
    response = "Example:\n\n```python\nfor item in items:\n    process(item)\n```"
    page = SimpleNamespace(
        url="https://muse.ai/",
        evaluate=lambda _script: {
            "messages": [
                {
                    "role": "user",
                    "text": "prompt",
                    "dom_index": 5,
                    "message_id": "u-current",
                },
                {
                    "role": "assistant",
                    "text": response,
                    "dom_index": 6,
                    "message_id": "a-fresh",
                },
            ],
            "typing": False,
            "working": False,
            "approvals": [],
        },
    )
    result = MuseChatClient._monitor_turn(page, "main", 5, 10, "u-current")
    assert result["response"] == response


def test_monitor_does_not_take_response_after_next_user_turn(monkeypatch):
    ticks = iter([0.0, 11.0])
    monkeypatch.setattr("muse_chat_cli.client.time.monotonic", lambda: next(ticks))
    page = SimpleNamespace(
        url="https://muse.ai/",
        evaluate=lambda _script: {
            "messages": [
                {"role": "user", "text": "first", "dom_index": 1, "message_id": "u-first"},
                {"role": "user", "text": "second", "dom_index": 2, "message_id": "u-second"},
                {"role": "assistant", "text": "second answer", "dom_index": 3, "message_id": "a-second"},
            ],
            "typing": False,
            "working": False,
            "approvals": [],
        },
        wait_for_timeout=lambda _milliseconds: None,
    )
    result = MuseChatClient._monitor_turn(page, "main", 1, 10, "u-first")
    assert result["status"] == "timeout"
    assert result["response"] is None


def test_monitor_refuses_when_anchored_user_disappears():
    page = SimpleNamespace(
        url="https://muse.ai/",
        evaluate=lambda _script: {
            "messages": [
                {
                    "role": "assistant",
                    "text": "unrelated",
                    "dom_index": 9,
                    "message_id": "a-other",
                }
            ],
            "typing": False,
            "working": False,
            "approvals": [],
        },
    )
    with pytest.raises(ClientError, match="refused to match another response"):
        MuseChatClient._monitor_turn(page, "main", 1, 10, "u-missing")


def test_monitor_drops_disappeared_partial_before_newer_turn(monkeypatch):
    ticks = iter([0.0, 0.5, 11.0])
    monkeypatch.setattr("muse_chat_cli.client.time.monotonic", lambda: next(ticks))
    turn = {"role": "user", "text": "first", "dom_index": 1, "message_id": "u-first"}
    snapshots = iter(
        [
            {
                "messages": [
                    turn,
                    {"role": "assistant", "text": "partial", "dom_index": 2, "message_id": "a-partial"},
                ],
                "typing": False,
                "working": True,
                "approvals": [],
            },
            {
                "messages": [
                    turn,
                    {"role": "user", "text": "second", "dom_index": 3, "message_id": "u-second"},
                    {"role": "assistant", "text": "second answer", "dom_index": 4, "message_id": "a-second"},
                ],
                "typing": False,
                "working": False,
                "approvals": [],
            },
        ]
    )
    page = SimpleNamespace(
        url="https://muse.ai/",
        evaluate=lambda _script: next(snapshots),
        wait_for_timeout=lambda _milliseconds: None,
    )
    result = MuseChatClient._monitor_turn(page, "main", 1, 10, "u-first")
    assert result["status"] == "timeout"
    assert result["response"] is None


def test_monitor_refuses_direct_reply_mixed_with_proactive_update():
    page = SimpleNamespace(
        url="https://muse.ai/",
        evaluate=lambda _script: {
            "messages": [
                {"role": "user", "text": "prompt", "dom_index": 1, "message_id": "u-current"},
                {"role": "assistant", "text": "direct reply", "dom_index": 2, "message_id": "a-direct"},
                {"role": "assistant", "text": "unrelated update", "dom_index": 3, "message_id": "a-proactive"},
            ],
            "typing": False,
            "working": False,
            "approvals": [],
        },
    )
    with pytest.raises(ClientError, match="multiple assistant messages"):
        MuseChatClient._monitor_turn(page, "main", 1, 10, "u-current")


def test_monitor_combines_ordered_components_when_candidates_share_turn_id():
    page = SimpleNamespace(
        url="https://muse.ai/",
        evaluate=lambda _script: {
            "messages": [
                {"role": "user", "text": "prompt", "dom_index": 1, "message_id": "u-current"},
                {
                    "role": "assistant",
                    "text": "progress",
                    "dom_index": 2,
                    "message_id": "a-progress",
                    "turn_id": "assistant-turn",
                },
                {
                    "role": "assistant",
                    "text": "final answer",
                    "dom_index": 3,
                    "message_id": "a-final",
                    "turn_id": "assistant-turn",
                },
            ],
            "typing": False,
            "working": False,
            "approvals": [],
        },
    )
    result = MuseChatClient._monitor_turn(page, "main", 1, 10, "u-current")
    assert result["status"] == "completed"
    assert result["response"] == "progress\n\nfinal answer"


def test_monitor_refuses_proactive_update_before_requested_reply():
    page = SimpleNamespace(
        url="https://muse.ai/",
        evaluate=lambda _script: {
            "messages": [
                {"role": "user", "text": "prompt", "dom_index": 1, "message_id": "u-current"},
                {
                    "role": "assistant",
                    "text": "unrelated proactive update",
                    "dom_index": 2,
                    "message_id": "a-proactive",
                    "turn_id": "proactive-turn",
                },
                {
                    "role": "assistant",
                    "text": "requested reply",
                    "dom_index": 3,
                    "message_id": "a-requested",
                    "turn_id": "requested-turn",
                },
            ],
            "typing": False,
            "working": False,
            "approvals": [],
        },
    )
    with pytest.raises(ClientError, match="refused to choose"):
        MuseChatClient._monitor_turn(page, "main", 1, 10, "u-current")
