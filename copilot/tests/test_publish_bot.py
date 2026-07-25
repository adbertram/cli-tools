"""
Tests for DataverseClient.publish_bot — regression lock for the false-success
bug where PvaPublish would return 200 with an empty payload AND a server-side
publish job would fail with "Node is unknown to the system", but the CLI would
report "published successfully" because it only checked the HTTP status code.

The fix: publish_bot reads synchronizationstatus.lastFinishedPublishOperation
both before and after the POST, polls until operationEnd advances past the
pre-publish baseline, and raises ClientError if the job's final status isn't
"Succeeded".
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import copilot_cli.capacity as capacity
from copilot_cli.client import ClientError, DataverseClient


BOT_ID = "12345678-1234-1234-1234-123456789abc"
BASELINE_OP_END = "2026-03-19T15:10:49.7102985Z"
NEW_OP_END = "2026-04-11T15:30:00.0000000Z"
_REAL_ENSURE_CAPACITY = capacity.ensure_tools_and_knowledge_entitled


def _make_client() -> DataverseClient:
    """Construct a DataverseClient bypassing the normal config/auth path."""
    client = DataverseClient.__new__(DataverseClient)
    client.api_url = "https://example.crm.dynamics.com/api/data/v9.2"
    return client


@pytest.fixture(autouse=True)
def _publish_capacity_entitled(monkeypatch):
    """Keep publish-status tests focused while exercising the shared gate."""
    monkeypatch.setattr(capacity, "resolve_environment_id", lambda: "env-1")
    monkeypatch.setattr(
        capacity, "ensure_tools_and_knowledge_entitled", lambda *args, **kwargs: None
    )


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._payload


def test_publish_bot_blocks_before_sync_or_post_without_capacity(monkeypatch):
    client = _make_client()

    monkeypatch.setattr(capacity, "resolve_environment_id", lambda: "env-1")
    monkeypatch.setattr(
        capacity, "environment_supports_tools_and_knowledge", lambda env: False
    )
    monkeypatch.setattr(
        capacity, "_resolve_environment_display_name", lambda env: "No Capacity Env"
    )
    monkeypatch.setattr(
        capacity,
        "ensure_tools_and_knowledge_entitled",
        _REAL_ENSURE_CAPACITY,
    )
    monkeypatch.setattr(
        client,
        "get",
        lambda path: (_ for _ in ()).throw(
            AssertionError(f"publish sync read must not run: {path}")
        ),
    )

    class FakeHttp:
        def post(self, *args, **kwargs):
            raise AssertionError("publish POST must not run")

    client._http_client = FakeHttp()

    with pytest.raises(capacity.CapacityError, match="agents cannot be published"):
        client.publish_bot(BOT_ID)


def test_publish_bot_blocks_before_sync_or_post_when_capacity_is_indeterminate(monkeypatch):
    client = _make_client()

    monkeypatch.setattr(capacity, "resolve_environment_id", lambda: "env-1")
    monkeypatch.setattr(
        capacity,
        "environment_supports_tools_and_knowledge",
        lambda env: (_ for _ in ()).throw(ClientError("licensing signal unavailable")),
    )
    monkeypatch.setattr(
        capacity,
        "ensure_tools_and_knowledge_entitled",
        _REAL_ENSURE_CAPACITY,
    )
    monkeypatch.setattr(
        client,
        "get",
        lambda path: (_ for _ in ()).throw(
            AssertionError(f"publish sync read must not run: {path}")
        ),
    )

    class FakeHttp:
        def post(self, *args, **kwargs):
            raise AssertionError("publish POST must not run")

    client._http_client = FakeHttp()

    with pytest.raises(ClientError, match="licensing signal unavailable"):
        client.publish_bot(BOT_ID)


def test_publish_bot_raises_when_job_fails_with_unknown_node(monkeypatch):
    """
    Reproduces the Brand agent regression: PvaPublish returns 200 with empty
    payload, the async publish job finishes with status='Failed' and a
    diagnosticList entry containing 'Node is unknown to the system', and the
    CLI must raise ClientError with that diagnostic message instead of
    reporting success.
    """
    client = _make_client()

    sync_states = iter([
        # baseline read (pre-POST)
        {
            "lastFinishedPublishOperation": {
                "status": "Failed",
                "operationEnd": BASELINE_OP_END,
                "diagnosticDetails": [],
            }
        },
        # first poll — operationEnd advanced to new failed job
        {
            "lastFinishedPublishOperation": {
                "status": "Failed",
                "operationEnd": NEW_OP_END,
                "diagnosticDetails": [
                    {
                        "componentId": "abcdef01-2345-6789-abcd-ef0123456789",
                        "diagnosticList": [
                            {"errorMessage": "Node is unknown to the system"}
                        ],
                    }
                ],
            }
        },
    ])

    def fake_get(path: str):
        if "synchronizationstatus" in path:
            return {"synchronizationstatus": next(sync_states)}
        raise AssertionError(f"unexpected GET path: {path}")

    class FakeHttp:
        def post(self, url, headers=None, json=None, timeout=None):
            return _FakeResponse(200, {"PublishedBotContentId": "", "PublishBotJobResponse": None})

    monkeypatch.setattr(client, "get", fake_get)
    monkeypatch.setattr(client, "_get_headers", lambda: {})
    client._http_client = FakeHttp()

    with pytest.raises(ClientError) as excinfo:
        client.publish_bot(BOT_ID, poll_timeout=10.0, poll_interval=0.0)

    msg = str(excinfo.value)
    assert "Failed" in msg
    assert "Node is unknown to the system" in msg
    assert "abcdef01-2345-6789-abcd-ef0123456789" in msg


def test_publish_bot_raises_with_dlp_diagnostic_code_and_violation_type(monkeypatch):
    """Failed publish errors include structured DLP diagnostic fields."""
    client = _make_client()

    sync_states = iter([
        {
            "lastFinishedPublishOperation": {
                "status": "Succeeded",
                "operationEnd": BASELINE_OP_END,
                "diagnosticDetails": [],
            }
        },
        {
            "lastFinishedPublishOperation": {
                "status": "Failed",
                "operationEnd": NEW_OP_END,
                "diagnosticDetails": [
                    {
                        "componentId": None,
                        "diagnosticList": [
                            {
                                "errorCode": "DlpViolationError",
                                "violationType": "BlockedConnector",
                                "errorMessage": "At least one connector here has been blocked by your admin",
                            }
                        ],
                    }
                ],
            }
        },
    ])

    def fake_get(path: str):
        if "synchronizationstatus" in path:
            return {"synchronizationstatus": next(sync_states)}
        raise AssertionError(f"unexpected GET path: {path}")

    class FakeHttp:
        def post(self, url, headers=None, json=None, timeout=None):
            return _FakeResponse(200, {"PublishedBotContentId": "", "PublishBotJobResponse": None})

    monkeypatch.setattr(client, "get", fake_get)
    monkeypatch.setattr(client, "_get_headers", lambda: {})
    client._http_client = FakeHttp()

    with pytest.raises(ClientError) as excinfo:
        client.publish_bot(BOT_ID, poll_timeout=10.0, poll_interval=0.0)

    msg = str(excinfo.value)
    assert "component ?" in msg
    assert "DlpViolationError" in msg
    assert "BlockedConnector" in msg
    assert "At least one connector here has been blocked by your admin" in msg


def test_publish_bot_returns_success_when_job_succeeds(monkeypatch):
    """Happy path: sync state advances and status becomes Succeeded."""
    client = _make_client()

    sync_states = iter([
        # baseline
        {
            "lastFinishedPublishOperation": {
                "status": "Succeeded",
                "operationEnd": BASELINE_OP_END,
            }
        },
        # poll — new successful job
        {
            "lastFinishedPublishOperation": {
                "status": "Succeeded",
                "operationEnd": NEW_OP_END,
            }
        },
    ])

    def fake_get(path: str):
        if "synchronizationstatus" in path:
            return {"synchronizationstatus": next(sync_states)}
        if "publishedon" in path:
            return {"publishedon": "2026-04-11T15:30:05Z"}
        raise AssertionError(f"unexpected GET path: {path}")

    class FakeHttp:
        def post(self, url, headers=None, json=None, timeout=None):
            return _FakeResponse(200, {"PublishedBotContentId": "abc123", "PublishBotJobResponse": {"jobId": "j1"}})

    monkeypatch.setattr(client, "get", fake_get)
    monkeypatch.setattr(client, "_get_headers", lambda: {})
    client._http_client = FakeHttp()

    result = client.publish_bot(BOT_ID, poll_timeout=10.0, poll_interval=0.0)

    assert result["status"] == "success"
    assert result["PublishedBotContentId"] == "abc123"
    assert result["publishedon"] == "2026-04-11T15:30:05Z"
    assert result["operationEnd"] == NEW_OP_END


def test_publish_bot_raises_when_poll_times_out(monkeypatch):
    """If operationEnd never advances, raise ClientError — never claim success."""
    client = _make_client()

    stuck_state = {
        "lastFinishedPublishOperation": {
            "status": "Succeeded",
            "operationEnd": BASELINE_OP_END,
        }
    }

    def fake_get(path: str):
        if "synchronizationstatus" in path:
            return {"synchronizationstatus": stuck_state}
        raise AssertionError(f"unexpected GET path: {path}")

    class FakeHttp:
        def post(self, url, headers=None, json=None, timeout=None):
            return _FakeResponse(200, {"PublishedBotContentId": "", "PublishBotJobResponse": None})

    monkeypatch.setattr(client, "get", fake_get)
    monkeypatch.setattr(client, "_get_headers", lambda: {})
    client._http_client = FakeHttp()

    with pytest.raises(ClientError, match="did not complete within"):
        client.publish_bot(BOT_ID, poll_timeout=0.05, poll_interval=0.01)


def test_publish_bot_handles_synchronizationstatus_as_json_string(monkeypatch):
    """
    Dataverse sometimes returns synchronizationstatus as a JSON-encoded string
    rather than a parsed object. _read_publish_sync_state must handle both.
    """
    client = _make_client()

    baseline_raw = json.dumps({
        "lastFinishedPublishOperation": {
            "status": "Failed",
            "operationEnd": BASELINE_OP_END,
        }
    })
    new_raw = json.dumps({
        "lastFinishedPublishOperation": {
            "status": "Succeeded",
            "operationEnd": NEW_OP_END,
        }
    })
    states = iter([baseline_raw, new_raw])

    def fake_get(path: str):
        if "synchronizationstatus" in path:
            return {"synchronizationstatus": next(states)}
        if "publishedon" in path:
            return {"publishedon": "2026-04-11T15:30:05Z"}
        raise AssertionError(f"unexpected GET path: {path}")

    class FakeHttp:
        def post(self, url, headers=None, json=None, timeout=None):
            return _FakeResponse(200, {"PublishedBotContentId": "x", "PublishBotJobResponse": None})

    monkeypatch.setattr(client, "get", fake_get)
    monkeypatch.setattr(client, "_get_headers", lambda: {})
    client._http_client = FakeHttp()

    result = client.publish_bot(BOT_ID, poll_timeout=10.0, poll_interval=0.0)
    assert result["status"] == "success"
    assert result["operationEnd"] == NEW_OP_END
