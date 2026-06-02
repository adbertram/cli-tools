"""Unit tests for the Apple purchase-history client and auth capture."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from apple_cli.auth_capture import (
    APPLE_CODE_TIMEOUT_SECONDS,
    capture_request_context_from_page,
    _detect_apple_auth_stage,
    _enter_apple_verification_code,
    _prompt_for_apple_verification_code,
    _request_text_message_code,
    _wait_for_apple_interactive_auth,
)
from apple_cli.client import AppleClient
from apple_cli.config import Config
from cli_tools_shared.auth import BrowserAutomationError
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError

from .test_parsers import _sample_page_one, _sample_page_two


class _FakeConfig:
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]

    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.request_context_path = storage_dir / "apple-reportaproblem-request-context.json"
        self._browser = _FakeBrowser()

    def get_profile_data_dir(self) -> Path:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        return self.storage_dir

    def get_browser(self):
        return self._browser


class _FakeBrowser:
    def close(self) -> None:
        return None


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _CookieJar:
    def __init__(self):
        self._cookies: dict[tuple[str, str, str], str] = {}

    def set(self, name: str, value: str, domain: str, path: str) -> None:
        self._cookies[(name, domain, path)] = value

    def get(self, name: str, domain: str, path: str) -> str | None:
        return self._cookies.get((name, domain, path))


class _FakeSession:
    def __init__(self, pages: list[dict]):
        self.headers = {}
        self.cookies = _CookieJar()
        self._pages = list(pages)
        self.calls: list[dict] = []

    def post(self, _url: str, *, json: dict, timeout: int):
        self.calls.append({"json": json, "timeout": timeout})
        return _FakeResponse(self._pages.pop(0))

    def close(self) -> None:
        return None


class _FakePage:
    def __init__(self, *, drain_batches: list[list[dict]], cookies: list[dict], token: str):
        self._drain_batches = [list(batch) for batch in drain_batches]
        self._cookies = list(cookies)
        self._token = token
        self.goto_calls: list[str] = []
        self.wait_for_network_idle_calls: list[tuple[float, int]] = []

    def drain_events(self):
        if not self._drain_batches:
            return []
        return self._drain_batches.pop(0)

    def goto(self, url: str) -> None:
        self.goto_calls.append(url)

    def wait_for_network_idle(self, timeout: float, idle_ms: int) -> bool:
        self.wait_for_network_idle_calls.append((timeout, idle_ms))
        return True

    def evaluate(self, _js: str):
        return self._token

    def cookie_list(self):
        return list(self._cookies)


class _FakeAuthPage:
    def __init__(self):
        self.wait_for_timeout_calls: list[int] = []
        self.frame_calls: list[dict | None] = []
        self.frame_results: list[object] = []
        self.typed_values: list[str] = []

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_for_timeout_calls.append(ms)

    def evaluate_in_iframe(self, _url_substr, _js, arg=None):
        self.frame_calls.append(arg)
        if self.frame_results:
            return self.frame_results.pop(0)
        return None

    def type_text(self, text: str) -> None:
        self.typed_values.append(text)


class _FakeAuthBrowser:
    LOGIN_TIMEOUT = 5

    def __init__(self):
        self.entered_codes: list[str] = []

    def _check_auth(self, _page) -> bool:
        return bool(self.entered_codes)


class _FakePromptInput(StringIO):
    def isatty(self) -> bool:
        return True


def _request_context_payload() -> dict:
    return {
        "dsid": "188158362",
        "headers": {
            "accept-language": "en-US,en;q=0.9",
            "x-apple-xsrf-token": "token-123",
            "x-apple-rap2-api": "3.0.0",
            "content-length": "999",
        },
        "cookies": [
            {"name": "selfserv_toru", "value": "cookie-a", "domain": "reportaproblem.apple.com", "path": "/api"},
            {"name": "user-context", "value": "cookie-b", "domain": "reportaproblem.apple.com", "path": "/api"},
            {"name": "dslang", "value": "US-EN", "domain": ".apple.com", "path": "/"},
            {"name": "geo", "value": "US", "domain": ".apple.com", "path": "/"},
            {"name": "site", "value": "USA", "domain": ".apple.com", "path": "/"},
            {"name": "myacinfo", "value": "cookie-c", "domain": ".apple.com", "path": "/"},
            {"name": "dqsid", "value": "cookie-d", "domain": "reportaproblem.apple.com", "path": "/"},
        ],
    }


def _capture_events() -> list[dict]:
    return [
        {
            "method": "Network.requestWillBeSent",
            "params": {
                "requestId": "1",
                "request": {
                    "url": "https://reportaproblem.apple.com/api/purchase/search",
                    "method": "POST",
                    "headers": {
                        "Accept": "application/json, text/plain, */*",
                        "Content-Type": "application/json",
                        "Referer": "https://reportaproblem.apple.com/",
                        "x-apple-rap2-api": "3.0.0",
                        "x-apple-xsrf-token": "token-123",
                        "content-length": "27",
                    },
                    "postData": '{"dsid":"188158362"}',
                },
            },
        }
    ]


def _make_client(monkeypatch, tmp_path: Path) -> tuple[AppleClient, _FakeConfig]:
    fake_config = _FakeConfig(tmp_path)
    monkeypatch.setattr("apple_cli.client.get_config", lambda profile=None: fake_config)
    monkeypatch.setenv("CACHE_ENABLED", "false")
    return AppleClient(), fake_config


def test_load_request_context_reads_profile_file(monkeypatch, tmp_path):
    client, config = _make_client(monkeypatch, tmp_path)
    config.request_context_path.write_text(json.dumps(_request_context_payload()), encoding="utf-8")

    assert client._load_request_context()["dsid"] == "188158362"


def test_load_request_context_requires_login_capture(monkeypatch, tmp_path):
    client, _config = _make_client(monkeypatch, tmp_path)

    with pytest.raises(ClientError, match="Run 'apple auth login'"):
        client._load_request_context()


def test_build_session_uses_captured_headers_and_cookies(monkeypatch, tmp_path):
    client, _config = _make_client(monkeypatch, tmp_path)

    session = client._build_session(
        _request_context_payload()["headers"],
        _request_context_payload()["cookies"],
    )

    assert session.headers["x-apple-xsrf-token"] == "token-123"
    assert session.headers["x-apple-rap2-api"] == "3.0.0"
    assert session.headers["Accept"] == "application/json, text/plain, */*"
    assert session.headers["accept-language"] == "en-US,en;q=0.9"
    assert "content-length" not in {key.lower() for key in session.headers}
    assert session.cookies.get("myacinfo", domain=".apple.com", path="/") == "cookie-c"
    assert session.cookies.get("dqsid", domain="reportaproblem.apple.com", path="/") == "cookie-d"


def test_list_all_purchase_records_uses_dsid_first_page_then_batch_id(monkeypatch, tmp_path):
    client, _config = _make_client(monkeypatch, tmp_path)
    fake_session = _FakeSession([_sample_page_one(), _sample_page_two()])

    monkeypatch.setattr(client, "_load_request_context", _request_context_payload)
    monkeypatch.setattr(client, "_build_session", lambda headers, cookies: fake_session)

    records = client._list_all_purchase_records()

    assert len(records) == 4
    assert fake_session.calls == [
        {"json": {"dsid": "188158362"}, "timeout": 30},
        {"json": {"batchId": "next-batch-1", "dsid": "188158362"}, "timeout": 30},
    ]


def test_list_purchases_stops_after_limit_without_fetching_next_page(monkeypatch, tmp_path):
    client, _config = _make_client(monkeypatch, tmp_path)
    fake_session = _FakeSession([_sample_page_one(), _sample_page_two()])

    monkeypatch.setattr(client, "_load_request_context", _request_context_payload)
    monkeypatch.setattr(client, "_build_session", lambda headers, cookies: fake_session)

    records = client.list_purchases(limit=1)

    assert len(records) == 1
    assert fake_session.calls == [
        {"json": {"dsid": "188158362"}, "timeout": 30},
    ]


def test_get_purchase_line_stops_after_first_matching_page(monkeypatch, tmp_path):
    client, _config = _make_client(monkeypatch, tmp_path)
    fake_session = _FakeSession([_sample_page_one(), _sample_page_two()])

    monkeypatch.setattr(client, "_load_request_context", _request_context_payload)
    monkeypatch.setattr(client, "_build_session", lambda headers, cookies: fake_session)

    record = client.get_purchase_line("purchase-1:item-2")

    assert record["id"] == "purchase-1:item-2"
    assert fake_session.calls == [
        {"json": {"dsid": "188158362"}, "timeout": 30},
    ]


def test_auth_login_capture_writes_profile_request_context(tmp_path):
    config = _FakeConfig(tmp_path)
    page = _FakePage(
        drain_batches=[[], _capture_events()],
        cookies=_request_context_payload()["cookies"],
        token="token-123",
    )

    capture_request_context_from_page(page, config)

    saved = json.loads(config.request_context_path.read_text(encoding="utf-8"))
    assert saved["dsid"] == "188158362"
    assert saved["headers"]["x-apple-xsrf-token"] == "token-123"
    assert saved["headers"]["x-apple-rap2-api"] == "3.0.0"
    assert "content-length" not in saved["headers"]
    assert [cookie["name"] for cookie in saved["cookies"]] == [
        "selfserv_toru",
        "user-context",
        "dslang",
        "geo",
        "site",
        "myacinfo",
        "dqsid",
    ]
    assert page.goto_calls == ["https://reportaproblem.apple.com/?s=6"]
    assert page.wait_for_network_idle_calls == [(20.0, 750)]


def test_auth_login_capture_uses_buffered_purchase_request_without_navigation(tmp_path):
    config = _FakeConfig(tmp_path)
    page = _FakePage(
        drain_batches=[_capture_events()],
        cookies=_request_context_payload()["cookies"],
        token="token-123",
    )

    capture_request_context_from_page(page, config)

    saved = json.loads(config.request_context_path.read_text(encoding="utf-8"))
    assert saved["dsid"] == "188158362"
    assert page.goto_calls == []
    assert page.wait_for_network_idle_calls == []


def test_auth_login_capture_fails_when_purchase_request_missing(tmp_path):
    config = _FakeConfig(tmp_path)
    page = _FakePage(
        drain_batches=[[], []],
        cookies=_request_context_payload()["cookies"],
        token="token-123",
    )

    with pytest.raises(BrowserAutomationError, match="did not observe the initial purchase-search POST request"):
        capture_request_context_from_page(page, config)


def test_request_text_message_code_opens_fallback_then_selects_text_option():
    page = _FakeAuthPage()
    page.frame_results = [
        "Enter Verification Code. Didn't Get a Code?",
        False,
        True,
        False,
        False,
        True,
        True,
    ]

    assert _request_text_message_code(page) is True
    calls = [call for call in page.frame_calls if isinstance(call, dict)]
    assert calls[0]["include"] == [r"didn.t get a code", r"can.t get to your devices"]
    assert calls[1]["include"] == [r"text code to"]
    assert calls[1]["exclude"] == [
        r"voice",
        r"call",
        r"recover",
        r"recovery",
        r"can.t use",
        r"don.t have access",
    ]


def test_detect_apple_auth_stage_identifies_sms_options():
    page = _FakeAuthPage()
    page.frame_results = [
        "Choose a trusted phone number. Text code to (***) ***-1234",
        False,
        False,
        True,
        False,
    ]

    assert _detect_apple_auth_stage(page)["stage"] == "sms_options"


def test_detect_apple_auth_stage_identifies_sms_code_prompt():
    page = _FakeAuthPage()
    page.frame_results = [
        "A verification code was sent as a message to your trusted phone number.",
        False,
        True,
        False,
        True,
    ]

    assert _detect_apple_auth_stage(page)["stage"] == "sms_code"


def test_request_text_message_code_returns_false_without_fallback_button():
    page = _FakeAuthPage()
    page.frame_results = [
        "Enter Verification Code.",
        False,
        True,
        False,
        False,
        False,
        False,
    ]

    assert _request_text_message_code(page) is False


def test_prompt_for_apple_verification_code_requires_six_digits(monkeypatch):
    monkeypatch.setattr("sys.stdin", _FakePromptInput("bad\n636617\n"))
    monkeypatch.setattr("apple_cli.auth_capture.select.select", lambda r, _w, _e, _timeout: (r, [], []))

    assert _prompt_for_apple_verification_code("text message", APPLE_CODE_TIMEOUT_SECONDS) == "636617"


def test_prompt_for_apple_verification_code_times_out(monkeypatch):
    monkeypatch.setattr("sys.stdin", _FakePromptInput(""))
    monkeypatch.setattr("apple_cli.auth_capture.select.select", lambda _r, _w, _e, _timeout: ([], [], []))

    with pytest.raises(BrowserAutomationError, match="Timed out waiting for the Apple verification code"):
        _prompt_for_apple_verification_code("trusted Apple device", APPLE_CODE_TIMEOUT_SECONDS)


def test_enter_apple_verification_code_requires_visible_code_input():
    class Page:
        def evaluate_in_iframe(self, _url_substr, _js, _arg=None):
            return False

        def type_text(self, text: str) -> None:
            raise AssertionError("type_text should not run when no verifier input exists")

    with pytest.raises(BrowserAutomationError, match="verification-code input was not found"):
        _enter_apple_verification_code(Page(), "636617")


def test_enter_apple_verification_code_focuses_iframe_then_types_code():
    page = _FakeAuthPage()
    page.frame_results = [True]

    _enter_apple_verification_code(page, "636617")

    assert page.typed_values == ["636617"]


def test_wait_for_apple_auth_prefers_text_delivery_and_enters_code(monkeypatch):
    page = _FakeAuthPage()
    browser = _FakeAuthBrowser()
    prompt_calls: list[tuple[str, int]] = []

    stages = iter(
        [
            {
                "stage": "trusted_device_code",
                "invalid_code": False,
                "body_text": "Enter Verification Code. Didn't Get a Code?",
            },
            {
                "stage": "sms_code",
                "invalid_code": False,
                "body_text": "Verification code sent as a message to your trusted phone number.",
            },
        ]
    )
    monkeypatch.setattr("apple_cli.auth_capture._detect_apple_auth_stage", lambda _page: next(stages))
    monkeypatch.setattr("apple_cli.auth_capture._request_text_message_code", lambda _page: True)

    prompt_values = iter(["sms", "636617"])

    def fake_prompt(code_source: str, timeout_seconds: int, **_kwargs) -> str:
        prompt_calls.append((code_source, timeout_seconds))
        return next(prompt_values)

    def fake_enter(_page, code: str) -> None:
        browser.entered_codes.append(code)

    monkeypatch.setattr("apple_cli.auth_capture._prompt_for_apple_verification_code", fake_prompt)
    monkeypatch.setattr("apple_cli.auth_capture._enter_apple_verification_code", fake_enter)

    _wait_for_apple_interactive_auth(browser, page)

    assert browser.entered_codes == ["636617"]
    assert prompt_calls == [
        ("trusted Apple device", APPLE_CODE_TIMEOUT_SECONDS),
        ("text message to the trusted phone number", APPLE_CODE_TIMEOUT_SECONDS),
    ]


def test_wait_for_apple_auth_stops_on_locked_account(monkeypatch):
    page = _FakeAuthPage()

    class Browser:
        LOGIN_TIMEOUT = 5

        def _check_auth(self, _page) -> bool:
            return False

    monkeypatch.setattr(
        "apple_cli.auth_capture._detect_apple_auth_stage",
        lambda _page: {
            "stage": "waiting",
            "invalid_code": False,
            "body_text": "This Apple Account has been locked for security reasons.",
        },
    )

    with pytest.raises(BrowserAutomationError, match="locked, not active, or disabled"):
        _wait_for_apple_interactive_auth(Browser(), page)


def test_request_context_path_defaults_to_profile_storage():
    config = object.__new__(Config)
    profile_dir = Path("/tmp/apple-profile-test")
    config.get_profile_data_dir = lambda: profile_dir
    assert config.request_context_path == profile_dir / "apple-reportaproblem-request-context.json"
