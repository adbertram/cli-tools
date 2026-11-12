"""Turn tracking on existing chats, from history captured 2026-11-12.

Side chat 41551660-... showed both failures. ``chat send --monitor`` saw its
echo under temporary ID e1b9452d..., Muse later rendered the saved turn as
7ec468a6..., and the monitor refused. A fresh ``chat monitor`` page first
rendered only the earlier turns, so it anchored on an older finished turn and
returned that turn's reply.
"""

import pytest

from cli_tools_shared.exceptions import ClientError
from muse_chat_cli import client as module
from muse_chat_cli.client import MuseChatClient

CHAT_ID = "41551660-2138-41d5-9c00-cddcc66951e3"
SUBMITTED = "CourseCraft jobs hand-off, part 1 of 2.\n\nPlease set these up."
TEMP_ID = "e1b9452d-083f-4cd4-8584-f26f4cf63fe8"
SAVED_ID = "7ec468a6-3341-49c4-98f4-1bbbc3a9b599"


def user(dom_index, message_id, text):
    return {"role": "user", "text": text, "dom_index": dom_index,
            "message_id": message_id, "turn_id": message_id}


def assistant(dom_index, uuid, text):
    message_id = f"assistant-msg-{uuid}"
    return {"role": "assistant", "text": text, "dom_index": dom_index,
            "message_id": message_id, "turn_id": message_id}


U1 = user(1, "c774a8e2-d7af-428a-98cd-9e307d0bb6ea", "Hi Mikey, which jobs do you run?")
A2 = assistant(2, "e1d6e392-c047-4eeb-8df0-387572ab6a11", "Plain answers, checked against my cron list.")
# An earlier turn with the same text proves re-anchoring never reaches back.
U3 = user(3, "227bd7f1-5b53-48c2-a17c-32c8fe173b00", SUBMITTED)
A4 = assistant(4, "95765219-fd56-4302-9288-083669ba367d", "Old answer to the earlier identical turn.")
HISTORY = [U1, A2, U3, A4]
REPLY = assistant(6, "0b5c1f2e-7a51-4d8e-9a43-3f1e2c6d9b10", "Both backups are set up.")


def state(*rows, typing=False, working=False):
    return {"messages": list(rows), "typing": typing, "working": working, "approvals": []}


class Composer:
    def __init__(self):
        self.pressed = []

    def fill(self, _value):
        pass

    def press(self, key):
        self.pressed.append(key)


class Page:
    url = f"https://muse.ai/thread/{CHAT_ID}"

    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.clock = 0.0
        self.composer = Composer()

    def evaluate(self, _script):
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]

    def wait_for_timeout(self, milliseconds):
        self.clock += milliseconds / 1000

    def locator(self, _selector):
        return self.composer


@pytest.fixture
def fake_clock(monkeypatch):
    def install(page):
        monkeypatch.setattr(module, "RESPONSE_SETTLE_SECONDS", 1.0)
        monkeypatch.setattr(module.time, "monotonic", lambda: page.clock)
        return page
    return install


def send(page):
    return MuseChatClient._send_on_page(
        MuseChatClient.__new__(MuseChatClient), page, SUBMITTED, monitor=True, timeout=60
    )


def test_existing_chat_send_follows_temporary_id_through_gap_to_saved_turn(fake_clock):
    page = fake_clock(Page([
        state(*HISTORY),
        state(*HISTORY, user(5, TEMP_ID, SUBMITTED)),
        state(*HISTORY, user(5, TEMP_ID, SUBMITTED), typing=True),
        state(*HISTORY, working=True),
        state(*HISTORY, user(5, SAVED_ID, SUBMITTED), REPLY),
    ]))
    result = send(page)
    assert result["status"] == "completed"
    assert result["chat_id"] == CHAT_ID
    assert result["turn_message_id"] == SAVED_ID
    assert result["response"] == REPLY["text"]
    assert page.composer.pressed == ["Enter"]


def test_existing_chat_send_follows_immediate_id_swap(fake_clock):
    page = fake_clock(Page([
        state(*HISTORY),
        state(*HISTORY, user(5, TEMP_ID, SUBMITTED)),
        state(*HISTORY, user(5, SAVED_ID, SUBMITTED), REPLY),
    ]))
    result = send(page)
    assert result["turn_message_id"] == SAVED_ID
    assert result["response"] == REPLY["text"]


@pytest.mark.parametrize(
    "saved_rows",
    [
        [user(5, SAVED_ID, "A message someone else sent")],
        [user(5, SAVED_ID, SUBMITTED), user(7, "9d1f6a0e-2b8c-4f3a-8e57-c4a1b2d3e4f5", SUBMITTED)],
    ],
    ids=["different-new-turn", "two-identical-new-turns"],
)
def test_existing_chat_send_refuses_unprovable_saved_turn(fake_clock, saved_rows):
    page = fake_clock(Page([
        state(*HISTORY),
        state(*HISTORY, user(5, TEMP_ID, SUBMITTED)),
        state(*HISTORY, *saved_rows, REPLY),
    ]))
    with pytest.raises(ClientError, match="refused to match another response"):
        send(page)


def test_existing_chat_send_gap_that_never_resolves_fails_at_deadline(fake_clock):
    page = fake_clock(Page([
        state(*HISTORY),
        state(*HISTORY, user(5, TEMP_ID, SUBMITTED)),
        state(*HISTORY),
    ]))
    with pytest.raises(ClientError, match=TEMP_ID):
        send(page)
    assert page.clock >= 60


def test_chat_monitor_moves_to_turn_rendered_after_page_load(fake_clock):
    page = fake_clock(Page([
        state(U1, A2),
        state(U1, A2, typing=True, working=True),
        state(U1, A2, U3, typing=True, working=True),
        state(U1, A2, U3, A4),
    ]))
    client = MuseChatClient.__new__(MuseChatClient)
    client._open_chat = lambda _chat_id: page
    result = client.monitor(CHAT_ID, timeout=60)
    assert result["status"] == "completed"
    assert result["turn_message_id"] == U3["message_id"]
    assert result["response"] == A4["text"]


def test_chat_monitor_waits_for_late_activity_before_trusting_older_reply(fake_clock):
    page = fake_clock(Page([
        state(U1, A2),
        state(U1, A2),
        state(U1, A2),
        state(U1, A2, typing=True, working=True),
        state(U1, A2, U3, A4),
    ]))
    client = MuseChatClient.__new__(MuseChatClient)
    client._open_chat = lambda _chat_id: page
    result = client.monitor(CHAT_ID, timeout=60)
    assert result["turn_message_id"] == U3["message_id"]
    assert result["response"] == A4["text"]
