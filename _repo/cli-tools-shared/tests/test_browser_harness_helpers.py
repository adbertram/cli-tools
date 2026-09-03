import base64

import pytest

from browser_harness import helpers


def test_js_accepts_explicit_keyword_arg(monkeypatch):
    calls = []

    def fake_runtime_evaluate(expression, session_id=None, await_promise=False):
        calls.append(
            {
                "expression": expression,
                "session_id": session_id,
                "await_promise": await_promise,
            }
        )
        return {"ok": True}

    monkeypatch.setattr(helpers, "_runtime_evaluate", fake_runtime_evaluate)

    assert helpers.js("(email) => ({ email })", arg="ada@example.com") == {"ok": True}
    assert calls == [
        {
            "expression": '((email) => ({ email }))("ada@example.com")',
            "session_id": None,
            "await_promise": True,
        }
    ]


def test_js_reports_second_positional_argument_is_target_id(monkeypatch):
    def fake_cdp(method, **params):
        assert method == "Target.attachToTarget"
        assert params == {"targetId": "ada@example.com", "flatten": True}
        raise RuntimeError("No target with given id found")

    monkeypatch.setattr(helpers, "cdp", fake_cdp)

    with pytest.raises(RuntimeError) as exc_info:
        helpers.js("(email) => email", "ada@example.com")

    message = str(exc_info.value)
    assert "second positional argument is target_id" in message
    assert "arg=" in message


def test_capture_screenshot_returns_path_and_writes_decoded_png(tmp_path, monkeypatch):
    png_bytes = b"\x89PNG\r\n\x1a\n"
    shot_path = tmp_path / "shot.png"

    def fake_cdp(method, **params):
        assert method == "Page.captureScreenshot"
        assert params == {"format": "png", "captureBeyondViewport": False}
        return {"data": base64.b64encode(png_bytes).decode("ascii")}

    monkeypatch.setattr(helpers, "cdp", fake_cdp)

    result = helpers.capture_screenshot(str(shot_path))

    assert result == str(shot_path)
    assert shot_path.read_bytes() == png_bytes


def test_press_key_sends_text_on_keydown_only(monkeypatch):
    """Chrome inserts a character for a text-carrying keyDown AND for a separate
    char event. Emitting both double-typed every printable key, so only keyDown
    may carry text."""
    events = []

    def fake_cdp(method, **params):
        assert method == "Input.dispatchKeyEvent"
        events.append(params)
        return {}

    monkeypatch.setattr(helpers, "cdp", fake_cdp)

    helpers.press_key("4")

    assert [event["type"] for event in events] == ["keyDown", "keyUp"]
    assert events[0]["text"] == "4"
    assert events[0]["key"] == "4"
    assert events[0]["windowsVirtualKeyCode"] == ord("4")
    assert "text" not in events[1]


def test_press_key_keeps_special_keys_untouched(monkeypatch):
    events = []

    def fake_cdp(method, **params):
        assert method == "Input.dispatchKeyEvent"
        events.append(params)
        return {}

    monkeypatch.setattr(helpers, "cdp", fake_cdp)

    helpers.press_key("Backspace")
    helpers.press_key("Enter", modifiers=8)

    assert [event["type"] for event in events] == ["keyDown", "keyUp", "keyDown", "keyUp"]
    # Backspace carries no text, so neither event may set it.
    assert "text" not in events[0] and "text" not in events[1]
    assert events[0]["windowsVirtualKeyCode"] == 8
    # Enter keeps its \r payload on the keyDown so keypress listeners still fire.
    assert events[2]["text"] == "\r"
    assert events[2]["windowsVirtualKeyCode"] == 13
    assert events[2]["modifiers"] == 8
