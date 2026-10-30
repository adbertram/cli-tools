"""Messenger thread ids: numeric and end-to-end-encrypted cid.g.<digits> (no network)."""
from pathlib import Path

import pytest

from facebook_cli.client import FacebookClient, MessengerLocked
from facebook_cli.messenger_parsers import (
    extract_conversations_from_snapshot,
    messenger_thread_url,
)

FIXTURE = Path(__file__).parent / "fixtures" / "messenger_thread_list.txt"
CID_G = "cid.g.1910025477072852"


def test_list_parsing_keeps_cid_g_threads_alongside_numeric_ones():
    conversations = extract_conversations_from_snapshot(FIXTURE.read_text())
    assert [c["id"] for c in conversations] == [
        "100000000000001",
        CID_G,
        "100000000000002",
        "cid.g.2020025477072853",
        "100000000000003",
    ]


def test_list_parsing_numeric_only_unchanged():
    snapshot = '- link "A":\n-   - /url: "/messages/t/123/"\n'
    assert [c["id"] for c in extract_conversations_from_snapshot(snapshot)] == ["123"]


def test_list_parsing_ignores_non_thread_links():
    snapshot = '-   - /url: "/messages/t/"\n-   - /url: "/messages/t/notanid/"\n-   - /url: "/marketplace/"\n'
    assert extract_conversations_from_snapshot(snapshot) == []


@pytest.mark.parametrize("thread_id", ["123456789", CID_G])
def test_thread_url_accepts_numeric_and_cid_g(thread_id):
    assert messenger_thread_url(thread_id) == f"https://www.facebook.com/messages/t/{thread_id}/"


@pytest.mark.parametrize("bad", ["", "abc", "cid.g.", "cid.g.12ab", "123/../x", "cid.x.123"])
def test_thread_url_rejects_other_ids(bad):
    with pytest.raises(ValueError, match="Invalid Messenger thread id"):
        messenger_thread_url(bad)


def test_get_conversation_navigates_to_cid_g_url(monkeypatch):
    client = FacebookClient.__new__(FacebookClient)
    visited = []

    class Page:
        def wait_for_timeout(self, ms):
            pass

    monkeypatch.setattr(client, "_get_page", lambda url, *a, **k: visited.append(url) or Page())
    monkeypatch.setattr(client, "_assert_authenticated_page", lambda *a, **k: None)
    monkeypatch.setattr(client, "_snapshot", lambda page: "- paragraph [ref=e1]: hello there")

    result = client.get_conversation(CID_G)

    assert visited == [f"https://www.facebook.com/messages/t/{CID_G}/"]
    assert result["conversation_id"] == CID_G
    assert result["messages"] == [{"text": "hello there"}]


PIN_SNAPSHOT = '- dialog "Restore your chats":\n-   - heading "Enter your PIN to restore your chats"\n'


def _offline_client(monkeypatch, snapshot):
    client = FacebookClient.__new__(FacebookClient)

    class Page:
        def wait_for_timeout(self, ms):
            pass

    monkeypatch.setattr(client, "_get_page", lambda url, *a, **k: Page())
    monkeypatch.setattr(client, "_assert_authenticated_page", lambda *a, **k: None)
    monkeypatch.setattr(client, "_snapshot", lambda page: snapshot)
    return client


def test_list_conversations_returns_cid_g_threads(monkeypatch):
    client = _offline_client(monkeypatch, FIXTURE.read_text())
    assert CID_G in [c["id"] for c in client.list_conversations(limit=50)]


def test_list_conversations_fails_when_pin_locked(monkeypatch):
    client = _offline_client(monkeypatch, PIN_SNAPSHOT)
    with pytest.raises(MessengerLocked, match="^MESSENGER_LOCKED:"):
        client.list_conversations()


def test_get_conversation_fails_when_pin_locked(monkeypatch):
    client = _offline_client(monkeypatch, PIN_SNAPSHOT)
    with pytest.raises(MessengerLocked, match="^MESSENGER_LOCKED:"):
        client.get_conversation(CID_G)
