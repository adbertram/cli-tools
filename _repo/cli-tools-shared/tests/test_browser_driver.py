from pathlib import Path
import threading
import time

import pytest

from cli_tools_shared.browser import BrowserHarnessError
from cli_tools_shared.browser.driver import BrowserHarnessService
from cli_tools_shared.browser._elements import _ServiceElement, _scoped_css_js
from cli_tools_shared.browser._js_fragments import _fill_js
import cli_tools_shared.browser.driver as driver


class _Proc:
    def __init__(self, pid: int):
        self.pid = pid


def test_browser_open_cleans_same_session_state_before_launch(tmp_path, monkeypatch):
    service = BrowserHarnessService("sample-browser-session")
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
    monkeypatch.setattr(service, "_request_browser_close", lambda: events.append("graceful-close"))
    monkeypatch.setattr(service, "_stop_daemon", lambda: events.append("stop"))
    monkeypatch.setattr(service, "_terminate_chrome", lambda: events.append("terminate"))
    monkeypatch.setattr(service, "_session_process_pids", lambda: [])

    class _Helpers:
        def cdp(self, *_args, **_kwargs):
            events.append("cdp")

        def goto_url(self, url):
            events.append(f"goto:{url}")

        def wait_for_load(self, timeout):
            events.append(f"load:{timeout}")

    service._bh = type("_BH", (), {"h": _Helpers()})()

    service.browser_open("https://example.com/dashboard", persistent_profile_dir=persistent)
    service.browser_close()

    assert events == [
        "cleanup",
        "popen",
        "wait:51312",
        "daemon",
        "cdp",
        "goto:https://example.com/dashboard",
        f"load:{service.default_timeout}",
        "graceful-close",
        "stop",
        "terminate",
    ]


def test_session_process_pids_match_only_same_session_user_data_dir(tmp_path, monkeypatch):
    service = BrowserHarnessService("sample-browser-session")
    session_dir = tmp_path / "ud-sample-browser-session"
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


def test_macos_app_launch_uses_new_instance_command():
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    args = [
        chrome,
        "--remote-debugging-port=51234",
        "--user-data-dir=/tmp/profile",
        "https://example.com",
    ]

    command = driver._chrome_launch_command(chrome, args)

    if driver.sys.platform == "darwin":
        assert command == [
            "/usr/bin/open",
            "-na",
            "/Applications/Google Chrome.app",
            "--args",
            "--remote-debugging-port=51234",
            "--user-data-dir=/tmp/profile",
            "https://example.com",
        ]
    else:
        assert command == args


def test_cleanup_stale_session_stops_daemon_kills_matching_pids_and_clears_locks(tmp_path, monkeypatch):
    service = BrowserHarnessService("sample-browser-session")
    user_data_dir = tmp_path / "ud-sample-browser-session"
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

    assert restarted == ["sample-browser-session"]
    assert killed == [201, 202]
    for path in lock_paths:
        assert not path.exists()


def test_browser_open_surfaces_stale_cleanup_failure(tmp_path, monkeypatch):
    service = BrowserHarnessService("sample-browser-session")
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
    monkeypatch.setattr(service, "_request_browser_close", lambda: None)
    monkeypatch.setattr(service, "_stop_daemon", lambda: None)
    monkeypatch.setattr(service, "_terminate_chrome", lambda: None)
    monkeypatch.setattr(service, "_session_process_pids", lambda: [])
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

        def goto_url(self, _url):
            return None

        def wait_for_load(self, timeout):
            return None

    service._bh = type("_BH", (), {"h": _Helpers()})()


def test_browser_open_navigates_requested_url_via_daemon(tmp_path, monkeypatch):
    service = BrowserHarnessService("sample-browser-session")
    persistent = tmp_path / "chromium-profile"
    events: list[str] = []
    _prepare_open_success(service, monkeypatch)

    class _Helpers:
        def cdp(self, *_args, **_kwargs):
            events.append("cdp")
            return {}

        def goto_url(self, url):
            events.append(f"goto:{url}")

        def wait_for_load(self, timeout):
            events.append(f"load:{timeout}")

    service._bh = type("_BH", (), {"h": _Helpers()})()

    service.browser_open("https://example.com/dashboard", persistent_profile_dir=persistent)
    service.browser_close()

    assert events == [
        "cdp",
        "goto:https://example.com/dashboard",
        f"load:{service.default_timeout}",
    ]


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
    service = BrowserHarnessService("sample-browser-session")
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


def test_page_eval_wraps_evaluate_result(monkeypatch):
    service = BrowserHarnessService("sample-browser-session")
    monkeypatch.setattr(service, "_require_open", lambda: None)
    monkeypatch.setattr(
        service,
        "evaluate",
        lambda js, arg=None: {"ok": True, "arg": arg, "js": js},
    )

    result = service.page_eval("() => ({ ok: true })", {"x": 1})

    assert result == {
        "result": {
            "ok": True,
            "arg": {"x": 1},
            "js": "() => ({ ok: true })",
        }
    }


def test_element_select_option_supports_label(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, [True, None])

    elem = service.query_selector("select.reason")
    elem.select_option(label="Item was missing or unsatisfactory")

    assert "criterion = \"label\"" in _calls[1]
    assert "Item was missing or unsatisfactory" in _calls[1]
    assert "dispatchEvent(new Event('change'" in _calls[1]


def test_locator_select_option_supports_value(monkeypatch):
    service, calls = _open_service_with_eval(monkeypatch, [None])

    service.locator("select.action").select_option("unread")

    assert "criterion = \"value\"" in calls[0]
    assert "unread" in calls[0]


def test_page_content_returns_serialized_html(monkeypatch):
    service, calls = _open_service_with_eval(monkeypatch, ["<html><body>hi</body></html>"])

    assert service.content() == "<html><body>hi</body></html>"
    assert "outerHTML" in calls[0]


def test_page_content_coerces_non_string_to_empty(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, [None])

    assert service.content() == ""


def test_page_select_option_resolves_selector_and_label(monkeypatch):
    service, calls = _open_service_with_eval(monkeypatch, [None])

    service.select_option('select[name*="type"]', label="User Specific Coupon")

    assert "document.querySelector(" in calls[0]
    assert 'select[name*=\\"type\\"]' in calls[0]
    assert "criterion = \"label\"" in calls[0]
    assert "User Specific Coupon" in calls[0]


def test_page_fill_resolves_selector_and_text(monkeypatch):
    service, calls = _open_service_with_eval(monkeypatch, [None])

    service.fill('input[name*="recipient"]', "chuchlama")

    assert "document.querySelector(" in calls[0]
    assert 'input[name*=\\"recipient\\"]' in calls[0]
    assert "chuchlama" in calls[0]


def test_page_title_returns_document_title(monkeypatch):
    service, calls = _open_service_with_eval(monkeypatch, ["Coupons - Brick Owl"])

    assert service.title() == "Coupons - Brick Owl"
    assert "document.title" in calls[0]


def test_page_title_coerces_non_string_to_empty(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, [None])

    assert service.title() == ""


# ---------------------------------------------------------------------------
# Phase B1 — Detect-and-refuse on live SingletonLock
# ---------------------------------------------------------------------------


def test_cleanup_session_lock_raises_when_singletonlock_points_at_live_pid(tmp_path, monkeypatch):
    """Live SingletonLock → fail fast with PID + actionable hint."""
    service = BrowserHarnessService("sample-browser-session")
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
    service = BrowserHarnessService("sample-browser-session")
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
    service = BrowserHarnessService("sample-browser-session")
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
    monkeypatch.setattr(service, "_stop_daemon", lambda: None)
    monkeypatch.setattr(service, "_terminate_chrome", lambda: None)
    monkeypatch.setattr(service, "_session_process_pids", lambda: [])
    monkeypatch.setattr(
        service,
        "_page_info",
        lambda: {"url": "", "title": "", "console_errors": 0, "console_warnings": 0},
    )

    class _Helpers:
        def cdp(self, *_a, **_k):
            pass

        def goto_url(self, _url):
            pass

        def wait_for_load(self, timeout):
            pass

    service._bh = type("_BH", (), {"h": _Helpers()})()

    service.browser_open("https://example.com", persistent_profile_dir=persistent)
    service.browser_close()

    assert captured_argv, "Popen must have been invoked"
    cmd = " ".join(captured_argv[0])
    parsed = service._command_user_data_dir(cmd)
    assert parsed == str(persistent)
    assert "--restore-last-session" in captured_argv[0]


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


def test_iframe_target_delegates_to_helper():
    service = BrowserHarnessService("test-session")
    service._opened = True
    calls: list[str] = []

    class _Helpers:
        def iframe_target(self, url_substr):
            calls.append(url_substr)
            return "frame-123"

    service._bh = type("_BH", (), {"h": _Helpers()})()

    assert service.iframe_target("appleauth/auth/authorize/signin") == "frame-123"
    assert calls == ["appleauth/auth/authorize/signin"]


def test_evaluate_in_iframe_uses_helper_target_id(monkeypatch):
    service = BrowserHarnessService("test-session")
    service._opened = True
    helper_calls: list[tuple[str, str]] = []

    class _Helpers:
        def iframe_target(self, url_substr):
            helper_calls.append(("iframe_target", url_substr))
            return "frame-123"

        def js(self, expression, target_id=None):
            helper_calls.append(("js", target_id))
            return {"ok": True, "expression": expression}

    service._bh = type("_BH", (), {"h": _Helpers()})()

    result = service.evaluate_in_iframe(
        "appleauth/auth/authorize/signin",
        "(arg) => ({ ok: true, value: arg.value })",
        {"value": 7},
    )

    assert result["ok"] is True
    assert helper_calls == [
        ("iframe_target", "appleauth/auth/authorize/signin"),
        ("js", "frame-123"),
    ]


def test_evaluate_in_iframe_falls_back_to_frame_tree_when_helper_has_no_target():
    service = BrowserHarnessService("test-session")
    service._opened = True
    calls: list[tuple[str, object]] = []

    class _Helpers:
        def iframe_target(self, url_substr):
            calls.append(("iframe_target", url_substr))
            return None

        def cdp(self, method, **kwargs):
            calls.append((method, kwargs))
            if method == "Page.getFrameTree":
                return {
                    "frameTree": {
                        "frame": {"id": "root", "url": "https://idmsa.apple.com/IDMSWebAuth/signin"},
                        "childFrames": [
                            {
                                "frame": {
                                    "id": "child-1",
                                    "url": "https://idmsa.apple.com/appleauth/auth/authorize/signin?frame_id=abc",
                                }
                            }
                        ],
                    }
                }
            if method == "Page.createIsolatedWorld":
                assert kwargs["frameId"] == "child-1"
                return {"executionContextId": 99}
            if method == "Runtime.evaluate":
                assert kwargs["contextId"] == 99
                return {"result": {"value": {"stage": "trusted_device_code"}}}
            raise AssertionError(f"unexpected CDP method: {method}")

    service._bh = type("_BH", (), {"h": _Helpers()})()

    result = service.evaluate_in_iframe(
        "appleauth/auth/authorize/signin",
        "() => ({ stage: 'trusted_device_code' })",
    )

    assert result == {"stage": "trusted_device_code"}


def test_fill_js_uses_native_input_value_setter():
    js = _fill_js("secret")

    assert "Object.getOwnPropertyDescriptor" in js
    assert "HTMLInputElement.prototype" in js
    assert "HTMLTextAreaElement.prototype" in js
    assert "__cliToolsDescriptor.set.call" in js
    assert "dispatchEvent(new Event('input'" in js
    assert "dispatchEvent(new Event('change'" in js


def test_service_element_fill_uses_native_setter_path(monkeypatch):
    service = BrowserHarnessService("test-session")
    evaluated: list[str] = []

    monkeypatch.setattr(service, "evaluate", lambda js, arg=None: evaluated.append(js))

    _ServiceElement(service, css='input[name="email"]').fill("user@example.com")

    assert evaluated, "fill() should evaluate JS against the element"
    js = evaluated[0]
    assert "Object.getOwnPropertyDescriptor" in js
    assert "__cliToolsDescriptor.set.call" in js


def test_service_locator_text_queries_delegate_to_first_element(monkeypatch):
    service = BrowserHarnessService("test-session")
    calls: list[str] = []

    def _evaluate(js, arg=None):
        calls.append(js)
        if "textContent" in js:
            return "Example text"
        if "getAttribute" in js:
            return "3"
        if "'value' in el" in js:
            return "typed value"
        return None

    monkeypatch.setattr(service, "evaluate", _evaluate)
    locator = service.locator('[role="treeitem"]')

    assert locator.text_content() == "Example text"
    assert locator.inner_text() == "Example text"
    assert locator.get_attribute("aria-level") == "3"
    assert locator.input_value() == "typed value"
    assert len(calls) == 4


def test_service_element_text_queries_delegate_to_live_dom(monkeypatch):
    service = BrowserHarnessService("test-session")
    calls: list[str] = []

    def _evaluate(js, arg=None):
        calls.append(js)
        if "textContent" in js:
            return "Example text"
        if "getAttribute" in js:
            return "value"
        if "'value' in el" in js:
            return "typed value"
        return None

    monkeypatch.setattr(service, "evaluate", _evaluate)
    element = _ServiceElement(service, css="input[name='email']")

    assert element.text_content() == "Example text"
    assert element.inner_text() == "Example text"
    assert element.get_attribute("data-test") == "value"
    assert element.input_value() == "typed value"
    assert len(calls) == 4


def test_service_element_supports_scoped_locator_chaining():
    service = BrowserHarnessService("test-session")
    element = _ServiceElement(service, css="section")

    child = element.locator("input.bulkCheck")
    by_role = element.get_by_role("button", name="Submit")
    by_placeholder = element.get_by_placeholder("Email")
    filtered = element.filter(has_text="Nested")

    assert "[document.querySelector(\"section\")].filter(Boolean)" in child._find_js
    assert "[document.querySelector(\"section\")].filter(Boolean)" in by_role._find_js
    assert 'placeholder=\\"Email\\"' in by_placeholder._find_js
    assert "[document.querySelector(\"section\")].filter(Boolean)" in filtered._find_js


def test_scoped_css_js_prefixes_scope_for_leading_combinator():
    js = _scoped_css_js("baseJs", "> div")
    assert ':scope > div' in js


# ---------------------------------------------------------------------------
# page.context.request.get — authenticated in-page fetch
#
# Regression guard: brickowl ``download_attachments`` calls
# ``self._page.context.request.get(url)`` to download logged-in-only message
# attachments. ``BrowserHarnessService`` exposed neither ``context`` nor the
# request shim; callers hit ``AttributeError: 'BrowserHarnessService' object
# has no attribute 'context'``. These tests pin the request shim's presence
# and the .ok/.status/.status_text/.body() contract.
# ---------------------------------------------------------------------------


def test_context_request_get_evaluates_authenticated_fetch(monkeypatch):
    import base64

    payload = b"\x89PNG\r\n\x1a\nbinary-bytes"
    fetch_result = {
        "ok": True,
        "status": 200,
        "statusText": "OK",
        "bodyBase64": base64.b64encode(payload).decode("ascii"),
    }
    service, calls = _open_service_with_eval(monkeypatch, [fetch_result])

    resp = service.context.request.get("https://www.brickowl.com/attach/1")

    # The GET must run as an in-page fetch (inherits the auth session) and
    # forward the URL as the evaluate arg.
    assert "fetch(" in calls[0]
    assert "credentials: 'include'" in calls[0]
    assert resp.ok is True
    assert resp.status == 200
    assert resp.status_text == "OK"
    assert resp.body() == payload


def test_context_request_get_maps_non_ok_response(monkeypatch):
    fetch_result = {
        "ok": False,
        "status": 404,
        "statusText": "Not Found",
        "bodyBase64": "",
    }
    service, _calls = _open_service_with_eval(monkeypatch, [fetch_result])

    resp = service.context.request.get("https://www.brickowl.com/missing")

    assert resp.ok is False
    assert resp.status == 404
    assert resp.status_text == "Not Found"
    assert resp.body() == b""


def test_context_request_get_rejects_non_dict_result(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, [None])

    with pytest.raises(BrowserHarnessError, match="unexpected fetch result"):
        service.context.request.get("https://www.brickowl.com/x")


def test_context_request_get_rejects_empty_url(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, [{}])

    with pytest.raises(BrowserHarnessError, match="must be non-empty"):
        service.context.request.get("")


def test_context_requires_open():
    service = BrowserHarnessService("test-session")
    assert service._opened is False
    with pytest.raises(BrowserHarnessError, match="No browser open"):
        _ = service.context


# ---------------------------------------------------------------------------
# page.once("dialog", ...) — one-time dialog auto-accept
#
# Regression guard: brickowl ``_submit_refund_and_verify`` calls
# ``self._page.once("dialog", lambda dialog: dialog.accept())`` right before
# submitting a refund (Brick Owl raises a JS confirm()). The harness exposed
# no ``once``; the refund silently failed to post. These tests pin that
# ``once("dialog", ...)`` installs the page-side auto-accept and that any
# other event name fails loudly.
# ---------------------------------------------------------------------------


def test_once_dialog_installs_auto_accept(monkeypatch):
    service, calls = _open_service_with_eval(monkeypatch, [None])

    service.once("dialog", lambda dialog: dialog.accept())

    assert len(calls) == 1
    assert "window.confirm = () => true" in calls[0]
    assert "window.alert = () => {}" in calls[0]


def test_once_rejects_unsupported_event(monkeypatch):
    service, _calls = _open_service_with_eval(monkeypatch, [None])

    with pytest.raises(BrowserHarnessError, match="unsupported event"):
        service.once("response", lambda _r: None)


def test_once_requires_open():
    service = BrowserHarnessService("test-session")
    assert service._opened is False
    with pytest.raises(BrowserHarnessError, match="No browser open"):
        service.once("dialog", lambda _d: None)
