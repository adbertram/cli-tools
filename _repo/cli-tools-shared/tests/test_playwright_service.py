import sys
import threading
import types

import pytest

from cli_tools_shared.browser.processes import ProcessCommand


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


def test_playwright_service_holds_profile_lifecycle_lock_until_close(tmp_path, monkeypatch):
    from cli_tools_shared.browser import playwright_service as module
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    playwright = _FakePlaywright()
    fake_sync_module = types.SimpleNamespace(
        sync_playwright=lambda: _FakeSyncPlaywright(playwright)
    )
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_module)
    monkeypatch.setattr(module, "_chrome_binary", lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    monkeypatch.setattr(
        PlaywrightBrowserService,
        "_cleanup_stale_profile_processes",
        lambda self: None,
    )
    lock_events = []
    monkeypatch.setattr(
        module.fcntl,
        "flock",
        lambda _fd, operation: lock_events.append(operation),
    )

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    service.browser_open(persistent_profile_dir=profile)

    assert lock_events == [module.fcntl.LOCK_EX]
    assert service._lifecycle_lock_file is not None
    assert (tmp_path / ".chromium-profile.lifecycle.lock").is_file()

    service.browser_close()

    assert lock_events == [module.fcntl.LOCK_EX, module.fcntl.LOCK_UN]
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
    lock_events = []
    monkeypatch.setattr(
        module.fcntl,
        "flock",
        lambda _fd, operation: lock_events.append(operation),
    )

    service = PlaywrightBrowserService("sample-browser-session")
    with pytest.raises(PlaywrightServiceError, match="launch failed"):
        service.browser_open(persistent_profile_dir=tmp_path / "chromium-profile")

    assert lock_events == [module.fcntl.LOCK_EX, module.fcntl.LOCK_UN]
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
    monkeypatch.setattr(service, "_session_process_pids", lambda: [])

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
    monkeypatch.setattr(service, "_session_process_pids", lambda: [13510])

    with pytest.raises(PlaywrightServiceError, match="13510"):
        service._cleanup_stale_profile_locks()

    assert lock.is_symlink()


def test_playwright_service_browser_close_terminates_leftover_profile_processes(tmp_path, monkeypatch):
    from cli_tools_shared.browser import playwright_service as module
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    service._user_data_dir = profile
    service._opened = True
    service._context = _FakeContext()
    service._playwright = _FakePlaywright()
    processes = [
        ProcessCommand(67275, 1, "S", f"/Applications/Google Chrome --user-data-dir={profile}")
    ]
    killed = []

    def fake_kill(pid, sig):
        killed.append((pid, sig))
        processes.clear()

    monkeypatch.setattr(service, "_list_process_table", lambda: list(processes))
    monkeypatch.setattr(service, "_pid_running", lambda pid: any(row.pid == pid for row in processes))
    monkeypatch.setattr(module.os, "kill", fake_kill)

    service.browser_close()

    assert killed == [(67275, module.signal.SIGTERM)]
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


def test_playwright_service_data_delete_terminates_matching_profile_processes(tmp_path, monkeypatch):
    from cli_tools_shared.browser import playwright_service as module
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    profile.mkdir()
    service._user_data_dir = profile
    processes = [
        ProcessCommand(67275, 1, "S", f"/Applications/Google Chrome --user-data-dir={profile}")
    ]
    killed = []

    def fake_kill(pid, sig):
        killed.append((pid, sig))
        processes.clear()

    monkeypatch.setattr(service, "_list_process_table", lambda: list(processes))
    monkeypatch.setattr(service, "_pid_running", lambda pid: any(row.pid == pid for row in processes))
    monkeypatch.setattr(module.os, "kill", fake_kill)

    service.data_delete()

    assert killed == [(67275, module.signal.SIGTERM)]
    assert not profile.exists()


def test_playwright_service_data_delete_surfaces_process_cleanup_failure(tmp_path, monkeypatch):
    from cli_tools_shared.browser.playwright_service import PlaywrightBrowserService, PlaywrightServiceError

    service = PlaywrightBrowserService("sample-browser-session")
    profile = tmp_path / "chromium-profile"
    profile.mkdir()
    service._user_data_dir = profile
    monkeypatch.setattr(service, "_session_process_pids", lambda: [67275])

    def fail_cleanup(pid):
        raise PlaywrightServiceError(f"Stale browser process {pid} did not exit")

    monkeypatch.setattr(service, "_terminate_session_pid", fail_cleanup)

    with pytest.raises(PlaywrightServiceError, match="67275"):
        service.data_delete()
    assert profile.exists()
