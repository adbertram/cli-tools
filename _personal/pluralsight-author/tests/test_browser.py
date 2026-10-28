import re

from cli_tools_shared.auth import BrowserAutomation

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
