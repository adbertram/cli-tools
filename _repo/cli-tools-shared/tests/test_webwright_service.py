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
        self.closed = False
        self.goto_calls = []
        self.evaluate_calls = []
        self.wait_for_selector_calls = []
        self.keyboard = _FakeKeyboard()

    async def goto(self, url, wait_until=None):
        self.url = url
        self.goto_calls.append((url, wait_until))

    async def close(self):
        self.closed = True

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
    def __init__(self, page):
        self.cookies_calls = 0
        self.pages = [page]

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
        self._context = _FakeContext(self._page)
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


class _FakeChromeProcess:
    def __init__(self, pid=4321):
        self.pid = pid
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout):
        del timeout
        self.terminated = True

    def kill(self):
        self.terminated = True


@pytest.fixture(autouse=True)
def reset_fake_environment(monkeypatch):
    from cli_tools_shared.browser import webwright as webwright_module

    _FakeEnvironment.instances = []
    monkeypatch.setattr(
        webwright_module,
        "_chrome_binary",
        lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )


@pytest.fixture
def fake_webwright_environment(monkeypatch):
    from cli_tools_shared.browser import webwright as webwright_module

    monkeypatch.setattr(
        webwright_module,
        "_load_local_browser_environment",
        lambda: _FakeEnvironment,
    )
    launches = []
    managed_processes = []

    def launch_owned_chrome(self, *, headed, launch_args, window_size):
        launches.append(
            {
                "headed": headed,
                "launch_args": launch_args,
                "window_size": window_size,
            }
        )
        process = _FakeChromeProcess()
        managed_processes.append(process)
        self._chrome_process = process
        self._cdp_port = 48321
        return "http://127.0.0.1:48321"

    monkeypatch.setattr(
        webwright_module.WebwrightBrowserService,
        "_launch_owned_chrome",
        launch_owned_chrome,
    )
    def profile_processes(_profile, *, remote_debugging_port=None):
        if remote_debugging_port != 48321:
            return []
        return [process.pid for process in managed_processes if process.poll() is None]

    def terminate_managed_process(pid):
        for process in managed_processes:
            if process.pid == pid:
                process.terminate()
                return
        raise AssertionError(f"unexpected process termination: {pid}")

    monkeypatch.setattr(webwright_module, "profile_process_pids", profile_processes)
    monkeypatch.setattr(webwright_module, "terminate_process", terminate_managed_process)
    return launches


def test_webwright_service_opens_an_owned_shared_profile_via_local_cdp(
    tmp_path, fake_webwright_environment
):
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

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
    assert env.kwargs["browser_mode"] == "local_cdp"
    assert env.kwargs["headless"] is False
    assert env.kwargs["user_data_dir"] == profile_dir
    assert env.kwargs["browser_width"] == 1440
    assert env.kwargs["browser_height"] == 900
    assert env.kwargs["browser_timeout_ms"] == 7000
    assert env.kwargs["browser_navigation_timeout_ms"] == 7000
    assert env.kwargs["local_cdp_url"] == "http://127.0.0.1:48321"
    assert env.kwargs["local_cdp_auto_start"] is False
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
    assert fake_webwright_environment == [
        {
            "headed": True,
            "launch_args": ["--restore-last-session", "--user-agent=CLI Tools"],
            "window_size": (1440, 900),
        }
    ]


def test_webwright_service_rejects_external_cdp_endpoints(tmp_path):
    from cli_tools_shared.browser.webwright import (
        WebwrightBrowserService,
        WebwrightServiceError,
    )

    profile_dir = tmp_path / "profile"

    service = WebwrightBrowserService(
        "service-default",
        local_cdp_url="http://127.0.0.1:9224",
    )

    with pytest.raises(
        WebwrightServiceError,
        match="local_cdp_url is not supported for managed persistent profiles",
    ):
        service.browser_open("https://example.com", persistent_profile_dir=profile_dir)


def test_webwright_service_maps_headless_to_its_owned_chrome(
    tmp_path, fake_webwright_environment
):
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

    service = WebwrightBrowserService("service-default")
    service.browser_open(persistent_profile_dir=tmp_path / "profile")

    assert fake_webwright_environment == [
        {
            "headed": False,
            "launch_args": ["--restore-last-session"],
            "window_size": None,
        }
    ]


def test_webwright_service_launches_owned_chrome_headless_on_an_ephemeral_port(
    tmp_path, monkeypatch
):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

    launched = []

    class _CapturingProcess(_FakeChromeProcess):
        def __init__(self, args, **kwargs):
            super().__init__()
            launched.append((args, kwargs))

    service = WebwrightBrowserService("service-default")
    service._user_data_dir = tmp_path / "profile"
    service._user_data_dir.mkdir()
    monkeypatch.setattr(webwright_module, "_chrome_binary", lambda: "/tmp/chrome")
    monkeypatch.setattr(webwright_module.subprocess, "Popen", _CapturingProcess)
    monkeypatch.setattr(
        service,
        "_wait_for_owned_cdp_endpoint",
        lambda: "http://127.0.0.1:48321",
    )

    endpoint = service._launch_owned_chrome(
        headed=False,
        launch_args=["--restore-last-session"],
        window_size=(1440, 900),
    )

    args, kwargs = launched[0]
    assert endpoint == "http://127.0.0.1:48321"
    assert args[0] == "/tmp/chrome"
    assert any(arg.startswith("--remote-debugging-port=") and arg != "--remote-debugging-port=9222" for arg in args)
    assert f"--user-data-dir={service._user_data_dir}" in args
    assert "--headless=new" in args
    assert "--window-size=1440,900" in args
    assert kwargs["start_new_session"] is True


def test_webwright_service_verifies_devtools_endpoint_matches_owned_process(
    tmp_path, monkeypatch
):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

    class _Response:
        status = 200

        def read(self):
            return b'{"webSocketDebuggerUrl":"ws://127.0.0.1:48321/devtools/browser/test"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    service = WebwrightBrowserService("service-default")
    service._user_data_dir = tmp_path / "profile"
    service._user_data_dir.mkdir()
    (service._user_data_dir / "DevToolsActivePort").write_text("48321\n/devtools/browser/test\n")
    service._cdp_port = 48321
    service._chrome_process = _FakeChromeProcess(pid=4321)
    monkeypatch.setattr(
        webwright_module,
        "profile_process_pids",
        lambda _profile, *, remote_debugging_port: [4321],
    )
    monkeypatch.setattr(webwright_module, "urlopen", lambda _url, timeout: _Response())

    assert service._wait_for_owned_cdp_endpoint() == "http://127.0.0.1:48321"


def test_webwright_service_rejects_devtools_endpoint_not_owned_by_launched_chrome(
    tmp_path, monkeypatch
):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import (
        WebwrightBrowserService,
        WebwrightServiceError,
    )

    service = WebwrightBrowserService("service-default", timeout=1)
    service._user_data_dir = tmp_path / "profile"
    service._user_data_dir.mkdir()
    (service._user_data_dir / "DevToolsActivePort").write_text("48321\n/devtools/browser/test\n")
    service._cdp_port = 48321
    service._chrome_process = _FakeChromeProcess(pid=4321)
    monkeypatch.setattr(
        webwright_module,
        "profile_process_pids",
        lambda _profile, *, remote_debugging_port: [999],
    )

    with pytest.raises(WebwrightServiceError, match="CDP endpoint is not owned"):
        service._wait_for_owned_cdp_endpoint()


def test_webwright_service_exposes_page_helpers_and_deletes_profile(
    tmp_path, fake_webwright_environment
):
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

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


def test_webwright_service_close_leaves_single_blank_tab_and_tears_down_owned_browser(
    tmp_path, fake_webwright_environment, monkeypatch
):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import WebwrightBrowserService

    service = WebwrightBrowserService("service-default")
    service.browser_open(
        "https://example.com/orders",
        persistent_profile_dir=tmp_path / "profile",
    )
    env = _FakeEnvironment.instances[0]
    chrome_process = service._chrome_process
    restored = _FakePage()
    env._context.pages.insert(0, restored)
    alive = {chrome_process.pid, 8765}
    terminated = []
    profile_port_checks = []

    def profile_processes(_profile, *, remote_debugging_port=None):
        profile_port_checks.append(remote_debugging_port)
        if remote_debugging_port == 48321:
            return [chrome_process.pid] if chrome_process.pid in alive else []
        return sorted(alive)

    def terminate_managed_process(pid):
        terminated.append(pid)
        alive.discard(pid)

    monkeypatch.setattr(webwright_module, "profile_process_pids", profile_processes)
    monkeypatch.setattr(webwright_module, "terminate_process", terminate_managed_process)

    service.browser_close()

    assert restored.closed is True
    assert env._page.goto_calls == [
        ("https://example.com/orders", "domcontentloaded"),
        ("about:blank", None),
    ]
    assert env.closed is True
    assert terminated == [chrome_process.pid]
    assert alive == {8765}
    assert profile_port_checks == [48321, 48321]
    assert chrome_process.terminated is True


def test_webwright_service_close_fails_when_a_profile_process_survives(
    tmp_path, fake_webwright_environment, monkeypatch
):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import (
        WebwrightBrowserService,
        WebwrightServiceError,
    )

    service = WebwrightBrowserService("service-default")
    service.browser_open(
        "https://example.com/orders",
        persistent_profile_dir=tmp_path / "profile",
    )
    env = _FakeEnvironment.instances[0]
    chrome_process = service._chrome_process
    monkeypatch.setattr(webwright_module, "terminate_process", lambda _pid: None)
    monkeypatch.setattr(
        webwright_module,
        "profile_process_pids",
        lambda _profile, *, remote_debugging_port: [chrome_process.pid],
    )

    with pytest.raises(WebwrightServiceError, match="managed Webwright CDP endpoint"):
        service.browser_close()

    assert env.closed is True


def test_webwright_service_refuses_to_start_when_another_chrome_owns_profile(
    tmp_path, fake_webwright_environment, monkeypatch
):
    from cli_tools_shared.browser import webwright as webwright_module
    from cli_tools_shared.browser.webwright import (
        WebwrightBrowserService,
        WebwrightServiceError,
    )

    monkeypatch.setattr(webwright_module, "profile_process_pids", lambda _profile: [99])
    service = WebwrightBrowserService("service-default")

    with pytest.raises(
        WebwrightServiceError,
        match=r"profile is already in use by Chrome process\(es\) 99",
    ):
        service.browser_open(persistent_profile_dir=tmp_path / "profile")

    assert _FakeEnvironment.instances == []


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
            local_cdp_executable=None,
            local_cdp_new_page=None,
            local_cdp_close_page_on_exit=None,
        ):
            self.session = session
            self.local_cdp_executable = local_cdp_executable
            self.local_cdp_new_page = local_cdp_new_page
            self.local_cdp_close_page_on_exit = local_cdp_close_page_on_exit
            _FakeService.instances.append(self)

    monkeypatch.setattr(webwright_module, "WebwrightBrowserService", _FakeService)

    browser = _Browser(_Config())
    service = browser._get_service()

    assert service.session == auth_module._safe_daemon_key("custom-work")
    assert service.local_cdp_executable is None
    assert service.local_cdp_new_page is None
    assert service.local_cdp_close_page_on_exit is None
    assert browser._get_service() is service
