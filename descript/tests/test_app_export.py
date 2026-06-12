"""Regression tests for Descript composition export CDP connections."""

import json
import subprocess

import pytest

from descript_cli.client import ClientError
from descript_cli import app_export


def test_connect_cdp_suppresses_origin_header(monkeypatch):
    captured = {}

    def fake_create_connection(url, timeout=None, **options):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["options"] = options
        return object()

    monkeypatch.setattr(app_export.websocket, "create_connection", fake_create_connection)

    ws = app_export._connect_cdp("ws://127.0.0.1:9222/devtools/page/example", timeout=15)

    assert ws is not None
    assert captured == {
        "url": "ws://127.0.0.1:9222/devtools/page/example",
        "timeout": 15,
        "options": {"suppress_origin": True},
    }


def test_get_cdp_targets_error_includes_deterministic_preflight(monkeypatch):
    def fake_connection(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(app_export.http.client, "HTTPConnection", fake_connection)

    with pytest.raises(ClientError) as error:
        app_export._get_cdp_targets()

    message = str(error.value)
    assert "http://127.0.0.1:9222/json/version" in message
    assert 'open -na "Descript" --args --remote-debugging-port=9222' in message
    assert (
        "Then rerun the export; the CLI auto-opens the target project via its descript:// deep link."
        in message
    )


def test_dialog_state_script_has_no_backslash_escaped_quotes():
    # Intermediate quoting layers can strip backslashes, turning escaped
    # quotes into a -2741 AppleScript syntax error. Embedded quotes must use
    # the AppleScript `quote` constant instead.
    assert '\\"' not in app_export._DIALOG_STATE_SCRIPT


def test_dialog_state_script_compiles(tmp_path):
    result = subprocess.run(
        [
            "osacompile",
            "-o", str(tmp_path / "dialog_state.scpt"),
            "-e", app_export._DIALOG_STATE_SCRIPT,
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_assert_assistive_access_passes_when_probe_succeeds(monkeypatch):
    captured = {}

    def fake_run_applescript(script):
        captured["script"] = script
        return "1"

    monkeypatch.setattr(app_export, "_run_applescript", fake_run_applescript)

    app_export._assert_assistive_access()

    assert captured["script"] == (
        'tell application "System Events" to count windows of process "Descript"'
    )


def test_assert_assistive_access_fails_fast_with_grant_guidance(monkeypatch):
    def deny(_script):
        raise ClientError(
            "AppleScript error: System Events got an error: "
            "osascript is not allowed assistive access. (-25211)"
        )

    monkeypatch.setattr(app_export, "_run_applescript", deny)

    with pytest.raises(ClientError) as error:
        app_export._assert_assistive_access()

    message = str(error.value)
    assert "assistive (Accessibility) access" in message
    assert "Privacy & Security > Accessibility" in message
    assert "responsible host app" in message
    assert "-25211" in message


def test_export_checks_assistive_access_before_triggering_export(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(
        app_export, "navigate_to_composition",
        lambda _project_id, _composition_id: calls.append("navigate"),
    )

    def deny():
        calls.append("probe")
        raise ClientError("no assistive access")

    monkeypatch.setattr(app_export, "_assert_assistive_access", deny)
    monkeypatch.setattr(
        app_export, "_trigger_local_export",
        lambda _project_id: calls.append("trigger"),
    )

    with pytest.raises(ClientError, match="no assistive access"):
        app_export.export_composition_local(
            "704a7924-a66e-4e47-b115-b43d0bc24875",
            "51be1848-ce29-47f0-bc21-9427fc0f1308",
            "Inventory Page",
            tmp_path / "inventory-page.mp4",
        )

    assert calls == ["navigate", "probe"]


def test_ensure_project_open_returns_ws_without_deep_link(monkeypatch):
    monkeypatch.setattr(app_export, "_get_project_page_ws", lambda _project_id: "ws://example")

    def fail_run(*_args, **_kwargs):
        raise AssertionError("open should not be called when the project page is already visible")

    monkeypatch.setattr(app_export.subprocess, "run", fail_run)

    assert app_export._ensure_project_open("704a7924-a66e-4e47-b115-b43d0bc24875") == "ws://example"


def test_ensure_project_open_opens_deep_link_and_polls(monkeypatch):
    project_id = "704a7924-a66e-4e47-b115-b43d0bc24875"
    ws_results = iter(["", "", "ws://example"])
    captured = {}

    monkeypatch.setattr(app_export, "_get_project_page_ws", lambda _project_id: next(ws_results))
    monkeypatch.setattr(app_export.time, "sleep", lambda _seconds: None)

    class FakeResult:
        returncode = 0
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        return FakeResult()

    monkeypatch.setattr(app_export.subprocess, "run", fake_run)

    assert app_export._ensure_project_open(project_id) == "ws://example"
    assert captured["args"] == ["open", f"descript://project/{project_id}"]


def test_ensure_project_open_fails_when_deep_link_command_fails(monkeypatch):
    monkeypatch.setattr(app_export, "_get_project_page_ws", lambda _project_id: "")

    class FakeResult:
        returncode = 1
        stderr = "Unable to find application"

    monkeypatch.setattr(app_export.subprocess, "run", lambda *_args, **_kwargs: FakeResult())

    with pytest.raises(ClientError, match="Failed to open Descript deep link"):
        app_export._ensure_project_open("704a7924-a66e-4e47-b115-b43d0bc24875")


def test_ensure_project_open_times_out_when_project_never_appears(monkeypatch):
    project_id = "704a7924-a66e-4e47-b115-b43d0bc24875"
    monkeypatch.setattr(app_export, "_get_project_page_ws", lambda _project_id: "")
    monkeypatch.setattr(app_export.time, "sleep", lambda _seconds: None)

    class FakeResult:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(app_export.subprocess, "run", lambda *_args, **_kwargs: FakeResult())

    start = 100.0
    times = iter([start, start, start + 2.0])
    monkeypatch.setattr(app_export.time, "time", lambda: next(times))

    with pytest.raises(ClientError, match="did not appear in Descript within 1 seconds"):
        app_export._ensure_project_open(project_id, timeout=1)


def test_save_dialog_timeout_allows_slow_native_sheet():
    assert app_export.SAVE_DIALOG_TIMEOUT_SECONDS == 300


def test_find_save_dialog_window_index_polls_across_windows(monkeypatch):
    responses = iter(["", "2"])

    def fake_run_applescript(script):
        assert 'repeat with windowIndex from 1 to count of windows' in script
        assert 'text field "Save As:"' in script
        return next(responses)

    monkeypatch.setattr(app_export, "_run_applescript", fake_run_applescript)
    monkeypatch.setattr(app_export.time, "sleep", lambda _seconds: None)

    assert app_export._find_save_dialog_window_index(timeout=1) == 2


def test_find_save_dialog_window_index_reports_configured_timeout(monkeypatch):
    monkeypatch.setattr(app_export, "_run_applescript", lambda _script: "")
    monkeypatch.setattr(
        app_export,
        "_describe_descript_dialog_state",
        lambda: "no Descript sheets found across 1 windows",
    )
    monkeypatch.setattr(app_export.time, "sleep", lambda _seconds: None)

    start = 100.0
    times = iter([start, start, start + 0.5, start + 1.0])
    monkeypatch.setattr(app_export.time, "time", lambda: next(times))

    with pytest.raises(ClientError, match="Save dialog did not appear within 1 seconds") as error:
        app_export._find_save_dialog_window_index(timeout=1)

    assert "no Descript sheets found across 1 windows" in str(error.value)


def test_count_descript_sheets_counts_all_windows(monkeypatch):
    captured = {}

    def fake_run_applescript(script):
        captured["script"] = script
        return "3"

    monkeypatch.setattr(app_export, "_run_applescript", fake_run_applescript)

    assert app_export._count_descript_sheets() == 3
    assert 'repeat with windowIndex from 1 to count of windows' in captured["script"]


def test_wait_for_export_complete_uses_long_render_timeout(monkeypatch, tmp_path):
    output_path = tmp_path / "export.mp4"

    monkeypatch.setattr(app_export, "_count_descript_sheets", lambda: 1)
    monkeypatch.setattr(app_export.time, "sleep", lambda _seconds: None)

    start = 100.0
    times = iter([start, start, start + app_export.EXPORT_COMPLETE_TIMEOUT_SECONDS])
    monkeypatch.setattr(app_export.time, "time", lambda: next(times))

    with pytest.raises(
        ClientError,
        match=f"Export timed out after {app_export.EXPORT_COMPLETE_TIMEOUT_SECONDS} seconds",
    ):
        app_export._wait_for_export_complete(output_path, "Catalog Page")


class FakeWebSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.closed = False

    def send(self, message):
        self.sent.append(json.loads(message))

    def recv(self):
        return json.dumps(self.responses.pop(0))

    def close(self):
        self.closed = True


def test_get_visible_compositions_returns_active_descript_pages(monkeypatch):
    ws = FakeWebSocket([
        {
            "result": {
                "result": {
                    "value": {
                        "visible_name": "Inventory Page",
                        "title": "BrickBuddy Overview",
                        "url": "https://web.descript.com/704a7924-a66e-4e47-b115-b43d0bc24875/51be1",
                    }
                }
            }
        }
    ])
    monkeypatch.setattr(app_export, "_get_cdp_targets", lambda: [
        {
            "type": "page",
            "url": "https://web.descript.com/704a7924-a66e-4e47-b115-b43d0bc24875/51be1",
            "webSocketDebuggerUrl": "ws://example",
        },
        {
            "type": "page",
            "url": "about:blank",
            "webSocketDebuggerUrl": "ws://ignored",
        },
    ])
    monkeypatch.setattr(app_export, "_connect_cdp", lambda _url, timeout: ws)

    records = app_export.get_visible_compositions()

    assert records == [
        {
            "visible_name": "Inventory Page",
            "title": "BrickBuddy Overview",
            "url": "https://web.descript.com/704a7924-a66e-4e47-b115-b43d0bc24875/51be1",
            "project_id": "704a7924-a66e-4e47-b115-b43d0bc24875",
            "composition_prefix": "51be1",
        }
    ]
    assert ws.closed is True


def test_trigger_local_export_uses_cdp_mouse_dispatch(monkeypatch):
    responses = [
        {"result": {}},
        {"result": {}},
        {"result": {}},
        {
            "result": {
                "result": {
                    "value": {
                        "x": 12,
                        "y": 34,
                        "disabled": False,
                        "text": "Export",
                    }
                }
            }
        },
        {"result": {}},
        {"result": {}},
        {"result": {}},
    ]
    ws = FakeWebSocket(responses)
    monkeypatch.setattr(app_export, "_run_applescript", lambda _script: "")
    monkeypatch.setattr(app_export, "_get_project_page_ws", lambda _project_id: "ws://example")
    monkeypatch.setattr(app_export, "_connect_cdp", lambda _url, timeout: ws)
    monkeypatch.setattr(app_export.time, "sleep", lambda _seconds: None)

    app_export._trigger_local_export("704a7924-a66e-4e47-b115-b43d0bc24875")

    methods = [message["method"] for message in ws.sent]
    assert methods[-3:] == [
        "Input.dispatchMouseEvent",
        "Input.dispatchMouseEvent",
        "Input.dispatchMouseEvent",
    ]
    assert [message["params"]["type"] for message in ws.sent[-3:]] == [
        "mouseMoved",
        "mousePressed",
        "mouseReleased",
    ]


def _trigger_export_responses():
    return [
        {"result": {}},
        {"result": {}},
        {"result": {}},
        {
            "result": {
                "result": {
                    "value": {
                        "x": 12,
                        "y": 34,
                        "disabled": False,
                        "text": "Export",
                    }
                }
            }
        },
        {"result": {}},
        {"result": {}},
        {"result": {}},
    ]


def test_trigger_local_export_activates_descript_before_cdp_clicks(monkeypatch):
    calls = []
    ws = FakeWebSocket(_trigger_export_responses())

    def fake_run_applescript(script):
        calls.append(("applescript", script))
        return ""

    def fake_connect_cdp(_url, timeout):
        calls.append(("connect", _url))
        return ws

    monkeypatch.setattr(app_export, "_run_applescript", fake_run_applescript)
    monkeypatch.setattr(app_export, "_get_project_page_ws", lambda _project_id: "ws://example")
    monkeypatch.setattr(app_export, "_connect_cdp", fake_connect_cdp)
    monkeypatch.setattr(app_export.time, "sleep", lambda _seconds: None)

    app_export._trigger_local_export("704a7924-a66e-4e47-b115-b43d0bc24875")

    assert calls[0] == ("applescript", 'tell application "Descript" to activate')
    assert calls[1][0] == "connect"


def test_trigger_local_export_panel_open_is_idempotent(monkeypatch):
    ws = FakeWebSocket(_trigger_export_responses())
    monkeypatch.setattr(app_export, "_run_applescript", lambda _script: "")
    monkeypatch.setattr(app_export, "_get_project_page_ws", lambda _project_id: "ws://example")
    monkeypatch.setattr(app_export, "_connect_cdp", lambda _url, timeout: ws)
    monkeypatch.setattr(app_export.time, "sleep", lambda _seconds: None)

    app_export._trigger_local_export("704a7924-a66e-4e47-b115-b43d0bc24875")

    panel_open = ws.sent[0]
    assert panel_open["method"] == "Runtime.evaluate"
    expression = panel_open["params"]["expression"]
    # Must check for an already-open panel BEFORE clicking the trigger,
    # otherwise the click toggles an open panel closed.
    button_guard = expression.index('[data-testid="export-button"]')
    trigger_click = expression.index('[data-testid="export-popover-trigger"]')
    assert button_guard < trigger_click
    assert "return 'already-open'" in expression


def test_wait_for_stable_export_file_rejects_tiny_file(monkeypatch, tmp_path):
    output_path = tmp_path / "tiny.mp4"
    output_path.write_bytes(b"x")
    monkeypatch.setattr(app_export.time, "sleep", lambda _seconds: None)

    start = 100.0
    times = iter([start, start, start + 0.5, start + 1.0])
    monkeypatch.setattr(app_export.time, "time", lambda: next(times))

    with pytest.raises(ClientError, match="did not become stable"):
        app_export._wait_for_stable_export_file(output_path, timeout=1)


def test_wait_for_stable_export_file_accepts_repeated_nontrivial_size(monkeypatch, tmp_path):
    output_path = tmp_path / "export.mp4"
    output_path.write_bytes(b"x" * app_export.MIN_EXPORT_BYTES)
    monkeypatch.setattr(app_export.time, "sleep", lambda _seconds: None)

    app_export._wait_for_stable_export_file(output_path, timeout=1)
