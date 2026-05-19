"""Apple auth-login replay-context capture."""

from __future__ import annotations

import json
from typing import Any

from cli_tools_shared.auth import BrowserAutomationError
from cli_tools_shared.output import print_error, print_info, print_success

from .parsers import validate_request_context

PURCHASE_SEARCH_URL = "https://reportaproblem.apple.com/api/purchase/search"
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
        print_info("Log in, then press Enter here to save the session and capture the Apple request context.")
        service = browser._get_service()
        service.browser_open(
            browser.LOGIN_URL,
            headed=True,
            persistent_profile_dir=browser._get_persistent_profile_dir(),
        )
        browser._service = service
        browser._page = service
        browser._prompt_enter_eof_safe()
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
