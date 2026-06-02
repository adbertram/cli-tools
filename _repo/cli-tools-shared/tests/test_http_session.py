from __future__ import annotations

import json
import gzip
import zlib
from unittest.mock import MagicMock

import pytest

from cli_tools_shared.http_session import (
    BrowserAuthState,
    BrowserAuthStateError,
    BrowserAuthenticatedHttpClient,
    BrowserCookie,
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
