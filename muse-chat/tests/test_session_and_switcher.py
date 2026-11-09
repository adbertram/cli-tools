"""Expired-session self-heal, live auth status, and chat-switcher settling."""

from __future__ import annotations

import sys

import pytest

from cli_tools_shared.auth import AuthResult, BrowserAutomationError
from cli_tools_shared.exceptions import CredentialError
from muse_chat_cli import client as client_module
from muse_chat_cli import main as main_module
from muse_chat_cli.browser import (
    AUTH_STATE_JS,
    COMPOSER_SELECTOR,
    SAVED_ACCOUNT_SELECTOR,
    MuseChatBrowser,
    MuseChatSessionBrowser,
    _log_in_with_saved_account,
)
from muse_chat_cli.client import SIDE_THREAD_ROWS_JS, MuseChatClient


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def count(self):
        return self.page.counts.get(self.selector, 0)

    @property
    def first(self):
        return self

    def click(self):
        self.page.clicked.append(self.selector)

    def is_visible(self, timeout=None):
        return self.page.counts.get(self.selector, 0) > 0


class FakePage:
    def __init__(self, auth_state="", counts=None, rows=(), url="https://muse.ai/"):
        self.auth_state = auth_state
        self.counts = counts or {}
        self.rows = list(rows)
        self.url = url
        self.clicked = []
        self.waited_for = []
        self.clock = 0.0

    def evaluate(self, script, *_args):
        if script == AUTH_STATE_JS:
            return self.auth_state
        if script == SIDE_THREAD_ROWS_JS:
            return self.rows.pop(0) if len(self.rows) > 1 else self.rows[0]
        raise AssertionError(f"unexpected script: {script[:40]}")

    def locator(self, selector):
        return FakeLocator(self, selector)

    def wait_for_selector(self, selector, timeout=None):
        if not self.counts.get(selector, 1):
            raise TimeoutError(selector)
        self.waited_for.append(selector)

    def wait_for_timeout(self, milliseconds):
        self.clock += milliseconds / 1000


# --- saved-account login handler -------------------------------------------


def test_handler_clicks_saved_facebook_account_and_waits_for_composer():
    page = FakePage(auth_state="login_pane", counts={SAVED_ACCOUNT_SELECTOR: 1})
    _log_in_with_saved_account(None, page)
    assert page.clicked == [SAVED_ACCOUNT_SELECTOR]
    assert page.waited_for == [SAVED_ACCOUNT_SELECTOR, COMPOSER_SELECTOR]


def test_handler_without_saved_account_fails_without_typing_anything():
    page = FakePage(auth_state="login_pane", counts={SAVED_ACCOUNT_SELECTOR: 0})
    with pytest.raises(BrowserAutomationError, match="no saved account"):
        _log_in_with_saved_account(None, page)
    assert page.clicked == []


def test_handler_is_a_no_op_when_already_signed_in():
    page = FakePage(auth_state="", counts={SAVED_ACCOUNT_SELECTOR: 1})
    _log_in_with_saved_account(None, page)
    assert page.clicked == []


def test_only_command_browser_resumes_headlessly():
    assert MuseChatBrowser.AUTH_LOGIN_HANDLER is None, "auth login must stay a headed login"
    assert MuseChatSessionBrowser.AUTH_LOGIN_HANDLER is not None


# --- auth status live check ------------------------------------------------


@pytest.mark.parametrize(
    ("auth_state", "expected"),
    [("", True), ("login_pane", False), ("no_composer", False)],
)
def test_auth_check_requires_composer_and_no_login_pane(auth_state, expected):
    browser = MuseChatBrowser.__new__(MuseChatBrowser)
    assert browser._check_auth(FakePage(auth_state=auth_state)) is expected


def test_auth_check_rejects_visible_login_pane_even_if_probe_passes():
    browser = MuseChatBrowser.__new__(MuseChatBrowser)
    page = FakePage(counts={MuseChatBrowser.AUTH_LOGIN_FORM_SELECTOR: 1})
    assert browser._check_auth(page) is False


# --- client self-heal ------------------------------------------------------


class FakeBrowser:
    def __init__(self, pages, outcome):
        self.pages = list(pages)
        self.outcome = outcome
        self.refreshes = 0
        self.urls = []

    def get_page(self, url):
        self.urls.append(url)
        return self.pages.pop(0)

    def ensure_fresh_session(self):
        self.refreshes += 1
        return self.outcome


def client_with(browser):
    client = MuseChatClient.__new__(MuseChatClient)
    client._browser = browser
    return client


def test_open_page_resumes_expired_session_and_reopens_url():
    healed = FakePage()
    browser = FakeBrowser(
        [FakePage(auth_state="login_pane"), healed],
        AuthResult(authenticated=True, live_check=True, refreshed=True),
    )
    assert client_with(browser)._open_page("https://muse.ai/") is healed
    assert browser.refreshes == 1
    assert browser.urls == ["https://muse.ai/", "https://muse.ai/"]


def test_open_page_skips_refresh_for_live_session():
    page = FakePage()
    browser = FakeBrowser([page], AuthResult(authenticated=False, live_check=True))
    assert client_with(browser)._open_page("https://muse.ai/") is page
    assert browser.refreshes == 0


def test_open_page_reports_auth_error_when_resume_fails():
    browser = FakeBrowser(
        [FakePage(auth_state="login_pane")],
        AuthResult(authenticated=False, live_check=True, reason="Muse is signed out and shows no saved account"),
    )
    with pytest.raises(CredentialError, match="muse-chat auth login"):
        client_with(browser)._open_page("https://muse.ai/")


def test_auth_error_exits_2(monkeypatch, capsys):
    def expired(_self, limit=100):
        raise CredentialError("Muse session expired. Run 'muse-chat auth login', then retry.")

    monkeypatch.setattr(MuseChatClient, "list_chats", expired)
    monkeypatch.setattr(MuseChatClient, "close", lambda _self: None)
    monkeypatch.setattr(sys, "argv", ["muse-chat", "chat", "list"])
    with pytest.raises(SystemExit) as exit_info:
        main_module.main()
    assert exit_info.value.code == 2
    assert "Run 'muse-chat auth login'" in capsys.readouterr().err


# --- chat switcher settling ------------------------------------------------


SIDE_ROWS = [{"index": i, "title": f"Side {i}"} for i in range(10)]


@pytest.fixture
def clocked(monkeypatch):
    def install(page):
        monkeypatch.setattr(client_module.time, "monotonic", lambda: page.clock)
        return page
    return install


def test_switcher_waits_past_slow_render_for_side_rows(clocked):
    # Panel renders after ~400ms, longer than the old fixed 300ms sleep.
    page = clocked(FakePage(rows=[None, None, None, None, SIDE_ROWS]))
    assert MuseChatClient._open_switcher(page) == SIDE_ROWS


def test_switcher_waits_for_partial_rows_to_stabilize(clocked):
    page = clocked(FakePage(rows=[None, SIDE_ROWS[:3], SIDE_ROWS[:3], SIDE_ROWS]))
    assert MuseChatClient._open_switcher(page) == SIDE_ROWS


def test_switcher_returns_no_side_rows_when_account_has_none(clocked):
    page = clocked(FakePage(rows=[None, []]))
    assert MuseChatClient._open_switcher(page) == []


def test_switcher_that_never_opens_is_an_error(clocked):
    page = clocked(FakePage(rows=[None]))
    with pytest.raises(client_module.ClientError, match="did not open"):
        MuseChatClient._open_switcher(page)
