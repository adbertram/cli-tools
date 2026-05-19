from cli_tools_shared.auth import BrowserAutomation

from pluralsight_author_cli.browser import PluralsightAuthorBrowser


class FakeConfig:
    def __init__(self, browser_data_dir):
        self.browser_data_dir = browser_data_dir

    def get_browser_data_dir(self):
        return self.browser_data_dir


def test_pluralsight_author_uses_common_profile_only_auth_validation(tmp_path):
    browser = PluralsightAuthorBrowser(FakeConfig(tmp_path / "browser-data"))

    assert type(browser)._on_authenticated is BrowserAutomation._on_authenticated
