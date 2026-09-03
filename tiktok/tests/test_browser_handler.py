"""Unit tests for the TikTok headless login handler (mocked page + secrets).

These prove the handler choreography without a live TikTok login: it reads the
CLI-tools secret-manager credentials, fills the validated selectors, submits,
and raises a specific ``BrowserAutomationError`` for each post-submit blocker
(captcha, rate-limit, 2FA code) instead of looping into a generic timeout.
"""

from __future__ import annotations

import pytest

from cli_tools_shared.auth import BrowserAutomationError

from tiktok_cli import browser as browser_mod
from tiktok_cli.browser import (
    EMAIL_LOGIN_URL,
    PASSWORD_SELECTOR,
    SUBMIT_SELECTOR,
    USERNAME_SELECTOR,
    VERIFY_CODE_SELECTOR,
    _tiktok_login_handler,
)


class _FakeElement:
    def __init__(self, visible: bool = True):
        self._visible = visible
        self.filled = None
        self.clicked = False

    def is_visible(self):
        return self._visible

    def fill(self, text: str):
        self.filled = text

    def click(self):
        self.clicked = True


class _FakeLocator:
    def __init__(self, elements):
        self._elements = elements

    def all(self):
        return list(self._elements)


class _FakePage:
    def __init__(self, *, issue=None, fields=None, code_field=False):
        self._issue = issue
        self._fields = fields if fields is not None else {
            USERNAME_SELECTOR: True,
            PASSWORD_SELECTOR: True,
            SUBMIT_SELECTOR: True,
        }
        self._code_field = code_field
        self.goto_urls = []
        self.waits = []

    def goto(self, url: str):
        self.goto_urls.append(url)

    def wait_for_timeout(self, ms: int):
        self.waits.append(ms)

    def locator(self, selector: str):
        if selector == VERIFY_CODE_SELECTOR:
            return _FakeLocator([_FakeElement()] if self._code_field else [])
        return _FakeLocator([_FakeElement()] if self._fields.get(selector) else [])

    def evaluate(self, js: str, arg=None):
        return self._issue


class _FakeBrowser:
    def __init__(self, authed: bool = False):
        self._authed = authed

    def _check_auth(self, page) -> bool:
        return self._authed


def _handler(monkeypatch, *, issue=None, authed=False, username=None, password=None, code_field=False):
    monkeypatch.setattr(browser_mod, "read_cli_tool_secret", lambda name: {
        "tiktok-username": username,
        "tiktok-password": password,
    }.get(name))
    page = _FakePage(issue=issue, code_field=code_field)
    browser = _FakeBrowser(authed=authed)
    return browser, page


def test_handler_navigates_to_email_form_and_submits(monkeypatch):
    browser, page = _handler(
        monkeypatch, issue=None, authed=True, username="u@example.com", password="pw"
    )
    _tiktok_login_handler(browser, page)
    assert EMAIL_LOGIN_URL in page.goto_urls
    assert page.waits  # settle + poll waits were issued


def test_handler_raises_on_missing_username(monkeypatch):
    browser, page = _handler(monkeypatch, username=None, password="pw")
    with pytest.raises(BrowserAutomationError, match="username"):
        _tiktok_login_handler(browser, page)


def test_handler_raises_on_missing_password(monkeypatch):
    browser, page = _handler(monkeypatch, username="u@example.com", password=None)
    with pytest.raises(BrowserAutomationError, match="password"):
        _tiktok_login_handler(browser, page)


def test_handler_raises_when_form_not_rendered(monkeypatch):
    monkeypatch.setattr(browser_mod, "read_cli_tool_secret", lambda name: "x")
    page = _FakePage(issue=None, fields={})  # no fields visible
    browser = _FakeBrowser()
    with pytest.raises(BrowserAutomationError, match="did not render"):
        _tiktok_login_handler(browser, page)


def test_handler_raises_on_rate_limit(monkeypatch):
    browser, page = _handler(
        monkeypatch, issue="rate_limit", username="u@example.com", password="pw"
    )
    with pytest.raises(BrowserAutomationError, match="rate-limiting"):
        _tiktok_login_handler(browser, page)


def test_handler_raises_on_captcha(monkeypatch):
    browser, page = _handler(
        monkeypatch, issue="captcha", username="u@example.com", password="pw"
    )
    with pytest.raises(BrowserAutomationError, match="CAPTCHA"):
        _tiktok_login_handler(browser, page)


def test_handler_raises_on_bad_credentials(monkeypatch):
    browser, page = _handler(
        monkeypatch, issue="bad_credentials", username="u@example.com", password="pw"
    )
    with pytest.raises(BrowserAutomationError, match="rejected"):
        _tiktok_login_handler(browser, page)


def test_handler_raises_on_verification_code(monkeypatch):
    browser, page = _handler(
        monkeypatch, issue=None, code_field=True, username="u@example.com", password="pw"
    )
    with pytest.raises(BrowserAutomationError, match="verification code"):
        _tiktok_login_handler(browser, page)
