from __future__ import annotations

import json
import gzip
import zlib
from unittest.mock import MagicMock

import pytest

import requests

from cli_tools_shared.http_session import (
    BrowserAuthState,
    BrowserAuthStateError,
    BrowserAuthenticatedHttpClient,
    BrowserCookie,
    RequestsRetryPolicy,
    request_with_retry,
)
from cli_tools_shared.exceptions import ClientError


def _make_state() -> BrowserAuthState:
    """Build a sample ``BrowserAuthState`` directly from cookies.

    The persistent-profile refactor removed disk-snapshot loading; this
    helper replaces the old ``_write_state`` + ``from_file`` pair.
    """
    return BrowserAuthState(
        cookies=(
            BrowserCookie(name="session", value="abc", domain=".example.com", path="/", expires=-1.0),
            BrowserCookie(name="hostonly", value="def", domain="www.example.com", path="/", expires=9999999999.0),
            BrowserCookie(name="expired", value="old", domain=".example.com", path="/", expires=1.0),
            BrowserCookie(name="other", value="zzz", domain=".other.test", path="/", expires=-1.0),
        ),
    )


class _FakeResponse:
    def __init__(
        self,
        body: bytes,
        chunk_size: int | None = None,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self.body = body
        self.chunk_size = chunk_size
        self.status = status
        self.headers = headers or {}
        self.read_calls = 0
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        if self.offset >= len(self.body):
            return b""
        amount = self.chunk_size if self.chunk_size is not None else size
        if amount < 0:
            amount = len(self.body) - self.offset
        chunk = self.body[self.offset:self.offset + amount]
        self.offset += len(chunk)
        return chunk


def test_auth_state_filters_cookies_for_host():
    state = _make_state()

    assert [cookie.name for cookie in state.cookies_for_host(
        "www.example.com",
        ["example.com"],
        now=100,
    )] == ["session", "hostonly"]


def test_cookie_header_requires_auth_cookie():
    state = _make_state()

    with pytest.raises(BrowserAuthStateError, match="required cookies"):
        state.cookie_header_for_url(
            "https://www.example.com/groups/1",
            ["example.com"],
            required_cookies=["missing"],
            now=100,
        )


def test_cookie_header_filters_by_request_host():
    state = _make_state()

    header = state.cookie_header_for_url(
        "https://api.example.com/data",
        ["example.com"],
        required_cookies=["session"],
        now=100,
    )

    assert header == "session=abc"


def test_http_client_get_text_stops_after_markers():
    response = _FakeResponse(b"one abc two target tail that should not be read", chunk_size=8)
    captured = {}

    def opener(request, timeout):
        captured["cookie"] = request.headers["Cookie"]
        captured["timeout"] = timeout
        return response

    client = BrowserAuthenticatedHttpClient(
        _make_state(),
        allowed_domains=["example.com"],
        required_cookies=["session"],
        timeout=3,
        opener=opener,
    )

    body = client.get_text("https://www.example.com/groups/1", stop_after_markers=["target"])

    assert "target" in body
    assert "tail that should not be read" not in body
    assert captured == {"cookie": "session=abc; hostonly=def", "timeout": 3}


def test_http_client_non_200_raises():
    def opener(request, timeout):
        return _FakeResponse(b"denied", status=403)

    client = BrowserAuthenticatedHttpClient(
        _make_state(),
        allowed_domains=["example.com"],
        opener=opener,
    )

    with pytest.raises(ClientError, match="HTTP 403"):
        client.get_text("https://www.example.com/groups/1")


def test_http_client_decodes_gzip_response():
    compressed = gzip.compress(b'{"ok":true}')
    captured = {}

    def opener(request, timeout):
        captured["accept_encoding"] = request.headers["Accept-encoding"]
        return _FakeResponse(compressed, headers={"Content-Encoding": "gzip"})

    client = BrowserAuthenticatedHttpClient(
        _make_state(),
        allowed_domains=["example.com"],
        opener=opener,
    )

    body = client.get_text(
        "https://www.example.com/api/data",
        headers={"Accept-Encoding": "gzip"},
    )

    assert body == '{"ok":true}'
    assert captured["accept_encoding"] == "gzip"


def test_http_client_decodes_deflate_response():
    compressed = zlib.compress(b'{"ok":true}')

    def opener(request, timeout):
        return _FakeResponse(compressed, headers={"Content-Encoding": "deflate"})

    client = BrowserAuthenticatedHttpClient(
        _make_state(),
        allowed_domains=["example.com"],
        opener=opener,
    )

    body = client.get_text(
        "https://www.example.com/api/data",
        headers={"Accept-Encoding": "deflate"},
    )

    assert body == '{"ok":true}'


def test_http_client_rejects_unsupported_content_encoding():
    def opener(request, timeout):
        return _FakeResponse(
            b"encoded",
            headers={"Content-Encoding": "br"},
        )

    client = BrowserAuthenticatedHttpClient(
        _make_state(),
        allowed_domains=["example.com"],
        opener=opener,
    )

    with pytest.raises(ClientError, match="Unsupported HTTP content encoding: br"):
        client.get_text("https://www.example.com/api/data")


# ---------------------------------------------------------------------------
# H1 — Live CDP cookie read uses the persistent Chromium profile
#
# After the persistent-profile refactor, ``BrowserAuthState.from_config`` no
# longer reads a disk snapshot. It fetches cookies live from the
# running browser-harness daemon via ``config.get_browser().live_cookies()``.
# The persistent Chromium profile is the single source of truth.
# ---------------------------------------------------------------------------


def _cookie(**overrides):
    """Build a CDP-shaped cookie dict like browser-harness returns."""
    base = {
        "name": "session",
        "value": "abc",
        "domain": ".example.com",
        "path": "/",
        "expires": 9999999999.0,
    }
    base.update(overrides)
    return base


def test_from_config_reads_profile_cookie_json_before_browser():
    cookies = [
        {
            "name": "session",
            "value": "abc",
            "domain": ".example.com",
            "path": "/",
        },
    ]
    config = MagicMock()
    config._get.return_value = json.dumps(cookies)
    config.get_browser.side_effect = AssertionError("stored auth cookies should not open the browser")

    state = BrowserAuthState.from_config(config)

    config._get.assert_called_once_with("AUTH_COOKIES_JSON")
    assert state.cookies[0].name == "session"
    assert state.cookies[0].expires == -1.0


def test_from_config_reads_live_cookies_from_browser():
    """``BrowserAuthState.from_config`` must delegate to
    ``config.get_browser().live_cookies()`` and wrap the result in cookie
    entries — no disk snapshot read.
    """
    cookies = [
        _cookie(name="session", value="abc"),
        _cookie(name="hostonly", value="def", domain="www.example.com"),
    ]
    browser = MagicMock()
    browser.live_cookies.return_value = cookies
    config = MagicMock()
    config._get.return_value = None
    config.get_browser.return_value = browser
    config._tool_name = "tool"

    state = BrowserAuthState.from_config(config)

    browser.live_cookies.assert_called_once_with()
    browser.close.assert_called_once_with()
    assert [c.name for c in state.cookies] == ["session", "hostonly"]
    assert state.origins == ()


def test_from_config_raises_when_browser_has_no_session():
    """``live_cookies()`` returning ``[]`` means there is no session — that is
    fail-fast. No fallback to a stale on-disk snapshot.
    """
    browser = MagicMock()
    browser.live_cookies.return_value = []
    config = MagicMock()
    config._get.return_value = None
    config.get_browser.return_value = browser
    config._tool_name = "tool"

    with pytest.raises(BrowserAuthStateError, match="No browser session"):
        BrowserAuthState.from_config(config)
    browser.close.assert_called_once_with()


# ---------------------------------------------------------------------------
# RequestsRetryPolicy + request_with_retry
#
# The shared exponential-backoff-with-jitter retry for ``requests``-backed CLI
# clients (replaces the per-tool copies in nextdoor/grammarly).
# ---------------------------------------------------------------------------


class _RetryResponse:
    """Minimal stand-in for ``requests.Response`` for retry-policy tests."""

    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}


class _ScriptedSend:
    """A ``send`` callable that replays a scripted list of responses/exceptions."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _recording_sleep():
    sleeps: list[float] = []
    return sleeps, sleeps.append


# ---- Policy decision/delay logic --------------------------------------------


def test_calculate_delay_prefers_retry_after_capped_at_max():
    policy = RequestsRetryPolicy(base_delay=1.0, max_delay=30.0, jitter=0.5)
    # Retry-After wins and is honored verbatim when under the cap.
    assert policy.calculate_delay(5, retry_after=4.0) == 4.0
    # Retry-After is still capped at max_delay.
    assert policy.calculate_delay(0, retry_after=120.0) == 30.0


def test_calculate_delay_no_jitter_is_pure_exponential():
    policy = RequestsRetryPolicy(base_delay=2.0, max_delay=1000.0, jitter=0.0)
    assert policy.calculate_delay(0) == 2.0
    assert policy.calculate_delay(1) == 4.0
    assert policy.calculate_delay(2) == 8.0
    assert policy.calculate_delay(3) == 16.0


def test_calculate_delay_caps_at_max_delay():
    policy = RequestsRetryPolicy(base_delay=10.0, max_delay=15.0, jitter=0.0)
    assert policy.calculate_delay(10) == 15.0


def test_calculate_delay_jitter_stays_within_bounds():
    policy = RequestsRetryPolicy(base_delay=1.0, max_delay=1000.0, jitter=0.1)
    for attempt in range(6):
        base = policy.base_delay * (2 ** attempt)
        delay = policy.calculate_delay(attempt)
        assert base * 0.9 <= delay <= base * 1.1


def test_is_retryable_response():
    policy = RequestsRetryPolicy()
    for code in (429, 500, 502, 503, 504):
        assert policy.is_retryable_response(_RetryResponse(code)) is True
    for code in (200, 201, 400, 401, 403, 404):
        assert policy.is_retryable_response(_RetryResponse(code)) is False


def test_is_retryable_exception():
    policy = RequestsRetryPolicy()
    assert policy.is_retryable_exception(requests.exceptions.ConnectionError()) is True
    assert policy.is_retryable_exception(requests.exceptions.Timeout()) is True
    assert policy.is_retryable_exception(requests.exceptions.ChunkedEncodingError()) is True
    # Other RequestExceptions and unrelated errors are not retryable.
    assert policy.is_retryable_exception(requests.exceptions.HTTPError()) is False
    assert policy.is_retryable_exception(ValueError()) is False


def test_retry_after_seconds_parses_missing_and_invalid():
    policy = RequestsRetryPolicy()
    assert policy.retry_after_seconds(_RetryResponse(503, {"Retry-After": "7"})) == 7.0
    assert policy.retry_after_seconds(_RetryResponse(503, {})) is None
    # Non-numeric (e.g. an HTTP-date) is tolerated as "no hint", not a crash.
    assert policy.retry_after_seconds(_RetryResponse(503, {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})) is None


# ---- Driver loop ------------------------------------------------------------


def test_request_with_retry_returns_first_non_retryable_response():
    sleeps, sleep = _recording_sleep()
    send = _ScriptedSend([_RetryResponse(200)])
    policy = RequestsRetryPolicy(max_retries=3, base_delay=0)

    response = request_with_retry(send, policy, sleep=sleep)

    assert response.status_code == 200
    assert send.calls == 1
    assert sleeps == []


def test_request_with_retry_retries_status_then_succeeds():
    sleeps, sleep = _recording_sleep()
    send = _ScriptedSend([_RetryResponse(503), _RetryResponse(500), _RetryResponse(200)])
    policy = RequestsRetryPolicy(max_retries=3, base_delay=0, jitter=0)

    response = request_with_retry(send, policy, sleep=sleep)

    assert response.status_code == 200
    assert send.calls == 3
    assert len(sleeps) == 2  # slept before each of the two retries


def test_request_with_retry_retries_exception_then_succeeds():
    sleeps, sleep = _recording_sleep()
    send = _ScriptedSend([requests.exceptions.ConnectionError(), _RetryResponse(200)])
    policy = RequestsRetryPolicy(max_retries=2, base_delay=0, jitter=0)

    response = request_with_retry(send, policy, sleep=sleep)

    assert response.status_code == 200
    assert send.calls == 2
    assert len(sleeps) == 1


def test_request_with_retry_honors_retry_after_header():
    sleeps, sleep = _recording_sleep()
    send = _ScriptedSend([_RetryResponse(429, {"Retry-After": "3"}), _RetryResponse(200)])
    policy = RequestsRetryPolicy(max_retries=2, base_delay=99, jitter=0)

    request_with_retry(send, policy, sleep=sleep)

    # The server's Retry-After overrides the exponential base delay.
    assert sleeps == [3.0]


def test_request_with_retry_exhausts_retries_and_returns_last_response():
    sleeps, sleep = _recording_sleep()
    send = _ScriptedSend([_RetryResponse(503) for _ in range(4)])
    policy = RequestsRetryPolicy(max_retries=3, base_delay=0, jitter=0)

    response = request_with_retry(send, policy, sleep=sleep)

    assert response.status_code == 503  # final retryable response returned, not raised
    assert send.calls == 4  # 1 initial + 3 retries
    assert len(sleeps) == 3


def test_request_with_retry_raises_last_exception_when_all_attempts_fail():
    sleeps, sleep = _recording_sleep()
    final = requests.exceptions.Timeout("last")
    send = _ScriptedSend([requests.exceptions.ConnectionError(), final])
    policy = RequestsRetryPolicy(max_retries=1, base_delay=0, jitter=0)

    with pytest.raises(requests.exceptions.Timeout, match="last"):
        request_with_retry(send, policy, sleep=sleep)
    assert send.calls == 2


def test_request_with_retry_non_retryable_exception_propagates_without_retry():
    sleeps, sleep = _recording_sleep()
    send = _ScriptedSend([requests.exceptions.HTTPError("boom")])
    policy = RequestsRetryPolicy(max_retries=3, base_delay=0)

    with pytest.raises(requests.exceptions.HTTPError, match="boom"):
        request_with_retry(send, policy, sleep=sleep)
    assert send.calls == 1
    assert sleeps == []


def test_request_with_retry_max_retries_zero_makes_single_attempt():
    sleeps, sleep = _recording_sleep()
    send = _ScriptedSend([_RetryResponse(503)])
    policy = RequestsRetryPolicy(max_retries=0, base_delay=0)

    response = request_with_retry(send, policy, sleep=sleep)

    assert response.status_code == 503
    assert send.calls == 1
    assert sleeps == []
