"""Facebook's saved-account picker must be dismissed before the declarative login.

Live shape (2026-11-04): with a remembered account, /login renders
"<Name> / Continue / Use another profile" and no email input, so the shared
declarative login failed with "requires one visible username control".
"""
from cli_tools_shared.auth import BrowserAutomation

from facebook_cli.browser import SAVED_ACCOUNT_PICKER_SELECTOR, FacebookBrowser


class FakePage:
    def __init__(self, picker_state):
        self.picker_state = picker_state
        self.calls = []

    def evaluate(self, js, arg=None):
        self.calls.append(("evaluate", arg))
        return self.picker_state

    def keyboard_press(self, key):
        self.calls.append(("press", key))

    def wait_for_selector(self, selector, state=None, timeout=None):
        self.calls.append(("wait", selector, state))


def _browser(monkeypatch):
    submitted = []
    monkeypatch.setattr(
        BrowserAutomation, "_complete_noninteractive_login", lambda self, page: submitted.append(page)
    )
    browser = FacebookBrowser.__new__(FacebookBrowser)
    return browser, submitted


def test_picker_is_dismissed_with_keyboard_then_shared_login_runs(monkeypatch):
    browser, submitted = _browser(monkeypatch)
    page = FakePage("focused")

    browser._complete_noninteractive_login(page)

    assert page.calls == [
        ("evaluate", SAVED_ACCOUNT_PICKER_SELECTOR),
        ("press", "Enter"),
        ("wait", 'input[name="email"]', "visible"),
    ]
    assert submitted == [page]


def test_plain_login_form_goes_straight_to_shared_login(monkeypatch):
    browser, submitted = _browser(monkeypatch)
    page = FakePage("form")

    browser._complete_noninteractive_login(page)

    assert page.calls == [("evaluate", SAVED_ACCOUNT_PICKER_SELECTOR)]
    assert submitted == [page]


def test_picker_selector_targets_use_another_profile():
    assert SAVED_ACCOUNT_PICKER_SELECTOR == '[role="button"][aria-label="Use another profile"]'
