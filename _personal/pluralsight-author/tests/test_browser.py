import re
import os

import pytest

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
from cli_tools_shared.browser.driver import BrowserHarnessService
from cli_tools_shared.browser._elements import _selector_js

from pluralsight_author_cli.browser import PluralsightAuthorBrowser, PluralsightAuthorKitBrowser
from pluralsight_author_cli.config import AUTH_METHOD_AUTHOR_KIT, AUTH_METHOD_OPPORTUNITIES, Config


class FakeConfig:
    def __init__(self, browser_data_dir):
        self.browser_data_dir = browser_data_dir

    def get_browser_data_dir(self):
        return self.browser_data_dir


def test_pluralsight_author_uses_common_profile_only_auth_validation(tmp_path):
    browser = PluralsightAuthorBrowser(FakeConfig(tmp_path / "browser-data"))

    assert type(browser)._on_authenticated is BrowserAutomation._on_authenticated


class DashboardPage:
    def __init__(self, url, title, body=""):
        self.url = url
        self.title = title
        self.body = body

    def evaluate(self, script):
        if script == "document.title":
            return self.title
        assert "innerText" in script
        return self.body


def test_dashboard_submit_selectors_use_driver_supported_text_filter():
    for selector, label in (
        (PluralsightAuthorBrowser.AUTH_LOGIN_USERNAME_SUBMIT_SELECTOR, "Continue"),
        (PluralsightAuthorBrowser.AUTH_LOGIN_SUBMIT_SELECTOR, "Sign In"),
    ):
        compiled = _selector_js(selector)
        assert ":has-text(" not in compiled
        assert "button[type=submit]" in compiled
        assert label in compiled


@pytest.mark.skipif(
    os.environ.get("PLURALSIGHT_AUTHOR_DRIVER_TEST") != "1",
    reason="opt-in headless browser integration test",
)
def test_dashboard_submit_selectors_resolve_with_driver_and_decoys(tmp_path):
    from urllib.parse import quote

    browser = PluralsightAuthorBrowser(FakeConfig(tmp_path / "browser-data"))
    service = BrowserHarnessService("pluralsight-author-selector-test")
    html = ('<input id="email-address"><input id="password" type="password">'
            '<button type="submit">Continue</button><button type="submit">Sign In</button>'
            '<button type="submit">Other action</button>')
    try:
        service.browser_open("data:text/html," + quote(html), headed=False,
                             persistent_profile_dir=tmp_path / "profile")
        for selector in (browser.AUTH_LOGIN_USERNAME_SELECTOR,
                         browser.AUTH_LOGIN_USERNAME_SUBMIT_SELECTOR,
                         browser.AUTH_LOGIN_PASSWORD_SELECTOR,
                         browser.AUTH_LOGIN_SUBMIT_SELECTOR):
            assert service.locator(selector).count() == 1
    finally:
        service.browser_close()


@pytest.mark.parametrize("title,body", [
    ("🐴 Just a moment...", ""),
    ("Pluralsight", "One more step. Please complete the security check to access the site. Verify you are human"),
])
def test_dashboard_cloud_verification_aborts_before_login_classification(tmp_path, monkeypatch, title, body):
    browser = PluralsightAuthorBrowser(FakeConfig(tmp_path / "browser-data"))
    page = DashboardPage("https://app.pluralsight.com/id", title, body)
    monkeypatch.setattr(BrowserAutomation, "_navigate_page", lambda self, url=None: page)
    with pytest.raises(BrowserAutomationError, match="Pluralsight cloud verification"):
        browser.get_page(browser.AUTH_CHECK_URL)

    browser.config.has_saved_session = lambda: True
    monkeypatch.setattr(browser, "close", lambda: None)
    result = browser.test_session()
    assert result["authenticated"] is False
    assert "Pluralsight cloud verification" in result["error"]
    assert "cannot be resolved automatically" in result["error"]


@pytest.mark.parametrize("url,title,expected", [
    ("https://app.pluralsight.com/id?redirectTo=x", "Sign In | Pluralsight", False),
    ("https://app.pluralsight.com/author-home/opportunities/all", "Opportunities", True),
    ("https://app.pluralsight.com/other", "Other", False),
    ("https://elsewhere.example/author-home/opportunities/all", "Other", False),
    ("https://app.pluralsight.com.evil.example/author-home/opportunities/all", "Other", False),
])
def test_dashboard_auth_requires_protected_url(tmp_path, url, title, expected):
    browser = PluralsightAuthorBrowser(FakeConfig(tmp_path / "browser-data"))
    page = DashboardPage(url, title)
    assert browser._classify_page_interstitial(page) is None
    assert browser._check_auth(page) is expected


def test_pluralsight_author_kit_uses_common_profile_only_auth_validation(tmp_path):
    browser = PluralsightAuthorKitBrowser(FakeConfig(tmp_path / "browser-data"))

    assert type(browser)._on_authenticated is BrowserAutomation._on_authenticated


def test_pluralsight_author_kit_declares_totp_challenge(tmp_path):
    browser = PluralsightAuthorKitBrowser(FakeConfig(tmp_path / "browser-data"))

    assert browser.AUTH_LOGIN_TOTP_SELECTOR == "#authcode"
    assert browser.AUTH_LOGIN_TOTP_SUBMIT_SELECTOR == "#wp-submit"
    assert browser.AUTH_LOGIN_TOTP_SECRET == "pluralsight-author-totp-secret"


def test_pluralsight_author_kit_success_url_allows_query_and_fragment(tmp_path):
    browser = PluralsightAuthorKitBrowser(FakeConfig(tmp_path / "browser-data"))
    pattern = re.compile(browser.AUTH_SUCCESS_URL)

    assert pattern.search("https://authors.pluralsight.com/icon-library/")
    assert pattern.search("https://authors.pluralsight.com/icon-library")
    assert pattern.search("https://authors.pluralsight.com/icon-library/?loggedin=true")
    assert pattern.search("https://authors.pluralsight.com/icon-library/#icons")
    assert not pattern.search("https://authors.pluralsight.com/wp-login.php")


def test_config_selects_browser_by_profile_auth_type(tmp_path):
    config = Config.__new__(Config)
    config.browser_data_dir = tmp_path / "browser-data"
    config.get_browser_data_dir = lambda: config.browser_data_dir
    config._active_auth_method = lambda: AUTH_METHOD_OPPORTUNITIES
    assert isinstance(Config.get_browser(config), PluralsightAuthorBrowser)

    config._active_auth_method = lambda: AUTH_METHOD_AUTHOR_KIT
    assert isinstance(Config.get_browser(config), PluralsightAuthorKitBrowser)
