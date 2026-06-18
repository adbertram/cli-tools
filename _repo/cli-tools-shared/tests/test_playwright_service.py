import sys
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
