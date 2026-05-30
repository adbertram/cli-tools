"""Unit tests for Apple interactive auth flow helpers."""

from __future__ import annotations

import itertools

import pytest

from apple_cli import auth_capture
from cli_tools_shared.auth import BrowserAutomationError


class _FakePage:
    def __init__(self, *, url: str = "https://idmsa.apple.com/IDMSWebAuth/signin", body_text: str = ""):
        self.url = url
        self.body_text = body_text
        self.wait_calls: list[int] = []
        self.frame_values: dict[object, object] = {}

    def evaluate_in_iframe(self, _url_substr: str, js: str, arg=None):
        key = (js, repr(arg))
        if key in self.frame_values:
            return self.frame_values[key]
        if js in self.frame_values:
            return self.frame_values[js]
        if js.strip().startswith("() => document.body ?"):
            return self.body_text
        return None

    def evaluate(self, js: str):
        if js.strip().startswith("() => document.body ?"):
            return self.body_text
        return None

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_calls.append(ms)


class _FakeBrowser:
    def __init__(self, results):
        self.LOGIN_TIMEOUT = 900
        self._results = iter(results)

    def _check_auth(self, _page) -> bool:
        return next(self._results)


def test_detect_apple_auth_stage_reports_authenticated_from_top_url():
    page = _FakePage(url="https://reportaproblem.apple.com/?s=6")

    state = auth_capture._detect_apple_auth_stage(page)

    assert state["stage"] == "authenticated"
    assert state["invalid_code"] is False


def test_detect_apple_auth_stage_reports_sign_in_form():
    page = _FakePage(body_text="Sign in to your Apple Account")
    page.frame_values = {
        auth_capture._HAS_SIGN_IN_FORM_JS: True,
        auth_capture._VERIFICATION_INPUTS_JS: False,
        auth_capture._HAS_SMS_OPTIONS_JS: False,
        auth_capture._HAS_SMS_PROMPT_JS: False,
    }

    state = auth_capture._detect_apple_auth_stage(page)

    assert state["stage"] == "signin_form"
    assert state["invalid_code"] is False


def test_detect_apple_auth_stage_prefers_sms_options_over_generic_otp():
    page = _FakePage(
        body_text="Two-Factor Authentication Can't get to your devices? Text code to (***) ***-**58"
    )
    page.frame_values = {
        auth_capture._HAS_SIGN_IN_FORM_JS: False,
        auth_capture._VERIFICATION_INPUTS_JS: True,
        auth_capture._HAS_SMS_OPTIONS_JS: True,
        auth_capture._HAS_SMS_PROMPT_JS: False,
    }

    state = auth_capture._detect_apple_auth_stage(page)

    assert state["stage"] == "sms_options"


def test_detect_apple_auth_stage_reports_sms_code_and_invalid_flag():
    page = _FakePage(
        body_text="Two-Factor Authentication Enter the verification code sent as a message to (***) ***-**58. Incorrect verification code."
    )
    page.frame_values = {
        auth_capture._HAS_SIGN_IN_FORM_JS: False,
        auth_capture._VERIFICATION_INPUTS_JS: True,
        auth_capture._HAS_SMS_OPTIONS_JS: False,
        auth_capture._HAS_SMS_PROMPT_JS: True,
    }

    state = auth_capture._detect_apple_auth_stage(page)

    assert state["stage"] == "sms_code"
    assert state["invalid_code"] is True


def test_prompt_for_apple_verification_code_accepts_sms_keyword(monkeypatch):
    monkeypatch.setattr(auth_capture, "_readline_with_timeout", lambda prompt, timeout: "sms\n")

    code = auth_capture._prompt_for_apple_verification_code(
        "trusted Apple device",
        auth_capture.APPLE_CODE_TIMEOUT_SECONDS,
        allow_sms=True,
    )

    assert code == "sms"


def test_prompt_for_apple_verification_code_retries_until_six_digits(monkeypatch):
    values = iter(["12\n", "123 456\n"])
    monkeypatch.setattr(auth_capture, "_readline_with_timeout", lambda prompt, timeout: next(values))

    code = auth_capture._prompt_for_apple_verification_code(
        "trusted Apple device",
        auth_capture.APPLE_CODE_TIMEOUT_SECONDS,
    )

    assert code == "123456"


def test_request_text_message_code_uses_alt_options_when_needed(monkeypatch):
    page = _FakePage()
    clicked: list[tuple[str, tuple[str, ...] | str]] = []

    monkeypatch.setattr(auth_capture, "_detect_apple_auth_stage", lambda page: {"stage": "trusted_device_code"})
    monkeypatch.setattr(
        auth_capture,
        "_click_auth_frame_button",
        lambda page, button_id: clicked.append(("id", button_id)) or True,
    )
    monkeypatch.setattr(
        auth_capture,
        "_click_text_matching_button",
        lambda page, include, exclude=(): clicked.append(("text", include)) or (include == (r"text code to",)),
    )

    assert auth_capture._request_text_message_code(page) is True
    assert clicked == [
        ("text", (r"didn.t get a code", r"can.t get to your devices")),
        ("id", "alt-options-btn"),
        ("text", (r"text code to",)),
    ]
    assert page.wait_calls == [1000]


def test_wait_for_apple_interactive_auth_prompts_for_trusted_device_code(monkeypatch):
    browser = _FakeBrowser([False, False, True])
    page = _FakePage(body_text="Two-Factor Authentication")
    prompts: list[tuple[str, int, bool]] = []
    entered_codes: list[str] = []

    states = itertools.chain(
        [{"stage": "trusted_device_code", "invalid_code": False, "body_text": "Two-Factor Authentication"}],
        itertools.repeat({"stage": "waiting", "invalid_code": False, "body_text": ""}),
    )
    monkeypatch.setattr(auth_capture, "_detect_apple_auth_stage", lambda page: next(states))
    monkeypatch.setattr(
        auth_capture,
        "_prompt_for_apple_verification_code",
        lambda source, timeout_seconds, allow_sms=False: prompts.append((source, timeout_seconds, allow_sms)) or "654321",
    )
    monkeypatch.setattr(auth_capture, "_enter_apple_verification_code", lambda page, code: entered_codes.append(code))

    auth_capture._wait_for_apple_interactive_auth(browser, page)

    assert prompts == [("trusted Apple device", auth_capture.APPLE_CODE_TIMEOUT_SECONDS, True)]
    assert entered_codes == ["654321"]
    assert 1500 in page.wait_calls


def test_wait_for_apple_interactive_auth_raises_when_sms_option_missing(monkeypatch):
    browser = _FakeBrowser([False, False, False])
    page = _FakePage(body_text="Two-Factor Authentication")

    monkeypatch.setattr(
        auth_capture,
        "_detect_apple_auth_stage",
        lambda page: {"stage": "trusted_device_code", "invalid_code": False, "body_text": "Two-Factor Authentication"},
    )
    monkeypatch.setattr(
        auth_capture,
        "_prompt_for_apple_verification_code",
        lambda source, timeout_seconds, allow_sms=False: "sms",
    )
    monkeypatch.setattr(auth_capture, "_request_text_message_code", lambda page: False)

    with pytest.raises(BrowserAutomationError, match="text-message verification option"):
        auth_capture._wait_for_apple_interactive_auth(browser, page)
