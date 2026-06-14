import asyncio
from pathlib import Path

import pytest


class _FakeKeyboard:
    def __init__(self):
        self.pressed = []
        self.typed = []

    async def press(self, key):
        self.pressed.append(key)

    async def type(self, text):
        self.typed.append(text)


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.goto_calls = []
        self.evaluate_calls = []
        self.wait_for_selector_calls = []
        self.keyboard = _FakeKeyboard()

    async def goto(self, url, wait_until=None):
        self.url = url
        self.goto_calls.append((url, wait_until))

    async def title(self):
        return "Fake title"

    async def evaluate(self, js, arg=None):
        self.evaluate_calls.append((js, arg))
        if "document.querySelector" in js:
            return True
        if "localStorage" in js:
            return [{"key": "token", "value": "abc"}]
        return {"js": js, "arg": arg}

    async def wait_for_selector(self, selector, state="visible", timeout=30000):
        self.wait_for_selector_calls.append((selector, state, timeout))
        return object()


class _FakeContext:
    def __init__(self):
        self.cookies_calls = 0

    async def cookies(self):
        self.cookies_calls += 1
        return [
            {
                "name": "session",
                "value": "secret",
                "domain": ".example.com",
                "path": "/",
                "expires": 9999999999,
            }
        ]


class _FakeEnvironment:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.prepared = []
        self.closed = False
        self._page = _FakePage()
        self._context = _FakeContext()
        _FakeEnvironment.instances.append(self)

    def prepare(self, **kwargs):
        self.prepared.append(kwargs)
        start_url = kwargs.get("start_url")
        if start_url:
            self._run(self._page.goto(start_url, wait_until="domcontentloaded"))

    def _run(self, coro):
        return asyncio.run(coro)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fake_environment():
    _FakeEnvironment.instances = []


def test_webwright_service_opens_persistent_profile_and_navigates(tmp_path, monkeypatch):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

    monkeypatch.setattr(
        webwright_module,
        "_load_local_browser_environment",
        lambda: _FakeEnvironment,
    )
    profile_dir = tmp_path / "profile"

    service = WebwrightBrowserService("service-default", timeout=7)
    result = service.browser_open(
        "https://example.com/dashboard",
        headed=True,
        persistent_profile_dir=profile_dir,
        user_agent="CLI Tools",
        window_size="1440x900",
    )

    env = _FakeEnvironment.instances[0]
    assert env.kwargs["browser_mode"] == "local_persistent"
    assert env.kwargs["headless"] is False
    assert env.kwargs["user_data_dir"] == profile_dir
    assert env.kwargs["browser_width"] == 1440
    assert env.kwargs["browser_height"] == 900
    assert env.kwargs["browser_timeout_ms"] == 7000
    assert env.kwargs["browser_navigation_timeout_ms"] == 7000
    assert env.kwargs["launch_args"] == [
        "--restore-last-session",
        "--user-agent=CLI Tools",
    ]
    assert env.prepared == [
        {
            "task": "Open https://example.com/dashboard",
            "task_id": "service-default",
            "start_url": "https://example.com/dashboard",
        }
    ]
    assert result["url"] == "https://example.com/dashboard"
    assert result["title"] == "Fake title"


def test_webwright_service_passes_local_cdp_options(tmp_path, monkeypatch):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

    monkeypatch.setattr(
        webwright_module,
        "_load_local_browser_environment",
        lambda: _FakeEnvironment,
    )
    profile_dir = tmp_path / "profile"

    service = WebwrightBrowserService(
        "service-default",
        browser_mode="local_cdp",
        local_cdp_url="http://127.0.0.1:9224",
        local_cdp_executable="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        local_cdp_new_page=True,
        local_cdp_close_page_on_exit=True,
        local_cdp_close_started_browser_on_exit=False,
    )
    service.browser_open("https://example.com", persistent_profile_dir=profile_dir)

    env = _FakeEnvironment.instances[0]
    assert env.kwargs["browser_mode"] == "local_cdp"
    assert env.kwargs["local_cdp_url"] == "http://127.0.0.1:9224"
    assert (
        env.kwargs["local_cdp_executable"]
        == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    assert env.kwargs["local_cdp_new_page"] is True
    assert env.kwargs["local_cdp_close_page_on_exit"] is True
    assert env.kwargs["local_cdp_close_started_browser_on_exit"] is False


def test_webwright_service_exposes_page_helpers_and_deletes_profile(tmp_path, monkeypatch):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

    monkeypatch.setattr(
        webwright_module,
        "_load_local_browser_environment",
        lambda: _FakeEnvironment,
    )
    profile_dir = tmp_path / "profile"
    (profile_dir / "Default").mkdir(parents=True)
    (profile_dir / "Default" / "Cookies").write_text("cookies")

    service = WebwrightBrowserService("service-default")
    service.browser_open(persistent_profile_dir=profile_dir)
    page = service.page_goto("https://example.com/orders")

    assert page["url"] == "https://example.com/orders"
    assert service.evaluate("() => 42", {"x": 1}) == {
        "js": "() => 42",
        "arg": {"x": 1},
    }
    assert service.page_eval("() => 42") == {
        "result": {"js": "() => 42", "arg": None}
    }
    assert service.cookie_list()[0]["name"] == "session"
    assert service.localstorage_list() == [{"key": "token", "value": "abc"}]
    assert service.query_selector("body") is not None
    assert service.wait_for_selector("body") is not None

    service.keyboard_press("Enter")
    service.type_text("hello")
    env = _FakeEnvironment.instances[0]
    assert env._page.keyboard.pressed == ["Enter"]
    assert env._page.keyboard.typed == ["hello"]

    service.data_delete()

    assert env.closed is True
    assert not profile_dir.exists()


def test_webwright_browser_automation_uses_webwright_service(monkeypatch):
    from cli_tools_shared import auth as auth_module
    from cli_tools_shared.auth import WebwrightBrowserAutomation
    from cli_tools_shared.browser import webwright as webwright_module

    class _Config:
        _tool_name = "tool"

        def get_active_profile_name(self):
            return "work"

    class _Browser(WebwrightBrowserAutomation):
        SESSION_NAME = "custom"

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

    browser = _Browser(_Config())
    service = browser._get_service()

    assert service.session == auth_module._safe_daemon_key("custom-work")
    assert service.browser_mode == "local_persistent"
    assert service.local_cdp_url is None
    assert browser._get_service() is service
