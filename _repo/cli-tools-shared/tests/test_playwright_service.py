import sys
import threading
import types

import pytest

from cli_tools_shared.browser.processes import (
    ProcessCommand,
    ProcessTableUnavailableError,
    ProfileProcessOwner,
)


@pytest.fixture(autouse=True)
def direct_launch_platform(monkeypatch):
    """Keep direct-launch tests portable; macOS CDP cases opt in explicitly."""
    from cli_tools_shared.browser import playwright_service as module
    monkeypatch.setattr(module, "sys", types.SimpleNamespace(platform="linux"))


class _FakePage:
    url = "about:blank"

    def title(self):
        return "Fake title"

    def set_default_timeout(self, _timeout):
        return None

    def set_default_navigation_timeout(self, _timeout):
        return None

    def goto(self, url):
        self.url = url

    def close(self):
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


def test_playwright_service_uses_real_keychain_like_cdp_backend(tmp_path, monkeypatch):
    """Playwright must encrypt cookies with the same OS key as the CDP backend.

    Playwright's default Chromium switches include ``--use-mock-keychain`` and
    ``--password-store=basic``. The CDP backend launches plain Chrome, which
    uses the real macOS "Chrome Safe Storage" key. Both backends open the one
    shared user-data-dir, so each purged the other's cookies as undecryptable
    and every cross-backend CLI run signed the other CLIs out (agent-issues#530).
    """
    from cli_tools_shared.browser import playwright_service as module
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    playwright = _FakePlaywright()
    fake_sync_module = types.SimpleNamespace(
        sync_playwright=lambda: _FakeSyncPlaywright(playwright)
    )
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_module)
    monkeypatch.setattr(module, "_chrome_binary", lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    service = PlaywrightBrowserService("sample-browser-session", timeout=7)
    service.browser_open(persistent_profile_dir=tmp_path / "profile")

    _args, kwargs = playwright.chromium.launch_calls[0]
    assert set(kwargs["ignore_default_args"]) == {"--use-mock-keychain", "--password-store=basic"}
    assert "--use-mock-keychain" not in kwargs["args"]
    assert "--password-store=basic" not in kwargs["args"]


def test_playwright_service_holds_profile_lifecycle_lock_until_close(tmp_path, monkeypatch):
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    playwright = _FakePlaywright()
    fake_sync_module = types.SimpleNamespace(
        sync_playwright=lambda: _FakeSyncPlaywright(playwright)
    )
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_module)
    from cli_tools_shared.browser import playwright_service as module
    monkeypatch.setattr(module, "_chrome_binary", lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    service.browser_open(persistent_profile_dir=profile)

    assert service._lifecycle_lock_file is not None
    assert (tmp_path / ".chromium-profile.lifecycle.lock").is_file()

    service.browser_close()

    assert service._lifecycle_lock_file is None


def test_playwright_service_serializes_concurrent_owners_of_same_profile(tmp_path):
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    profile = tmp_path / "chromium-profile"
    first = PlaywrightBrowserService("first-owner")
    second = PlaywrightBrowserService("second-owner")
    first._user_data_dir = profile
    second._user_data_dir = profile
    first._acquire_profile_lifecycle_lock()

    second_acquired = threading.Event()

    def acquire_second_owner():
        second._acquire_profile_lifecycle_lock()
        second_acquired.set()

    thread = threading.Thread(target=acquire_second_owner)
    thread.start()

    assert not second_acquired.wait(timeout=0.1)
    first._release_profile_lifecycle_lock()
    assert second_acquired.wait(timeout=1)

    second._release_profile_lifecycle_lock()
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_playwright_service_releases_profile_lifecycle_lock_after_failed_launch(tmp_path, monkeypatch):
    from cli_tools_shared.browser import playwright_service as module
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService, PlaywrightServiceError

    class _FailingChromium:
        def launch_persistent_context(self, *_args, **_kwargs):
            raise RuntimeError("launch failed")

    playwright = _FakePlaywright()
    playwright.chromium = _FailingChromium()
    fake_sync_module = types.SimpleNamespace(
        sync_playwright=lambda: _FakeSyncPlaywright(playwright)
    )
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_module)
    monkeypatch.setattr(module, "_chrome_binary", lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    service = PlaywrightBrowserService("sample-browser-session")
    with pytest.raises(PlaywrightServiceError, match="launch failed"):
        service.browser_open(persistent_profile_dir=tmp_path / "chromium-profile")

    assert service._lifecycle_lock_file is None


def test_playwright_service_session_process_pids_match_profile_only(tmp_path, monkeypatch):
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    other = tmp_path / "other-profile"
    service._user_data_dir = profile
    monkeypatch.setattr(
        service,
        "_list_process_table",
        lambda: [
            ProcessCommand(101, 1, "S", f"/Applications/Google Chrome --user-data-dir={profile}"),
            ProcessCommand(102, 1, "S", f"/Applications/Google Chrome Helper --user-data-dir {profile}"),
            ProcessCommand(103, 1, "S", f"/Applications/Google Chrome --user-data-dir={other}"),
            ProcessCommand(104, 1, "S", "/Applications/Google Chrome"),
            ProcessCommand(105, 1, "Z", f"/Applications/Google Chrome --user-data-dir={profile}"),
        ],
    )

    assert service._session_process_pids() == [101, 102]


def test_playwright_service_removes_stale_singleton_artifacts(tmp_path, monkeypatch):
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    profile.mkdir()
    (profile / "SingletonLock").symlink_to("old-host-99999")
    (profile / "SingletonCookie").write_text("stale")
    service._user_data_dir = profile
    monkeypatch.setattr(service, "_profile_owner", lambda: None)
    monkeypatch.setattr(
        "cli_tools_shared.browser.playwright_service.pid_is_running",
        lambda _pid: False,
    )

    service._cleanup_stale_profile_locks()

    assert not (profile / "SingletonLock").is_symlink()
    assert not (profile / "SingletonCookie").exists()


def test_playwright_service_preserves_locks_for_live_profile_owner(tmp_path, monkeypatch):
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService, PlaywrightServiceError

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    profile.mkdir()
    lock = profile / "SingletonLock"
    lock.symlink_to("host-13510")
    service._user_data_dir = profile
    owner = ProfileProcessOwner(
        pid=13510,
        parent_pid=55,
        parent_command="python external-cli.py",
    )
    monkeypatch.setattr(service, "_profile_owner", lambda: owner)

    with pytest.raises(PlaywrightServiceError, match="13510"):
        service._cleanup_stale_profile_locks()

    assert lock.is_symlink()


def test_playwright_service_browser_close_does_not_signal_leftover_profile_processes(tmp_path, monkeypatch):
    from cli_tools_shared.browser import playwright_service as module
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    service._user_data_dir = profile
    service._opened = True
    service._context = _FakeContext()
    service._playwright = _FakePlaywright()
    monkeypatch.setattr(
        module.os,
        "kill",
        lambda *_args: pytest.fail("browser_close must not signal a profile owner"),
    )

    service.browser_close()

    assert service._context is None
    assert service._playwright is None
    assert service._opened is False


def test_playwright_service_browser_close_does_not_kill_external_profile_owner_after_failed_open(tmp_path, monkeypatch):
    from cli_tools_shared.browser import playwright_service as module
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    service._user_data_dir = profile
    processes = [
        ProcessCommand(67275, 1, "S", f"/Applications/Google Chrome --user-data-dir={profile}")
    ]
    killed = []

    monkeypatch.setattr(service, "_list_process_table", lambda: list(processes))
    monkeypatch.setattr(module.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    service.browser_close()

    assert killed == []


def test_playwright_service_data_delete_refuses_live_external_profile_owner(tmp_path, monkeypatch):
    from cli_tools_shared.browser import playwright_service as module
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService, PlaywrightServiceError

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    profile.mkdir()
    service._user_data_dir = profile
    monkeypatch.setattr(
        service,
        "_list_process_table",
        lambda: [
            ProcessCommand(67274, 1, "S", "python external-cli.py"),
            ProcessCommand(
                67275,
                67274,
                "S",
                f"/Applications/Google Chrome --user-data-dir={profile.resolve()}",
            ),
        ],
    )
    monkeypatch.setattr(
        module.os,
        "kill",
        lambda *_args: pytest.fail("data_delete must not signal an external profile owner"),
    )

    with pytest.raises(PlaywrightServiceError, match="PID 67275"):
        service.data_delete()

    assert profile.exists()


def test_playwright_service_data_delete_requires_fresh_owner_inspection(tmp_path, monkeypatch):
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService, PlaywrightServiceError

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    profile.mkdir()
    service._user_data_dir = profile
    monkeypatch.setattr(
        service,
        "_list_process_table",
        lambda: (_ for _ in ()).throw(ProcessTableUnavailableError("inspection unavailable")),
    )

    with pytest.raises(PlaywrightServiceError, match="Cannot verify"):
        service.data_delete()
    assert profile.exists()


class _RecordingPage:
    def __init__(self, name, events):
        self.name = name
        self.events = events

    def goto(self, url):
        self.events.append(f"goto:{self.name}:{url}")

    def close(self):
        self.events.append(f"close:{self.name}")


def test_playwright_service_close_leaves_single_blank_tab_for_next_restore(tmp_path, monkeypatch):
    """Other tools' restored tabs must not reopen on the next launch (agent-issues#530)."""
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    events = []
    ours = _RecordingPage("ours", events)
    restored = [_RecordingPage("brickowl-login", events), _RecordingPage("lego-identity", events)]
    context = _FakeContext()
    context.pages = [restored[0], ours, restored[1]]
    original_close = context.close
    context.close = lambda: (events.append("context-close"), original_close())

    service = PlaywrightBrowserService("sample-browser-session")
    service._user_data_dir = tmp_path / "chromium-profile"
    service._opened = True
    service._context = context
    service._page = ours
    service._playwright = _FakePlaywright()

    service.browser_close()

    assert events == [
        "close:brickowl-login",
        "close:lego-identity",
        "goto:ours:about:blank",
        "context-close",
    ]


@pytest.fixture
def macos_launch(tmp_path, monkeypatch):
    from cli_tools_shared.browser import playwright_service as module

    events = []
    playwright = _FakePlaywright()
    context = _FakeContext()
    cdp = types.SimpleNamespace(send=lambda method: events.append(method))
    browser = types.SimpleNamespace(
        contexts=[context], new_browser_cdp_session=lambda: cdp,
    )
    playwright.chromium.connect_over_cdp = lambda endpoint, **kwargs: (
        events.append((endpoint, kwargs)) or browser
    )
    monkeypatch.setitem(sys.modules, "playwright.sync_api", types.SimpleNamespace(
        sync_playwright=lambda: _FakeSyncPlaywright(playwright),
    ))
    monkeypatch.setattr(module, "sys", types.SimpleNamespace(platform="darwin"))
    executable = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    monkeypatch.setattr(module, "_chrome_binary", lambda: executable)
    monkeypatch.setattr(module, "_find_free_port", lambda: 19456)
    monkeypatch.setattr(module, "_wait_for_cdp", lambda *args, **kwargs: "ws://127.0.0.1:19456/test")
    launches = []
    launcher = types.SimpleNamespace(wait=lambda **kwargs: 0)
    monkeypatch.setattr(module.subprocess, "Popen", lambda args, **kwargs: (
        launches.append(args) or launcher
    ))
    monkeypatch.setattr(module, "list_process_commands", lambda **kwargs: [])
    return module, playwright, context, events, launches


@pytest.mark.parametrize("headed", [False, True])
def test_macos_launchservices_uses_real_keychain_and_persistent_context(macos_launch, tmp_path, headed):
    module, playwright, context, events, launches = macos_launch
    service = module.PlaywrightBrowserService("macos", timeout=7)
    profile = tmp_path / "profile with spaces"
    service.browser_open(persistent_profile_dir=profile, headed=headed, user_agent="Agent test")

    assert launches[0][:4] == ["/usr/bin/open", "-na", "/Applications/Google Chrome.app", "--args"]
    assert f"--user-data-dir={profile}" in launches[0]
    assert "--remote-debugging-port=19456" in launches[0]
    assert "--restore-last-session" in launches[0]
    assert "--user-agent=Agent test" in launches[0]
    assert ("--headless=new" in launches[0]) is not headed
    assert "--use-mock-keychain" not in launches[0]
    assert "--password-store=basic" not in launches[0]
    assert playwright.chromium.launch_calls == []
    assert service._context is context
    assert events[0] == ("ws://127.0.0.1:19456/test", {"timeout": 7000})
    service.browser_close()
    assert "Browser.close" in events
    assert context.closed is False
    assert playwright.stopped
    assert service._lifecycle_lock_file is None


def test_macos_shutdown_holds_lock_until_owned_processes_exit(macos_launch, tmp_path, monkeypatch):
    module, *_rest = macos_launch
    service = module.PlaywrightBrowserService("first")
    other = module.PlaywrightBrowserService("second")
    profile = tmp_path / "profile"
    service.browser_open(persistent_profile_dir=profile)
    other._user_data_dir = profile
    acquired = threading.Event()
    worker = threading.Thread(target=lambda: (other._acquire_profile_lifecycle_lock(), acquired.set()))
    original_finish = service._finish_external_chrome

    def finish():
        worker.start()
        assert not acquired.wait(timeout=0.1)
        assert service._lifecycle_lock_file is not None
        original_finish()

    monkeypatch.setattr(service, "_finish_external_chrome", finish)
    service.browser_close()
    assert acquired.wait(timeout=1)
    other._release_profile_lifecycle_lock()
    worker.join(timeout=1)


def test_macos_failed_connection_reaps_only_exact_launch(macos_launch, tmp_path, monkeypatch):
    module, playwright, _context, _events, _launches = macos_launch
    profile = tmp_path / "profile"
    processes = [
        ProcessCommand(101, 1, "S", f'/Applications/Google Chrome --user-data-dir={profile} --remote-debugging-port=19456'),
        ProcessCommand(102, 1, "S", f'/Applications/Google Chrome --user-data-dir={tmp_path / "other"} --remote-debugging-port=19456'),
    ]
    monkeypatch.setattr(module, "list_process_commands", lambda **kwargs: list(processes))
    service = module.PlaywrightBrowserService("failed")
    monkeypatch.setattr(service, "_cleanup_stale_profile_locks", lambda: None)
    monkeypatch.setattr(playwright.chromium, "connect_over_cdp", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("connection failed")))
    ticks = iter(range(0, 1000, 10))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    killed = []

    def terminate(pid, *, ownership_check, **kwargs):
        assert service._lifecycle_lock_file is not None
        assert ownership_check(1) is True
        killed.append(pid)
        processes[:] = [proc for proc in processes if proc.pid != pid]

    monkeypatch.setattr(module, "terminate_process", terminate)
    with pytest.raises(module.PlaywrightServiceError, match="connection failed"):
        service.browser_open(persistent_profile_dir=profile)
    assert killed == [101]
    assert [proc.pid for proc in processes] == [102]
    assert service._lifecycle_lock_file is None
    assert playwright.stopped


def test_macos_failed_launch_never_signals_foreign_profile_owner(macos_launch, tmp_path, monkeypatch):
    module, *_rest = macos_launch
    service = module.PlaywrightBrowserService("failed")
    profile = tmp_path / "profile"
    monkeypatch.setattr(service, "_cleanup_stale_profile_locks", lambda: None)
    monkeypatch.setattr(module, "_wait_for_cdp", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no endpoint")))
    monkeypatch.setattr(module, "list_process_commands", lambda **kwargs: [
        ProcessCommand(111, 1, "S", f'/Applications/Google Chrome --user-data-dir={profile} --remote-debugging-port=19999'),
    ])
    monkeypatch.setattr(module, "terminate_process", lambda *args, **kwargs: pytest.fail("foreign owner signalled"))
    ticks = iter(range(0, 1000, 10))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    with pytest.raises(module.PlaywrightServiceError, match="still holds the profile"):
        service.browser_open(persistent_profile_dir=profile)
    assert service._lifecycle_lock_file is not None
    assert service._cdp_port == 19456
    assert service._chrome_proc is not None
    monkeypatch.setattr(module, "list_process_commands", lambda **kwargs: [])
    service.browser_close()
    assert service._lifecycle_lock_file is None
    assert service._cdp_port is None
    assert service._chrome_proc is None


def test_macos_shutdown_inspection_failure_retains_lock_and_ownership_for_retry(macos_launch, tmp_path, monkeypatch):
    module, *_rest = macos_launch
    service = module.PlaywrightBrowserService("first")
    other = module.PlaywrightBrowserService("second")
    profile = tmp_path / "profile"
    service.browser_open(persistent_profile_dir=profile)
    other._user_data_dir = profile
    acquired = threading.Event()
    worker = threading.Thread(target=lambda: (other._acquire_profile_lifecycle_lock(), acquired.set()))
    original_launcher = service._chrome_proc
    monkeypatch.setattr(module, "list_process_commands", lambda **kwargs: (
        (_ for _ in ()).throw(ProcessTableUnavailableError("cannot inspect"))
    ))
    with pytest.raises(ProcessTableUnavailableError, match="cannot inspect"):
        service.browser_close()
    assert service._chrome_proc is original_launcher
    assert service._cdp_port == 19456
    assert service._lifecycle_lock_file is not None
    worker.start()
    assert not acquired.wait(timeout=0.1)
    monkeypatch.setattr(module, "list_process_commands", lambda **kwargs: [])
    service.browser_close()
    assert acquired.wait(timeout=1)
    other._release_profile_lifecycle_lock()
    worker.join(timeout=1)
    assert service._chrome_proc is None
    assert service._cdp_port is None
    assert service._lifecycle_lock_file is None
