from browser_harness import admin


# --- _is_transient_dedicated_chrome_timeout -------------------------------


def test_transient_timeout_matches_daemon_bu_cdp_url_unreachable_message():
    msg = (
        "fatal: BU_CDP_URL=http://127.0.0.1:60977 unreachable after 60s: "
        "timed out -- is the dedicated automation Chrome running?"
    )
    assert admin._is_transient_dedicated_chrome_timeout(msg) is True


def test_transient_timeout_does_not_match_unrelated_messages():
    assert admin._is_transient_dedicated_chrome_timeout("") is False
    assert admin._is_transient_dedicated_chrome_timeout(None) is False
    assert admin._is_transient_dedicated_chrome_timeout("CDP WS handshake failed: boom") is False


def test_transient_timeout_and_inspect_prompt_are_mutually_exclusive_classes():
    """The two retry classifiers must not both fire for the same message --
    ensure_daemon() picks one branch (chrome://inspect prompt vs. bare
    retry) and they target different failure modes."""
    dedicated_chrome_msg = (
        "fatal: BU_CDP_URL=http://127.0.0.1:60977 unreachable after 60s: "
        "timed out -- is the dedicated automation Chrome running?"
    )
    inspect_prompt_msg = "DevToolsActivePort not found in [...]"
    assert admin._is_transient_dedicated_chrome_timeout(dedicated_chrome_msg) is True
    assert admin._needs_chrome_remote_debugging_prompt(dedicated_chrome_msg) is False
    assert admin._is_transient_dedicated_chrome_timeout(inspect_prompt_msg) is False
    assert admin._needs_chrome_remote_debugging_prompt(inspect_prompt_msg) is True


# --- ensure_daemon() retry wiring ------------------------------------------


class _FakeProc:
    def poll(self):
        return 0  # already exited, so ensure_daemon's poll loop breaks fast


def test_ensure_daemon_retries_once_on_transient_dedicated_chrome_timeout(monkeypatch):
    """A first attempt whose daemon subprocess logs the BU_CDP_URL timeout
    (Chrome was confirmed alive moments earlier by the caller, but the
    daemon's own poll lost the race under host load) must get a second
    attempt spawned -- not a hard failure and not the chrome://inspect
    permission-prompt flow, which targets a different browser instance."""
    calls = {"popen": 0, "restart": [], "inspect_opened": False}

    monkeypatch.setattr(admin, "daemon_alive", lambda name=None: False)

    def fake_popen(*args, **kwargs):
        calls["popen"] += 1
        return _FakeProc()

    monkeypatch.setattr(admin.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(admin, "restart_daemon", lambda name=None: calls["restart"].append(name))
    monkeypatch.setattr(admin, "_open_chrome_inspect", lambda: calls.__setitem__("inspect_opened", True))

    timeout_msg = (
        "fatal: BU_CDP_URL=http://127.0.0.1:60977 unreachable after 60s: "
        "timed out -- is the dedicated automation Chrome running?"
    )
    monkeypatch.setattr(admin, "_log_tail", lambda name=None: timeout_msg)

    try:
        admin.ensure_daemon(wait=0.01, name="brickowl-default", env={})
    except RuntimeError as exc:
        assert str(exc) == timeout_msg
    else:
        raise AssertionError("expected ensure_daemon to exhaust its retry and raise")

    assert calls["popen"] == 2, "expected one retry (two daemon subprocess spawns total)"
    assert calls["restart"] == ["brickowl-default"]
    assert calls["inspect_opened"] is False, "chrome://inspect is the wrong browser instance for this failure mode"
