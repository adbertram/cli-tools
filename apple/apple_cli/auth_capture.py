"""Apple auth-login replay-context capture."""

from __future__ import annotations

import json
import re
import select
import sys
import time
from typing import Any, TextIO

from cli_tools_shared.auth import BrowserAutomationError
from cli_tools_shared.output import print_error, print_info, print_success

from .parsers import validate_request_context

PURCHASE_SEARCH_URL = "https://reportaproblem.apple.com/api/purchase/search"
APPLE_AUTH_IFRAME_URL_SUBSTR = "appleauth/auth/authorize/signin"
REQUIRED_COOKIE_NAMES = (
    "selfserv_toru",
    "user-context",
    "dslang",
    "geo",
    "site",
    "myacinfo",
    "dqsid",
)
FORBIDDEN_CAPTURED_HEADERS = {"content-length", "cookie", "host"}
APPLE_CODE_TIMEOUT_SECONDS = 300
APPLE_AUTH_POLL_SECONDS = 1.0
POST_CODE_SETTLE_SECONDS = 6.0

_ACCOUNT_BLOCKED_PATTERNS = (
    r"apple account has been disabled",
    r"account was disabled for security reasons",
    r"apple account has been locked",
    r"account is locked",
    r"account is not active",
    r"media & purchases account has been disabled",
)
_ACCOUNT_RECOVERY_PATTERNS = (
    r"account recovery",
    r"recover access",
    r"can.t use",
    r"don.t have access",
)
_SECURITY_KEY_PATTERNS = (
    r"security key",
    r"insert your security key",
    r"use your security key",
)
_DEVICE_PASSCODE_PATTERNS = (
    r"device passcode",
    r"passcode of one of your devices",
    r"enter the passcode",
)
_VERIFICATION_CODE_PATTERNS = (
    r"verification code",
    r"six-digit",
    r"6-digit",
    r"trusted device",
    r"trusted phone number",
    r"didn.t get a code",
    r"can.t get to your devices",
)
_TEXT_DELIVERY_PATTERNS = (
    r"didn.t get a code",
    r"can.t get to your devices",
)
_TEXT_MESSAGE_OPTION_PATTERNS = (
    r"text code to",
)
_TEXT_DELIVERY_EXCLUDED_PATTERNS = (
    r"voice",
    r"call",
    r"recover",
    r"recovery",
    r"can.t use",
    r"don.t have access",
)


def capture_request_context_from_page(page, config) -> dict[str, Any]:
    """Capture and persist the first live Apple purchase-search request."""
    params = _first_purchase_search_request(page.drain_events())
    if params is None:
        page.goto("https://reportaproblem.apple.com/?s=6")
        if not page.wait_for_network_idle(timeout=20.0, idle_ms=750):
            raise BrowserAutomationError("Timed out waiting for Apple purchase-history page activity.")
        params = _first_purchase_search_request(page.drain_events())
    if params is None:
        raise BrowserAutomationError(
            "Apple auth login did not observe the initial purchase-search POST request."
        )
    request = params.get("request")
    if not isinstance(request, dict):
        raise BrowserAutomationError("Apple purchase-search request event was missing request details.")

    post_data = request.get("postData")
    if not isinstance(post_data, str) or not post_data:
        raise BrowserAutomationError("Apple purchase-search request event was missing postData.")
    try:
        request_body = json.loads(post_data)
    except json.JSONDecodeError as exc:
        raise BrowserAutomationError("Apple purchase-search request postData was not valid JSON.") from exc
    if not isinstance(request_body, dict):
        raise BrowserAutomationError("Apple purchase-search request body was not an object.")

    dsid = request_body.get("dsid")
    if not isinstance(dsid, str) or not dsid:
        raise BrowserAutomationError("Apple purchase-search request body did not include string dsid.")
    if set(request_body) != {"dsid"}:
        raise BrowserAutomationError(
            "Apple auth capture expected the first purchase-search request body to be exactly {'dsid': ...}."
        )

    headers = request.get("headers")
    if not isinstance(headers, dict):
        raise BrowserAutomationError("Apple purchase-search request event was missing request headers.")
    normalized_headers = _normalized_headers(headers)

    session_storage_token = page.evaluate("() => sessionStorage.getItem('x-apple-xsrf-token')")
    if not isinstance(session_storage_token, str) or not session_storage_token:
        raise BrowserAutomationError("Apple browser sessionStorage did not contain x-apple-xsrf-token.")
    captured_token = normalized_headers.get("x-apple-xsrf-token")
    if captured_token != session_storage_token:
        raise BrowserAutomationError(
            "Apple purchase-search request x-apple-xsrf-token did not match sessionStorage."
        )

    payload = validate_request_context(
        {
            "dsid": dsid,
            "headers": normalized_headers,
            "cookies": _required_cookies(page.cookie_list()),
        }
    )
    _write_request_context(config, payload)
    return payload


def apple_browser_login(config, force: bool) -> None:
    """Open the Apple browser flow and capture replay context."""
    browser = config.get_browser()
    effective_force = force
    try:
        if not force and config.has_saved_session():
            live = browser.is_authenticated()
            if bool(live) and _has_valid_request_context(config):
                print_success("Already authenticated (apple browser session)")
                return
            if bool(live):
                print_info("Saved Apple session is valid but replay context is missing. Refreshing capture.")
            else:
                print_info("Saved session is no longer valid — re-running browser login.")
            effective_force = True

        if effective_force:
            browser.clear_session()

        print_info(f"Opening browser for login at: {browser.LOGIN_URL}")
        print_info(
            "Complete Apple sign-in in the browser. If Apple asks for a "
            "verification code, this CLI will prefer text-message delivery "
            "when Apple offers it and will prompt for the six-digit code."
        )
        service = browser._get_service()
        service.browser_open(
            browser.LOGIN_URL,
            headed=True,
            persistent_profile_dir=browser._get_persistent_profile_dir(),
        )
        browser._service = service
        browser._page = service
        _wait_for_apple_interactive_auth(browser, service)
        service.wait_for_timeout(2000)
        if not browser._check_auth(service):
            raise BrowserAutomationError("Browser session is not authenticated after login.")
        capture_request_context_from_page(service, config)
        print_success("Browser session authenticated")
    except BrowserAutomationError as exc:
        print_error(f"Browser auth failed: {exc}")
        raise SystemExit(1)
    finally:
        browser.close()


def _wait_for_apple_interactive_auth(browser, page) -> None:
    """Wait for Apple auth, handling iframe-based login and MFA stages."""
    deadline = time.monotonic() + float(getattr(browser, "LOGIN_TIMEOUT", APPLE_CODE_TIMEOUT_SECONDS))
    last_notice: tuple[str, bool] | None = None
    last_code_submission_at = 0.0

    while time.monotonic() < deadline:
        if browser._check_auth(page):
            return

        state = _detect_apple_auth_stage(page)
        stage = state["stage"]
        invalid_code = bool(state["invalid_code"])
        lowered = state["body_text"].lower()
        _raise_for_blocked_apple_state(lowered)

        if _matches_any(lowered, _SECURITY_KEY_PATTERNS):
            if last_notice != ("security_key", False):
                print_info(
                    "Apple is requesting a security key or nearby trusted Apple device. Complete that step in the browser."
                )
                last_notice = ("security_key", False)
            page.wait_for_timeout(int(APPLE_AUTH_POLL_SECONDS * 1000))
            continue

        if _matches_any(lowered, _DEVICE_PASSCODE_PATTERNS):
            if last_notice != ("device_passcode", False):
                print_info(
                    "Apple is requesting a device passcode. Complete that step in the browser; the CLI will continue automatically."
                )
                last_notice = ("device_passcode", False)
            page.wait_for_timeout(int(APPLE_AUTH_POLL_SECONDS * 1000))
            continue

        notice_key = (stage, invalid_code)
        if notice_key != last_notice:
            _print_apple_auth_stage_notice(stage, invalid_code)
            last_notice = notice_key

        if stage == "trusted_device_code":
            if not invalid_code and _code_submission_is_settling(last_code_submission_at):
                page.wait_for_timeout(500)
                continue
            code = _prompt_for_apple_verification_code(
                "trusted Apple device",
                APPLE_CODE_TIMEOUT_SECONDS,
                allow_sms=True,
            )
            if code == "sms":
                if not _request_text_message_code(page):
                    raise BrowserAutomationError("Apple did not expose the text-message verification option.")
                page.wait_for_timeout(1500)
                continue
            _enter_apple_verification_code(page, code)
            last_code_submission_at = time.monotonic()
            page.wait_for_timeout(1500)
            continue

        if stage == "sms_options":
            if not _request_text_message_code(page):
                raise BrowserAutomationError("Apple did not expose the text-message verification option.")
            page.wait_for_timeout(1500)
            continue

        if stage == "sms_code":
            if not invalid_code and _code_submission_is_settling(last_code_submission_at):
                page.wait_for_timeout(500)
                continue
            code = _prompt_for_apple_verification_code(
                "text message to the trusted phone number",
                APPLE_CODE_TIMEOUT_SECONDS,
            )
            _enter_apple_verification_code(page, code)
            last_code_submission_at = time.monotonic()
            page.wait_for_timeout(1500)
            continue

        page.wait_for_timeout(int(APPLE_AUTH_POLL_SECONDS * 1000))

    raise BrowserAutomationError(
        "Timed out waiting for Apple authentication. Re-run 'apple auth login' "
        "from an interactive shell and complete the visible Apple sign-in flow."
    )


def _detect_apple_auth_stage(page) -> dict[str, Any]:
    """Classify the current Apple auth stage from the auth iframe."""
    page_url = getattr(page, "url", "") or ""
    if page_url.startswith("https://reportaproblem.apple.com/"):
        return {"stage": "authenticated", "invalid_code": False, "body_text": ""}

    body_text = _visible_page_text(page)
    lowered = body_text.lower()
    has_sign_in_form = bool(_evaluate_auth_frame(page, _HAS_SIGN_IN_FORM_JS))
    has_verification_inputs = bool(_evaluate_auth_frame(page, _VERIFICATION_INPUTS_JS))
    has_sms_options = bool(_evaluate_auth_frame(page, _HAS_SMS_OPTIONS_JS))
    has_sms_prompt = bool(_evaluate_auth_frame(page, _HAS_SMS_PROMPT_JS))
    invalid_code = "incorrect verification code" in lowered

    if has_sign_in_form:
        stage = "signin_form"
    elif has_sms_prompt and has_verification_inputs:
        stage = "sms_code"
    elif has_sms_options:
        stage = "sms_options"
    elif has_verification_inputs or _matches_any(lowered, _VERIFICATION_CODE_PATTERNS):
        stage = "trusted_device_code"
    else:
        stage = "waiting"

    return {
        "stage": stage,
        "invalid_code": invalid_code,
        "body_text": body_text,
    }


def _raise_for_blocked_apple_state(lowered_text: str) -> None:
    if _matches_any(lowered_text, _ACCOUNT_BLOCKED_PATTERNS):
        raise BrowserAutomationError(
            "Apple reports that the account is locked, not active, or disabled. "
            "Resolve the account state through Apple's account recovery or "
            "request-access flow before running auth login again."
        )
    if _matches_any(lowered_text, _ACCOUNT_RECOVERY_PATTERNS):
        raise BrowserAutomationError(
            "Apple is offering account recovery or a no-access recovery path. "
            "This CLI cannot complete account recovery; regain access to a "
            "trusted device or trusted phone number, then rerun auth login."
        )


def _visible_page_text(page) -> str:
    value = _evaluate_auth_frame(
        page,
        "() => document.body ? (document.body.innerText || document.body.textContent || '') : ''",
    )
    if isinstance(value, str) and value.strip():
        return _normalize_auth_text(value)
    try:
        value = page.evaluate(
            "() => document.body ? (document.body.innerText || document.body.textContent || '') : ''"
        )
    except Exception:
        return ""
    if isinstance(value, str):
        return _normalize_auth_text(value)
    return ""


def _request_text_message_code(page) -> bool:
    """Open Apple's text-message fallback from the trusted-device screen."""
    state = _detect_apple_auth_stage(page)
    if state["stage"] != "sms_options":
        clicked = _click_text_matching_button(page, (r"didn.t get a code", r"can.t get to your devices"))
        if not clicked:
            clicked = _click_auth_frame_button(page, button_id="alt-options-btn")
        if not clicked:
            return False
        page.wait_for_timeout(1000)

    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if _click_text_matching_button(
            page,
            _TEXT_MESSAGE_OPTION_PATTERNS,
            _TEXT_DELIVERY_EXCLUDED_PATTERNS,
        ):
            return True
        if _click_auth_frame_button(page, button_id="send-code"):
            return True
        page.wait_for_timeout(500)
    return False


def _click_text_matching_button(
    page,
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...] = (),
) -> bool:
    return bool(
        _evaluate_auth_frame(
            page,
            _CLICK_TEXT_MATCHING_BUTTON_JS,
            {
                "include": list(include_patterns),
                "exclude": list(exclude_patterns),
            },
        )
    )


def _prompt_for_apple_verification_code(
    code_source: str,
    timeout_seconds: int,
    *,
    allow_sms: bool = False,
) -> str:
    prompt = (
        f"Enter the six-digit Apple verification code from {code_source} "
        f"within {timeout_seconds // 60} minutes"
    )
    if allow_sms:
        prompt += ", or type 'sms' for text-message fallback: "
    else:
        prompt += ": "

    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BrowserAutomationError("Timed out waiting for the Apple verification code.")
        raw = _readline_with_timeout(prompt, int(max(1, remaining)))
        normalized = raw.strip().lower()
        if allow_sms and normalized == "sms":
            return "sms"
        code = re.sub(r"\D", "", raw)
        if len(code) == 6:
            return code
        if allow_sms:
            print_error("Apple verification code must contain exactly six digits, or enter 'sms'.")
        else:
            print_error("Apple verification code must contain exactly six digits.")


def _enter_apple_verification_code(page, code: str) -> None:
    prepared = _evaluate_auth_frame(page, _PREPARE_VERIFICATION_CODE_INPUT_JS, {"code": code})
    if not prepared:
        raise BrowserAutomationError("Apple verification-code input was not found in the browser.")
    try:
        page.type_text(code)
    except Exception as exc:
        raise BrowserAutomationError("Apple verification code could not be typed into the browser.") from exc


def _readline_with_timeout(prompt: str, timeout_seconds: int) -> str:
    stream, close_stream = _open_prompt_stream()
    try:
        sys.stderr.write(prompt)
        sys.stderr.flush()
        readable, _, _ = select.select([stream], [], [], timeout_seconds)
        if not readable:
            raise BrowserAutomationError("Timed out waiting for the Apple verification code.")
        raw = stream.readline()
        if raw == "":
            raise BrowserAutomationError("Apple verification code input ended before a code was provided.")
        return raw
    finally:
        if close_stream:
            stream.close()


def _open_prompt_stream() -> tuple[TextIO, bool]:
    try:
        return open("/dev/tty", "r", encoding="utf-8", errors="replace"), True
    except OSError:
        pass

    if sys.stdin is not None and not sys.stdin.closed:
        try:
            sys.stdin.fileno()
            return sys.stdin, False
        except (AttributeError, OSError, ValueError):
            if hasattr(sys.stdin, "readline"):
                return sys.stdin, False

    raise BrowserAutomationError(
        "Apple verification requires an interactive terminal, but stdin and /dev/tty are unavailable."
    )


def _click_auth_frame_button(page, *, button_id: str) -> bool:
    return bool(
        _evaluate_auth_frame(
            page,
            """
            (arg) => {
              const button = document.getElementById(arg.buttonId);
              if (!button) return false;
              button.click();
              return true;
            }
            """,
            {"buttonId": button_id},
        )
    )


def _evaluate_auth_frame(page, js: str, arg: Any = None) -> Any:
    try:
        return page.evaluate_in_iframe(APPLE_AUTH_IFRAME_URL_SUBSTR, js, arg)
    except Exception:
        return None


def _code_submission_is_settling(last_code_submission_at: float) -> bool:
    return (
        last_code_submission_at > 0
        and (time.monotonic() - last_code_submission_at) < POST_CODE_SETTLE_SECONDS
    )


def _print_apple_auth_stage_notice(stage: str, invalid_code: bool) -> None:
    if invalid_code:
        print_error("Apple rejected the previous verification code.")
    if stage == "signin_form":
        print_info(
            "Enter your Apple Account email/phone number and password in the browser window."
        )
        return
    if stage == "trusted_device_code":
        print_info(
            "Apple requires a trusted-device verification code. Enter the code from your Apple device here, or type 'sms' to switch to text-message delivery."
        )
        return
    if stage == "sms_options":
        print_info("Requesting Apple verification by text message.")
        return
    if stage == "sms_code":
        print_info(
            "Apple sent a text-message verification code. Enter it here within 5 minutes."
        )
        return
    print_info(
        "Finish the Apple email/password step in the browser. The CLI is waiting for authentication or a verification-code screen."
    )


def _normalize_auth_text(value: str) -> str:
    return " ".join(value.replace("\u2019", "'").split())


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


_VISIBLE_ELEMENT_JS = """
function isVisible(el) {
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style
    && style.visibility !== 'hidden'
    && style.display !== 'none'
    && rect.width > 0
    && rect.height > 0;
}
"""

_HAS_SIGN_IN_FORM_JS = """() => {
  return !!document.querySelector('#account_name_text_field')
    && !!document.querySelector('#password_text_field')
    && !!document.querySelector('#sign-in');
}"""

_HAS_SMS_OPTIONS_JS = f"""() => {{
  {_VISIBLE_ELEMENT_JS}
  return Array.from(document.querySelectorAll('button'))
    .filter(isVisible)
    .some(el => /text code to/i.test((el.innerText || el.textContent || '').trim()));
}}"""

_HAS_SMS_PROMPT_JS = """() => {
  const text = document.body ? (document.body.innerText || document.body.textContent || '') : '';
  return /sent as a message to/i.test(text);
}"""

_VERIFICATION_INPUTS_JS = f"""() => {{
  {_VISIBLE_ELEMENT_JS}
  const inputs = Array.from(document.querySelectorAll('input'))
    .filter(el => !el.disabled && !el.readOnly && isVisible(el));
  return inputs.some(el => {{
    const attrs = [
      el.type,
      el.name,
      el.id,
      el.className,
      el.autocomplete,
      el.inputMode,
      el.placeholder,
      el.getAttribute('aria-label')
    ].join(' ').toLowerCase();
    return /code|verification|digit|char|one-time|numeric|tel/.test(attrs);
  }});
}}"""

_CLICK_TEXT_MATCHING_BUTTON_JS = f"""(arg) => {{
  {_VISIBLE_ELEMENT_JS}
  const include = (arg.include || []).map(pattern => new RegExp(pattern, 'i'));
  const exclude = (arg.exclude || []).map(pattern => new RegExp(pattern, 'i'));
  const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'))
    .filter(isVisible);
  for (const el of candidates) {{
    const label = [
      el.innerText,
      el.textContent,
      el.value,
      el.getAttribute('aria-label'),
      el.getAttribute('title')
    ].filter(Boolean).join(' ').trim();
    if (!label) continue;
    if (!include.some(pattern => pattern.test(label))) continue;
    if (exclude.some(pattern => pattern.test(label))) continue;
    el.click();
    return true;
  }}
  return false;
}}"""

_PREPARE_VERIFICATION_CODE_INPUT_JS = f"""(arg) => {{
  {_VISIBLE_ELEMENT_JS}
  const code = String(arg.code || '').replace(/\\D/g, '');
  if (!/^\\d{{6}}$/.test(code)) return false;
  const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  if (!descriptor || typeof descriptor.set !== 'function') return false;
  const inputs = Array.from(document.querySelectorAll('input'))
    .filter(el => !el.disabled && !el.readOnly && isVisible(el))
    .filter(el => {{
      const attrs = [
        el.type,
        el.name,
        el.id,
        el.className,
        el.autocomplete,
        el.inputMode,
        el.placeholder,
        el.getAttribute('aria-label')
      ].join(' ').toLowerCase();
      return /code|verification|digit|char|one-time|numeric|tel/.test(attrs);
    }});
  if (inputs.length >= 6) {{
    inputs.slice(0, 6).forEach((el, index) => {{
      descriptor.set.call(el, '');
      el.dispatchEvent(new InputEvent('input', {{ bubbles: true, data: null, inputType: 'deleteContentBackward' }}));
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }});
    inputs[0].focus();
  }} else if (inputs.length >= 1) {{
    const el = inputs[0];
    descriptor.set.call(el, '');
    el.dispatchEvent(new InputEvent('input', {{ bubbles: true, data: null, inputType: 'deleteContentBackward' }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    el.focus();
  }} else {{
    return false;
  }}
  return true;
}}"""


def _has_valid_request_context(config) -> bool:
    path = config.request_context_path
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_request_context(payload)
    except Exception:
        return False
    return True


def _write_request_context(config, payload: dict[str, Any]) -> None:
    path = config.request_context_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _first_purchase_search_request(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("method") != "Network.requestWillBeSent":
            continue
        params = event.get("params")
        if not isinstance(params, dict):
            continue
        request = params.get("request")
        if not isinstance(request, dict):
            continue
        if request.get("method") != "POST":
            continue
        if request.get("url") == PURCHASE_SEARCH_URL:
            return params
    return None


def _normalized_headers(headers: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not key:
            raise BrowserAutomationError("Apple purchase-search request header name was invalid.")
        if not isinstance(value, str):
            raise BrowserAutomationError(f"Apple purchase-search header '{key}' was not a string.")
        lowered = key.lower()
        if lowered in FORBIDDEN_CAPTURED_HEADERS:
            continue
        normalized[lowered] = value
    return normalized


def _required_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(cookies, list):
        raise BrowserAutomationError("Apple browser cookie list was not a list.")
    selected: list[dict[str, Any]] = []
    by_name = {
        cookie.get("name"): cookie
        for cookie in cookies
        if isinstance(cookie, dict) and isinstance(cookie.get("name"), str)
    }
    for name in REQUIRED_COOKIE_NAMES:
        cookie = by_name.get(name)
        if cookie is None:
            raise BrowserAutomationError(f"Apple browser session was missing required cookie '{name}'.")
        selected.append(cookie)
    return selected
