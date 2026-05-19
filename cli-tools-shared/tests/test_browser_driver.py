from pathlib import Path
import threading
import time

import pytest

from cli_tools_shared.browser import BrowserHarnessError
from cli_tools_shared.browser.driver import BrowserHarnessService
import cli_tools_shared.browser.driver as driver


class _Proc:
    def __init__(self, pid: int):
        self.pid = pid


def test_browser_open_cleans_same_session_state_before_launch(tmp_path, monkeypatch):
    service = BrowserHarnessService("pluralsight-author")
    events: list[str] = []
    persistent = tmp_path / "chromium-profile"

    monkeypatch.setattr(service, "_cleanup_stale_session", lambda: events.append("cleanup"))
    monkeypatch.setattr(driver, "_find_free_port", lambda: 51312)
    monkeypatch.setattr(driver, "_wait_for_cdp", lambda port, timeout: events.append(f"wait:{port}"))
    monkeypatch.setattr(driver, "_chrome_binary", lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    monkeypatch.setattr(
        driver.subprocess,
        "Popen",
        lambda *args, **kwargs: events.append("popen") or _Proc(4242),
    )
    monkeypatch.setattr(service, "_start_daemon", lambda: events.append("daemon"))
    monkeypatch.setattr(
        service,
        "_page_info",
        lambda: {"url": "", "title": "", "console_errors": 0, "console_warnings": 0},
    )
    monkeypatch.setattr(service, "_stop_daemon", lambda: events.append("stop"))
    monkeypatch.setattr(service, "_terminate_chrome", lambda: events.append("terminate"))

    class _Helpers:
        def cdp(self, *_args, **_kwargs):
            events.append("cdp")

    service._bh = type("_BH", (), {"h": _Helpers()})()

    service.browser_open("https://example.com/dashboard", persistent_profile_dir=persistent)
    service.browser_close()

    assert events == ["cleanup", "popen", "wait:51312", "daemon", "cdp", "stop", "terminate"]


def test_session_process_pids_match_only_same_session_user_data_dir(tmp_path, monkeypatch):
    service = BrowserHarnessService("pluralsight-author")
    session_dir = tmp_path / "ud-pluralsight-author"
    other_dir = tmp_path / "ud-other"
    extra_dir = Path(f"{session_dir}-extra")
    service._user_data_dir = session_dir
    monkeypatch.setattr(
        service,
        "_list_process_commands",
        lambda: [
            (101, "S", f"/Applications/Google Chrome --user-data-dir={session_dir}"),
            (102, "S", f"/Applications/Google Chrome Helper --user-data-dir {session_dir}"),
            (103, "S", f"/Applications/Google Chrome --user-data-dir={extra_dir}"),
            (104, "S", f"/Applications/Google Chrome Helper --user-data-dir {extra_dir}"),
            (105, "S", "/Applications/Google Chrome"),
            (106, "S", f"/Applications/Google Chrome --user-data-dir={other_dir}"),
            (107, "Z", f"/Applications/Google Chrome --user-data-dir={session_dir}"),
        ],
    )

    assert service._session_process_pids() == [101, 102]


def test_cleanup_stale_session_stops_daemon_kills_matching_pids_and_clears_locks(tmp_path, monkeypatch):
    service = BrowserHarnessService("pluralsight-author")
    user_data_dir = tmp_path / "ud-pluralsight-author"
    user_data_dir.mkdir(parents=True)
    lock_paths = [
        user_data_dir / "SingletonCookie",
        user_data_dir / "SingletonLock",
        user_data_dir / "SingletonSocket",
        user_data_dir / "DevToolsActivePort",
    ]
    for path in lock_paths:
        path.write_text("stale")

    restarted: list[str] = []
    killed: list[int] = []

    service._user_data_dir = user_data_dir
    monkeypatch.setattr("browser_harness.admin.restart_daemon", lambda name=None: restarted.append(name))
    monkeypatch.setattr(service, "_session_process_pids", lambda: [201, 202])
    monkeypatch.setattr(service, "_terminate_session_pid", lambda pid: killed.append(pid))

    service._cleanup_stale_session()

    assert restarted == ["pluralsight-author"]
    assert killed == [201, 202]
    for path in lock_paths:
        assert not path.exists()


def test_browser_open_surfaces_stale_cleanup_failure(tmp_path, monkeypatch):
    service = BrowserHarnessService("pluralsight-author")
    monkeypatch.setattr(
        service,
        "_cleanup_stale_session",
        lambda: (_ for _ in ()).throw(BrowserHarnessError("stale browser session")),
    )

    with pytest.raises(BrowserHarnessError, match="stale browser session"):
        service.browser_open(persistent_profile_dir=tmp_path / "chromium-profile")


def _prepare_open_success(service, monkeypatch):
    monkeypatch.setattr(service, "_cleanup_stale_session", lambda: None)
    monkeypatch.setattr(driver, "_find_free_port", lambda: 51312)
    monkeypatch.setattr(driver, "_wait_for_cdp", lambda port, timeout: None)
    monkeypatch.setattr(
        driver,
        "_chrome_binary",
        lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    monkeypatch.setattr(
        driver.subprocess,
        "Popen",
        lambda *args, **kwargs: _Proc(4242),
    )
    monkeypatch.setattr(service, "_start_daemon", lambda: None)
    monkeypatch.setattr(service, "_stop_daemon", lambda: None)
    monkeypatch.setattr(service, "_terminate_chrome", lambda: None)
    monkeypatch.setattr(
        service,
        "_page_info",
        lambda: {"url": "", "title": "", "console_errors": 0, "console_warnings": 0},
    )
    monkeypatch.setattr(service, "_stop_daemon", lambda: None)
    monkeypatch.setattr(service, "_terminate_chrome", lambda: None)

    class _Helpers:
        def cdp(self, *_args, **_kwargs):
            return {}

    service._bh = type("_BH", (), {"h": _Helpers()})()


def test_browser_open_serializes_same_session_until_first_owner_closes(tmp_path, monkeypatch):
    first = BrowserHarnessService("bricklink-default")
    second = BrowserHarnessService("bricklink-default")
    persistent = tmp_path / "chromium-profile"
    _prepare_open_success(first, monkeypatch)
    _prepare_open_success(second, monkeypatch)

    first.browser_open("https://example.com/one", persistent_profile_dir=persistent)

    acquired = threading.Event()

    def _open_second():
        second.browser_open("https://example.com/two", persistent_profile_dir=persistent)
        acquired.set()

    thread = threading.Thread(target=_open_second)
    thread.start()
    time.sleep(0.2)
    assert acquired.is_set() is False

    first.browser_close()
    thread.join(1.0)

    assert acquired.is_set() is True
    second.browser_close()


# ---------------- wait_for_selector / query_selector ----------------
#
# Regression guard: ``bricklink messages list`` (and every other CLI that
# combines ``BrowserAutomation`` with raw page navigation) calls Playwright-
# shaped primitives like ``page.wait_for_selector(selector, state=...)`` and
# ``page.query_selector(selector)``. Earlier ``BrowserHarnessService`` exposed
# neither; CLIs hit ``AttributeError: 'BrowserHarnessService' object has no
# attribute 'wait_for_selector'`` at runtime. These tests pin both methods'
# presence and core semantics so removing them again fails CI immediately.


def _open_service_with_eval(monkeypatch, eval_results):
    """Build a real BrowserHarnessService whose ``evaluate`` is scripted.

    ``eval_results`` is either a list (consumed in order) or a callable that
    receives the JS string and returns a value. ``_require_open`` is no-oped so
    we don't need a real daemon. Returns ``(service, calls)`` where ``calls``
    is a list of every JS string the method passed to ``evaluate``.
    """
    service = BrowserHarnessService("pluralsight-author")
    monkeypatch.setattr(service, "_require_open", lambda: None)
    calls: list[str] = []
    if callable(eval_results):
        def _evaluate(js, arg=None):
            calls.append(js)
            return eval_results(js)
    else:
        results = list(eval_results)
        def _evaluate(js, arg=None):
            calls.append(js)
            return results.pop(0)
    monkeypatch.setattr(service, "evaluate", _evaluate)
    return service, calls


def test_wait_for_selector_returns_element_when_visible_immediately(monkeypatch):
    service, calls = _open_service_with_eval(monkeypatch, [True])

    elem = service.wait_for_selector("body", state="visible", timeout=5000)

    assert elem is not None
    # Exactly one evaluate call when state is satisfied on the first poll.
    assert len(calls) == 1


def test_wait_for_selector_polls_until_state_matches(monkeypatch):
    # Three "not yet" responses, then visible.
    service, calls = _open_service_with_eval(monkeypatch, [False, False, False, True])
    monkeypatch.setattr("time.sleep", lambda _s: None)

    elem = service.wait_for_selector("a.foo", state="visible", timeout=5000)

    assert elem is not None
    assert len(calls) == 4


def test_wait_for_selector_raises_on_timeout(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, lambda _js: False)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    with pytest.raises(BrowserHarnessError, match="timed out"):
        # Tiny timeout so the loop exits even with a no-op sleep.
        service.wait_for_selector("a.missing", state="visible", timeout=1)


def test_wait_for_selector_rejects_unknown_state(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, [True])

    with pytest.raises(BrowserHarnessError, match="state must be one of"):
        service.wait_for_selector("body", state="bogus")


def test_wait_for_selector_supports_attached_state(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, [True])

    elem = service.wait_for_selector("body", state="attached", timeout=5000)
    assert elem is not None


def test_wait_for_selector_supports_detached_state(monkeypatch):
    # Element is currently attached, then on the second poll it's gone.
    service, _calls = _open_service_with_eval(monkeypatch, [True, False])
    monkeypatch.setattr("time.sleep", lambda _s: None)

    result = service.wait_for_selector(".gone", state="detached", timeout=5000)
    assert result is None


def test_query_selector_returns_element_when_present(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, [True])

    elem = service.query_selector("button.save")
    assert elem is not None


def test_query_selector_returns_none_when_absent(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, [False])

    assert service.query_selector("button.missing") is None


# ---------------------------------------------------------------------------
# Phase B1 — Detect-and-refuse on live SingletonLock
# ---------------------------------------------------------------------------


def test_cleanup_session_lock_raises_when_singletonlock_points_at_live_pid(tmp_path, monkeypatch):
    """Live SingletonLock → fail fast with PID + actionable hint."""
    service = BrowserHarnessService("pluralsight-author")
    ud = tmp_path / "ud"
    ud.mkdir()
    lock = ud / "SingletonLock"
    # Chrome's SingletonLock is a symlink whose target is "<hostname>-<pid>".
    lock.symlink_to("somehost-12345")
    monkeypatch.setattr(service, "_user_data_dir", lambda: ud)
    monkeypatch.setattr(service, "_pid_running", lambda pid: pid == 12345)

    with pytest.raises(BrowserHarnessError, match="12345"):
        service._cleanup_session_lock_files()
    # Lock must survive — it's a live session.
    assert lock.exists() or lock.is_symlink()


def test_cleanup_session_lock_deletes_when_pid_is_dead(tmp_path, monkeypatch):
    """Dead PID in SingletonLock target → lock is stale, delete it."""
    service = BrowserHarnessService("pluralsight-author")
    ud = tmp_path / "ud"
    ud.mkdir()
    lock = ud / "SingletonLock"
    lock.symlink_to("somehost-99999")
    monkeypatch.setattr(service, "_user_data_dir", lambda: ud)
    monkeypatch.setattr(service, "_pid_running", lambda pid: False)

    service._cleanup_session_lock_files()

    assert not lock.exists() and not lock.is_symlink()


def test_cleanup_session_lock_treats_unparseable_target_as_stale(tmp_path, monkeypatch):
    """If the lock target can't be parsed as <host>-<pid>, treat as stale."""
    service = BrowserHarnessService("pluralsight-author")
    ud = tmp_path / "ud"
    ud.mkdir()
    lock = ud / "SingletonLock"
    lock.symlink_to("garbage")
    monkeypatch.setattr(service, "_user_data_dir", lambda: ud)
    # _pid_running should NOT be called when parsing fails.
    monkeypatch.setattr(
        service,
        "_pid_running",
        lambda pid: (_ for _ in ()).throw(AssertionError("pid check skipped for unparseable")),
    )

    service._cleanup_session_lock_files()

    assert not lock.exists() and not lock.is_symlink()


# ---------------------------------------------------------------------------
# Phase C2 — browser_open accepts persistent_profile_dir; _user_data_dir is
# the resolved attribute. _session_process_pids filters against it.
# ---------------------------------------------------------------------------


def test_browser_open_uses_persistent_profile_dir_as_chrome_user_data_dir(tmp_path, monkeypatch):
    service = BrowserHarnessService("bricklink-default")
    persistent = tmp_path / "chromium-profile"
    captured_argv: list = []

    monkeypatch.setattr(service, "_cleanup_stale_session", lambda: None)
    monkeypatch.setattr(driver, "_find_free_port", lambda: 51313)
    monkeypatch.setattr(driver, "_wait_for_cdp", lambda port, timeout: None)
    monkeypatch.setattr(driver, "_chrome_binary", lambda: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    def _popen(args, **kwargs):
        captured_argv.append(list(args))
        return _Proc(4243)

    monkeypatch.setattr(driver.subprocess, "Popen", _popen)
    monkeypatch.setattr(service, "_start_daemon", lambda: None)
    monkeypatch.setattr(
        service,
        "_page_info",
        lambda: {"url": "", "title": "", "console_errors": 0, "console_warnings": 0},
    )

    class _Helpers:
        def cdp(self, *_a, **_k):
            pass

    service._bh = type("_BH", (), {"h": _Helpers()})()

    service.browser_open("https://example.com", persistent_profile_dir=persistent)
    service.browser_close()

    assert captured_argv, "Popen must have been invoked"
    cmd = " ".join(captured_argv[0])
    parsed = service._command_user_data_dir(cmd)
    assert parsed == str(persistent)


def test_session_process_pids_filters_against_persistent_profile_dir(tmp_path, monkeypatch):
    service = BrowserHarnessService("bricklink-default")
    persistent = tmp_path / "chromium-profile"
    other = tmp_path / "elsewhere"
    # After browser_open the service caches its resolved user_data_dir as
    # ``_user_data_dir`` (attribute, NOT method). Simulate by setting it.
    service._user_data_dir = persistent
    monkeypatch.setattr(
        service,
        "_list_process_commands",
        lambda: [
            (201, "S", f"chrome --user-data-dir={persistent}"),
            (202, "S", f"chrome --user-data-dir={other}"),
            (203, "S", "chrome"),
            (204, "Z", f"chrome --user-data-dir={persistent}"),
        ],
    )

    assert service._session_process_pids() == [201]


# ---------------------------------------------------------------------------
# Phase D1 — service receives an already-safe daemon key
# ---------------------------------------------------------------------------


def test_service_uses_session_name_for_runtime_dir_and_bu_name(monkeypatch):
    captured_env: dict = {}
    captured_runtime: list = []

    real_ensure = driver._ensure_runtime_dir

    def _spy_ensure(session):
        captured_runtime.append(session)
        return real_ensure(session)

    monkeypatch.setattr(driver, "_ensure_runtime_dir", _spy_ensure)

    service = BrowserHarnessService("bricklink-default")

    assert captured_runtime == ["bricklink-default"]
    # _start_daemon will read self.session into BU_NAME. Patch ensure_daemon
    # to capture the env dict it would receive.
    service._cdp_port = 1234

    def _fake_ensure_daemon(name, env):
        captured_env["name"] = name
        captured_env["BU_NAME"] = env.get("BU_NAME")
        captured_env["BH_RUNTIME_DIR"] = env.get("BH_RUNTIME_DIR")

    monkeypatch.setattr("browser_harness.admin.ensure_daemon", _fake_ensure_daemon)
    service._start_daemon()

    assert captured_env["name"] == "bricklink-default"
    assert captured_env["BU_NAME"] == "bricklink-default"


def test_service_does_not_re_sanitize_already_safe_key(monkeypatch):
    """The caller (auth.py) applies ``_safe_daemon_key`` before constructing
    the service. The service must not double-hash a key that is already
    in the safe form ``bh-<sha8>``.
    """
    key = "bh-deadbeef"
    service = BrowserHarnessService(key)
    assert service.session == key


# =====================================================================
# Regression tests for `cookie_list()` — see Known Issue:
# "cookie_list used page-scoped Network.getCookies instead of
# Network.getAllCookies, so the persistent profile's cookies were
# invisible when the current page URL was about:blank or a redirect
# intermediate, causing BrowserAuthState.from_config to raise
# 'No browser session for <tool>' on a valid logged-in profile."
# =====================================================================

def test_cookie_list_calls_get_all_cookies_not_get_cookies():
    """``cookie_list()`` must use ``Network.getAllCookies`` (browser-
    wide) — never ``Network.getCookies`` (current-URL scoped). Cookies
    in the persistent profile span many domains, and the current page
    URL is irrelevant to the consumer's needs.
    """
    service = BrowserHarnessService("test-session")
    service._opened = True
    calls: list[str] = []

    class _Helpers:
        def cdp(self, method, *_args, **_kwargs):
            calls.append(method)
            if method == "Network.getAllCookies":
                return {"cookies": [{"name": "a", "value": "1", "domain": ".example.com"}]}
            if method == "Network.getCookies":
                return {"cookies": []}
            return {}

    service._bh = type("_BH", (), {"h": _Helpers()})()

    cookies = service.cookie_list()

    assert calls == ["Network.getAllCookies"], (
        f"cookie_list must call Network.getAllCookies, called {calls}"
    )
    assert len(cookies) == 1
    assert cookies[0]["name"] == "a"


def test_cookie_list_raises_when_browser_not_opened():
    """``cookie_list`` must fail loudly when called before
    ``browser_open()`` — fail-fast policy, no silent empty list.
    """
    service = BrowserHarnessService("test-session")
    assert service._opened is False
    with pytest.raises(BrowserHarnessError) as excinfo:
        service.cookie_list()
    assert "No browser open" in str(excinfo.value)


def test_cookie_list_propagates_cdp_errors_no_silent_fallback():
    """``cookie_list`` must propagate underlying CDP failures — the old
    ``except Exception: return []`` made every CDP problem look like
    'no cookies' and produced misleading 'No browser session' errors
    downstream.
    """
    service = BrowserHarnessService("test-session")
    service._opened = True

    class _Helpers:
        def cdp(self, *_args, **_kwargs):
            raise RuntimeError("daemon socket closed")

    service._bh = type("_BH", (), {"h": _Helpers()})()

    with pytest.raises(RuntimeError) as excinfo:
        service.cookie_list()
    assert "daemon socket closed" in str(excinfo.value)


def test_cookie_list_rejects_non_dict_payload():
    """Unexpected CDP payload shape must raise — never silently coerce
    to ``[]``.
    """
    service = BrowserHarnessService("test-session")
    service._opened = True

    class _Helpers:
        def cdp(self, *_args, **_kwargs):
            return "unexpected string payload"

    service._bh = type("_BH", (), {"h": _Helpers()})()

    with pytest.raises(BrowserHarnessError) as excinfo:
        service.cookie_list()
    assert "unexpected payload" in str(excinfo.value)


def test_drain_events_returns_buffered_events():
    service = BrowserHarnessService("test-session")
    service._opened = True

    class _Helpers:
        def drain_events(self):
            return [{"method": "Network.requestWillBeSent", "params": {"requestId": "1"}}]

    service._bh = type("_BH", (), {"h": _Helpers()})()

    assert service.drain_events() == [
        {"method": "Network.requestWillBeSent", "params": {"requestId": "1"}}
    ]


def test_wait_for_network_idle_delegates_to_helper():
    service = BrowserHarnessService("test-session")
    service._opened = True
    calls: list[tuple[float, int]] = []

    class _Helpers:
        def wait_for_network_idle(self, timeout, idle_ms):
            calls.append((timeout, idle_ms))
            return True

    service._bh = type("_BH", (), {"h": _Helpers()})()

    assert service.wait_for_network_idle(timeout=12.5, idle_ms=900) is True
    assert calls == [(12.5, 900)]
