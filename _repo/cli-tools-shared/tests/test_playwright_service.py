import sys
import types


class _FakePage:
    url = "about:blank"

    def title(self):
        return "Fake title"

    def set_default_timeout(self, _timeout):
        return None

    def set_default_navigation_timeout(self, _timeout):
        return None


class _FakeContext:
    def __init__(self):
        self.pages = [_FakePage()]
        self.closed = False

    def new_page(self):
        page = _FakePage()
        self.pages.append(page)
        return page

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self):
        self.launch_calls = []

    def launch_persistent_context(self, *args, **kwargs):
        self.launch_calls.append((args, kwargs))
        return _FakeContext()


class _FakePlaywright:
    def __init__(self):
        self.chromium = _FakeChromium()
        self.stopped = False

    def stop(self):
        self.stopped = True


class _FakeSyncPlaywright:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


def test_playwright_service_restores_persistent_browser_session(tmp_path, monkeypatch):
    from cli_tools_shared.browser import playwright_service as module
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    playwright = _FakePlaywright()
    fake_sync_module = types.SimpleNamespace(
        sync_playwright=lambda: _FakeSyncPlaywright(playwright)
    )
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_module)
    monkeypatch.setattr(module, "_chrome_binary", lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    service = PlaywrightBrowserService("sample-browser-session", timeout=7)
    result = service.browser_open(persistent_profile_dir=tmp_path / "profile")

    assert result == {
        "url": "about:blank",
        "title": "Fake title",
        "console_errors": 0,
        "console_warnings": 0,
    }
    assert playwright.chromium.launch_calls
    _args, kwargs = playwright.chromium.launch_calls[0]
    assert "--restore-last-session" in kwargs["args"]
