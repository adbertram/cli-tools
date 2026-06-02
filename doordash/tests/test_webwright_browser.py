"""DoorDash Webwright browser regressions."""

from cli_tools_shared import auth as auth_module
from cli_tools_shared.auth import WebwrightBrowserAutomation

from doordash_cli.browser import DoorDashBrowser


class _Config:
    _tool_name = "doordash"

    def get_active_profile_name(self):
        return "default"


def test_doordash_browser_uses_webwright_service(monkeypatch):
    from cli_tools_shared.browser import webwright as webwright_module

    class _FakeService:
        instances = []

        def __init__(
            self,
            session,
            *,
            browser_mode="local_persistent",
            timeout=60,
            local_cdp_url=None,
            local_cdp_executable=None,
            local_cdp_new_page=None,
            local_cdp_close_page_on_exit=None,
            local_cdp_close_started_browser_on_exit=None,
        ):
            self.session = session
            self.browser_mode = browser_mode
            self.timeout = timeout
            self.local_cdp_url = local_cdp_url
            self.local_cdp_executable = local_cdp_executable
            self.local_cdp_new_page = local_cdp_new_page
            self.local_cdp_close_page_on_exit = local_cdp_close_page_on_exit
            self.local_cdp_close_started_browser_on_exit = (
                local_cdp_close_started_browser_on_exit
            )
            _FakeService.instances.append(self)

    monkeypatch.setattr(webwright_module, "WebwrightBrowserService", _FakeService)

    browser = DoorDashBrowser(_Config())
    service = browser._get_service()

    assert isinstance(browser, WebwrightBrowserAutomation)
    assert service.session == auth_module._safe_daemon_key("doordash-default")
    assert service.browser_mode == "local_cdp"
    assert service.local_cdp_url == "http://127.0.0.1:9224"
    assert (
        service.local_cdp_executable
        == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    assert service.local_cdp_new_page is False
    assert service.local_cdp_close_page_on_exit is None
    assert browser._get_service() is service
