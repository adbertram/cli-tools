import asyncio
import threading

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
    service.browser_close()


def test_webwright_service_holds_profile_lifecycle_lock_until_close(tmp_path, monkeypatch):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

    monkeypatch.setattr(
        webwright_module,
        "_load_local_browser_environment",
        lambda: _FakeEnvironment,
    )
    profile_dir = tmp_path / "chromium-profile"
    service = WebwrightBrowserService("service-default")

    service.browser_open(persistent_profile_dir=profile_dir)

    assert service._lifecycle_lock_file is not None
    assert (tmp_path / ".chromium-profile.lifecycle.lock").is_file()

    service.browser_close()

    assert service._lifecycle_lock_file is None


def test_driver_and_webwright_backends_share_one_resolved_profile_lock(tmp_path):
    from cli_tools_shared.browser.driver import BrowserHarnessService
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

    profile = tmp_path / "profiles" / ".." / "chromium-profile"
    driver = BrowserHarnessService("cdp-owner")
    webwright = WebwrightBrowserService("webwright-owner")
    driver._user_data_dir = profile
    webwright._user_data_dir = profile.resolve()
    driver._acquire_lifecycle_lock()
    acquired = threading.Event()

    def acquire_webwright_owner():
        webwright._acquire_profile_lifecycle_lock()
        acquired.set()

    thread = threading.Thread(target=acquire_webwright_owner)
    thread.start()
    try:
        assert not acquired.wait(timeout=0.1)
    finally:
        driver._release_lifecycle_lock()
    assert acquired.wait(timeout=1)
    webwright._release_profile_lifecycle_lock()
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_webwright_service_releases_lifecycle_lock_after_failed_prepare(tmp_path, monkeypatch):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import (
        WebwrightBrowserService,
        WebwrightServiceError,
    )

    class _FailingEnvironment(_FakeEnvironment):
        def prepare(self, **kwargs):
            self.prepared.append(kwargs)
            raise RuntimeError("prepare failed")

    monkeypatch.setattr(
        webwright_module,
        "_load_local_browser_environment",
        lambda: _FailingEnvironment,
    )
    service = WebwrightBrowserService("service-default")

    with pytest.raises(WebwrightServiceError, match="prepare failed"):
        service.browser_open(persistent_profile_dir=tmp_path / "chromium-profile")

    assert service._lifecycle_lock_file is None
    assert _FakeEnvironment.instances[0].closed is True


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
    service.browser_close()


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

    monkeypatch.setattr(service, "_list_process_table", list)
    service.data_delete()

    assert env.closed is True
    assert not profile_dir.exists()


def test_webwright_data_delete_holds_lifecycle_lock_across_close_and_removal(tmp_path, monkeypatch):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

    profile_dir = tmp_path / "chromium-profile"
    profile_dir.mkdir()
    service = WebwrightBrowserService("service-default")
    service._user_data_dir = profile_dir
    events = []
    original_rmtree = webwright_module.shutil.rmtree

    def close_browser():
        assert service._lifecycle_lock_file is not None
        events.append("close")

    def verify_owner():
        assert service._lifecycle_lock_file is not None
        events.append("owner-check")

    def cleanup_artifacts():
        assert service._lifecycle_lock_file is not None
        events.append("cleanup")

    def remove_profile(path):
        assert service._lifecycle_lock_file is not None
        events.append("remove")
        original_rmtree(path)

    monkeypatch.setattr(service, "_close_browser_locked", close_browser)
    monkeypatch.setattr(service, "_raise_if_profile_in_use", verify_owner)
    monkeypatch.setattr(service, "_cleanup_stale_profile_locks", cleanup_artifacts)
    monkeypatch.setattr(webwright_module.shutil, "rmtree", remove_profile)

    service.data_delete()

    assert events == ["close", "owner-check", "cleanup", "remove"]
    assert service._lifecycle_lock_file is None
    assert not profile_dir.exists()


def test_webwright_data_delete_refuses_live_external_profile_owner(tmp_path, monkeypatch):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.processes import ProcessCommand
    from cli_tools_shared.browser.webwright import (
        WebwrightBrowserService,
        WebwrightServiceError,
    )

    profile_dir = tmp_path / "chromium-profile"
    profile_dir.mkdir()
    service = WebwrightBrowserService("service-default")
    service._user_data_dir = profile_dir
    monkeypatch.setattr(
        service,
        "_list_process_table",
        lambda: [
            ProcessCommand(67274, 1, "S", "python external-cli.py"),
            ProcessCommand(
                67275,
                67274,
                "S",
                f"/Applications/Google Chrome --user-data-dir={profile_dir.resolve()}",
            ),
        ],
    )
    monkeypatch.setattr(
        webwright_module.os,
        "kill",
        lambda *_args: pytest.fail("data_delete must not signal an external profile owner"),
    )

    with pytest.raises(WebwrightServiceError, match="PID 67275"):
        service.data_delete()

    assert profile_dir.exists()


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
