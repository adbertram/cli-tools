"""Offline client tests for the Grok Bot Sessions CLI.

These tests drive the transcript pager with a fake Connect transport so the
shared-``seq`` boundary behaviour is exercised without a live account. No
credential material is read, faked, or asserted here.
"""
import base64
import json
from pathlib import Path

import pytest

from grokbot_sessions_cli import client as client_module


class DummyConfig:
    """Minimal config surface the client needs for offline transport tests."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.api_base_url = "https://example.invalid"
        self.client_version = "0.0.0"
        self.app_dir = Path("/tmp/grokbot-sessions-test-app")

    def get_profile_data_dir(self) -> Path:
        return self.storage_dir


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self.ok = True
        self.content = b"{}" if payload is not None else b""
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""
        self.headers = {}

    def json(self):
        if self._payload is None:
            return {}
        return self._payload


def body(entry_id: str) -> str:
    return base64.b64encode(json.dumps({"kind": "message", "id": entry_id}).encode()).decode()


def make_entry(entry_id: str, seq: int) -> dict:
    return {"seq": str(seq), "entryKind": "message", "entryId": entry_id, "body": body(entry_id)}


@pytest.fixture()
def offline_client(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "false")
    client = client_module.GrokBotClient(config=DummyConfig(tmp_path))
    return client


def test_transcript_deduplicates_shared_seq_boundary(offline_client, monkeypatch):
    """Page 2 re-includes the boundary seq bucket; the pager must de-duplicate."""
    pages = {
        None: [
            make_entry("t5u", 9),
            make_entry("t4u", 8),
            make_entry("t3u", 7),
            make_entry("t2u", 7),
        ],
        8: [make_entry("t2u", 7), make_entry("t1u", 6)],
    }
    calls = []

    def fake_call(method, payload=None, retry=True):
        before_seq = payload.get("beforeSeq")
        calls.append(before_seq)
        entries = pages[before_seq]
        return {"entries": entries, "generation": 1}

    monkeypatch.setattr(offline_client, "_call", fake_call)
    monkeypatch.setattr(client_module, "TRANSCRIPT_PAGE_SIZE", 4)

    result = offline_client.transcript("scope", "uuid")

    ids = [entry["entryId"] for entry in result["entries"]]
    assert len(ids) == len(set(ids)), "pager returned duplicate entries"
    assert ids == ["t5u", "t4u", "t3u", "t2u", "t1u"]
    assert calls == [None, 8]


def test_transcript_stops_on_short_page(offline_client, monkeypatch):
    monkeypatch.setattr(
        offline_client,
        "_call",
        lambda method, payload=None, retry=True: {"entries": [make_entry("t0u", 1)]},
    )
    monkeypatch.setattr(client_module, "TRANSCRIPT_PAGE_SIZE", 8)

    result = offline_client.transcript("scope", "uuid")

    assert len(result["entries"]) == 1
    assert result["pages"] == 1


def test_transcript_pushes_small_limit_into_page_size(offline_client, monkeypatch):
    seen = []

    def fake_call(method, payload=None, retry=True):
        seen.append(payload["limit"])
        return {"entries": [make_entry("t0u", 1)]}

    monkeypatch.setattr(offline_client, "_call", fake_call)
    monkeypatch.setattr(client_module, "TRANSCRIPT_PAGE_SIZE", 200)

    result = offline_client.transcript("scope", "uuid", limit=1)

    assert seen == [1]
    assert len(result["entries"]) == 1


def test_transcript_stops_when_a_page_adds_nothing(offline_client, monkeypatch):
    """A full page of already-seen entries must not loop forever."""
    page = [make_entry("t0u", 1)]

    monkeypatch.setattr(offline_client, "_call", lambda method, payload=None, retry=True: {"entries": page})
    monkeypatch.setattr(client_module, "TRANSCRIPT_PAGE_SIZE", 1)

    result = offline_client.transcript("scope", "uuid")

    assert len(result["entries"]) == 1
    assert result["pages"] == 2


def test_call_treats_empty_body_as_empty_result(offline_client, monkeypatch):
    monkeypatch.setattr(offline_client, "_headers", lambda: {})
    monkeypatch.setattr(
        client_module.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(None),
    )

    assert offline_client._call("ListGrokBotTranscriptEntries", {"agentId": "uuid"}) == {}


def test_split_entry_id_requires_agent_prefix():
    assert client_module.split_entry_id("uuid:t3u") == ("uuid", "t3u")
    with pytest.raises(client_module.ClientError):
        client_module.split_entry_id("t3u")


def test_masked_checksum_is_deterministic_and_carries_machine_id():
    first = client_module.masked_checksum("machine", seconds=1700000000)
    second = client_module.masked_checksum("machine", seconds=1700000000)
    later = client_module.masked_checksum("machine", seconds=1700000001)

    assert first == second
    assert first != later
    assert first.endswith("machine")
    assert "=" not in first


def test_cache_scope_separates_data_sources(tmp_path, monkeypatch):
    """A cached roster must not be served for a different endpoint/app dir.

    Regression for the chaos finding that ``GROKBOT_SESSIONS_API_BASE`` and
    ``GROKBOT_SESSIONS_APP_DIR`` overrides were ignored on a cache hit.
    """
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("CACHE_TTL", "3600")
    client = client_module.GrokBotClient(config=DummyConfig(tmp_path))
    counter = {"n": 0}

    def fake_call(method, payload=None, retry=True):
        counter["n"] += 1
        return {
            "agents": [
                {"id": "1", "legacyAgentId": "uuid", "name": f"call-{counter['n']}"}
            ]
        }

    monkeypatch.setattr(client, "_call", fake_call)

    first = client._agent_records("endpoint-a")
    second = client._agent_records("endpoint-b")
    cached_first = client._agent_records("endpoint-a")

    assert first[0]["name"] == "call-1"
    assert second[0]["name"] == "call-2", "a different scope must not reuse the entry"
    assert cached_first[0]["name"] == "call-1", "the same scope must reuse its entry"


def test_cache_scope_tracks_environment_overrides(tmp_path, monkeypatch):
    """The scope carries the API base and app dir the client actually uses."""
    monkeypatch.setenv("GROKBOT_SESSIONS_API_BASE", "https://example.invalid/base")
    monkeypatch.setenv("GROKBOT_SESSIONS_APP_DIR", "/tmp/gb-scope")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    config = DummyConfig(tmp_path)
    config.api_base_url = "https://example.invalid/base"
    config.app_dir = Path("/tmp/gb-scope")
    client = client_module.GrokBotClient(config=config)

    assert client.cache_scope == "https://example.invalid/base|/tmp/gb-scope|active"
