"""Bounded retry of the CDP WS opening handshake at daemon start.

A just-spawned Chrome can accept the TCP connection but be too busy to finish
the WebSocket upgrade before websockets' open_timeout, raising
``TimeoutError("timed out during opening handshake")``. The parent process
proved the endpoint live via /json/version moments earlier, so this is a lost
race under host load — ``connect_cdp`` must retry that SAME handshake a
bounded number of times with growing backoff, and must NOT retry non-timeout
handshake failures (403 Allow-flow, bad URL), which cannot succeed on retry.
"""
import asyncio

import pytest

from browser_harness import daemon


# --- _is_transient_handshake_timeout ---------------------------------------


def test_timeout_error_instance_is_transient():
    assert daemon._is_transient_handshake_timeout(TimeoutError()) is True
    assert daemon._is_transient_handshake_timeout(asyncio.TimeoutError()) is True


def test_opening_handshake_timeout_message_is_transient():
    e = Exception("timed out during opening handshake")
    assert daemon._is_transient_handshake_timeout(e) is True


def test_non_timeout_handshake_failures_are_not_transient():
    assert daemon._is_transient_handshake_timeout(Exception("server rejected WebSocket connection: HTTP 403")) is False
    assert daemon._is_transient_handshake_timeout(ConnectionRefusedError("connection refused")) is False


# --- connect_cdp retry behavior ---------------------------------------------


class _FakeCDP:
    """Scripted CDPClient stand-in: raise per-instance outcome or start."""

    instances = []
    outcomes = []

    def __init__(self, url):
        self.url = url
        self.started = False
        self.stopped = False
        _FakeCDP.instances.append(self)
        self._outcome = _FakeCDP.outcomes[len(_FakeCDP.instances) - 1]

    async def start(self):
        if self._outcome is not None:
            raise self._outcome
        self.started = True

    async def stop(self):
        self.stopped = True


@pytest.fixture
def fake_cdp(monkeypatch):
    _FakeCDP.instances = []
    _FakeCDP.outcomes = []
    monkeypatch.setattr(daemon, "CDPClient", _FakeCDP)
    logs = []
    monkeypatch.setattr(daemon, "log", logs.append)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return {"logs": logs, "sleeps": sleeps}


def test_transient_timeout_retries_and_succeeds(fake_cdp, monkeypatch):
    monkeypatch.setenv("BU_CDP_WS", "ws://127.0.0.1:51312/devtools/browser/x")
    _FakeCDP.outcomes = [TimeoutError("timed out during opening handshake"), None, None]

    client = asyncio.run(daemon.connect_cdp("ws://127.0.0.1:51312/devtools/browser/x"))

    assert client is _FakeCDP.instances[1]
    assert client.started is True
    assert len(_FakeCDP.instances) == 2, "expected exactly one retry"
    assert _FakeCDP.instances[0].stopped is True, "failed client must be cleaned up"
    assert fake_cdp["sleeps"] == [1], "first retry backs off 1s"
    assert any("attempt 1/3" in line for line in fake_cdp["logs"])


def test_transient_timeout_exhausts_bounded_attempts_remote_message(fake_cdp, monkeypatch):
    monkeypatch.setenv("BU_CDP_WS", "ws://127.0.0.1:51312/devtools/browser/x")
    _FakeCDP.outcomes = [TimeoutError("timed out during opening handshake")] * daemon.HANDSHAKE_ATTEMPTS

    with pytest.raises(RuntimeError, match="CDP WS handshake failed: .* remote browser WebSocket connection failed"):
        asyncio.run(daemon.connect_cdp("ws://127.0.0.1:51312/devtools/browser/x"))

    assert len(_FakeCDP.instances) == daemon.HANDSHAKE_ATTEMPTS
    assert fake_cdp["sleeps"] == [1, 2], "growing backoff between the bounded attempts"


def test_transient_timeout_exhausts_bounded_attempts_local_message(fake_cdp, monkeypatch):
    monkeypatch.delenv("BU_CDP_WS", raising=False)
    _FakeCDP.outcomes = [TimeoutError("timed out during opening handshake")] * daemon.HANDSHAKE_ATTEMPTS

    with pytest.raises(RuntimeError, match="CDP WS handshake failed: .* click Allow in Chrome"):
        asyncio.run(daemon.connect_cdp("ws://127.0.0.1:9222/devtools/browser/x"))

    assert len(_FakeCDP.instances) == daemon.HANDSHAKE_ATTEMPTS


def test_non_timeout_failure_fails_immediately_without_retry(fake_cdp, monkeypatch):
    monkeypatch.delenv("BU_CDP_WS", raising=False)
    _FakeCDP.outcomes = [Exception("server rejected WebSocket connection: HTTP 403")]

    with pytest.raises(RuntimeError, match="CDP WS handshake failed"):
        asyncio.run(daemon.connect_cdp("ws://127.0.0.1:9222/devtools/browser/x"))

    assert len(_FakeCDP.instances) == 1, "non-timeout handshake failures must not be retried"
    assert fake_cdp["sleeps"] == []


def test_final_failure_message_still_matches_admin_classifiers(fake_cdp, monkeypatch):
    """admin._needs_chrome_remote_debugging_prompt keys on the final message
    text ('ws handshake failed' + 'timed out') — the retry must not change
    that contract when it exhausts its attempts."""
    from browser_harness import admin

    monkeypatch.delenv("BU_CDP_WS", raising=False)
    _FakeCDP.outcomes = [TimeoutError("timed out during opening handshake")] * daemon.HANDSHAKE_ATTEMPTS

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(daemon.connect_cdp("ws://127.0.0.1:9222/devtools/browser/x"))

    assert admin._needs_chrome_remote_debugging_prompt(str(excinfo.value)) is True
