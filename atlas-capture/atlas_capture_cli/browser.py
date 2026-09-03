"""Browser automation for Atlas Capture (audit.atlascapture.io).

This account signs in with passwordless email one-time codes, not a password.
The worker portal's auth is Stytch (the code email arrives from
``login@stytch.com``) fronted by a Cloudflare Turnstile widget on the login
form. Validated live 2026-09-03 against the real site:

  1. GET https://audit.atlascapture.io/login renders an email form
     (``input#email`` + a hidden ``input[name=cf-turnstile-response]``). The
     Turnstile widget mints its token automatically in a REAL Chrome session;
     in headless Chromium no token is produced and the server answers
     "Please complete the security check and try again." So ``auth login``
     must run headed (``HEADLESS=false``).
  2. Submitting the email sends the site's own request and redirects to
     https://audit.atlascapture.io/verify?methodId=...&signupRequestId=...
     with a 6-digit code form (``input#code``, placeholder "000000").
  3. The code is delivered by email from ``login@stytch.com`` (subject
     "Your one-time login code for Atlas"). This module polls Gmail through
     the ``google`` CLI (profile ``adbertram``) for the code — never printing
     it — then submits it and lands on the authenticated dashboard.

The login page email is Adam's account address, stored as the reusable
``atlas-capture-email`` CLI-tools secret (see the cli-tool-secrets skill);
``ATLAS_CAPTURE_EMAIL`` overrides it for other accounts.

The site keeps the session in httpOnly cookies (``stytch_session_token``,
``mecka_device_key``) inside the persistent profile, so once logged in the
headless commands reuse that saved session.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from typing import Optional

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
from cli_tools_shared.config import read_cli_tool_secret

EMAIL_SELECTOR = "#email"
EMAIL_SUBMIT_TEXT = "Start Earning Today"
CODE_SELECTOR = "#code"
CODE_SUBMIT_TEXT = "Verify"
TURNSTILE_TOKEN_SELECTOR = 'input[name="cf-turnstile-response"]'
EMAIL_SECRET_NAME = "atlas-capture-email"
GOOGLE_GMAIL_PROFILE = "adbertram"
GMAIL_CODE_SENDER_QUERY = "from:login@stytch.com subject:(one-time login code)"

DASHBOARD_PATH = "/dashboard"
VERIFY_PATH = "/verify"


def _atlas_login_handler(browser: "AtlasCaptureBrowser", page) -> None:
    """Complete Atlas Capture's passwordless email-OTP login.

    Requires a HEADED browser (Turnstile will not mint a token in headless
    Chromium — see the module docstring). The only human-free interactions
    are filling the email, reading the emailed code back through the ``google``
    Gmail CLI, and submitting it.
    """
    if browser._headless_enabled():
        raise BrowserAutomationError(
            "Atlas Capture login must run in a HEADED browser: Cloudflare "
            "Turnstile does not mint its token in headless Chromium and the "
            "server rejects the code request. Re-run with "
            "'HEADLESS=false atlas-capture auth login'."
        )

    email = _resolve_email()
    token = _wait_for_turnstile_token(page, timeout_s=25)
    if not token:
        raise BrowserAutomationError(
            "Cloudflare Turnstile did not produce a token on the Atlas login "
            "page within 25s. If an interactive 'Verify you are human' "
            "checkbox is showing, only a human can pass it — complete the "
            "login by hand in the headed window (or run the one-time CDP "
            "bootstrap per the browser-automation skill), then re-run "
            "'atlas-capture auth login'."
        )

    _fill_and_submit_email(page, email)
    _wait_for_path(page, VERIFY_PATH, timeout_s=30, what="the /verify code page")

    code = _poll_gmail_code(timeout_s=150)
    _submit_code(page, code)
    _wait_for_path(page, DASHBOARD_PATH, timeout_s=30,
                   what="the authenticated dashboard (code accepted)")


def _resolve_email() -> str:
    env_email = os.environ.get("ATLAS_CAPTURE_EMAIL", "").strip()
    if env_email:
        return env_email
    secret = read_cli_tool_secret(EMAIL_SECRET_NAME)
    if secret:
        return secret
    raise BrowserAutomationError(
        "No Atlas Capture login email configured. Set the reusable secret "
        "with: secrets.sh set --tool atlas-capture --type email  (value via "
        "stdin), or export ATLAS_CAPTURE_EMAIL."
    )


def _wait_for_turnstile_token(page, timeout_s: int) -> str:
    """Poll the Turnstile response input until it carries a token."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        token = page.evaluate(
            "() => { const el = document.querySelector("
            "'input[name=\"cf-turnstile-response\"]'); "
            "return el && el.value ? el.value : ''; }"
        )
        if token:
            return token
        page.wait_for_timeout(1000)
    return ""


def _fill_and_submit_email(page, email: str) -> None:
    email_field = page.locator(EMAIL_SELECTOR)
    if email_field.count() != 1 or not email_field.first.is_visible():
        raise BrowserAutomationError(
            "Atlas login page did not render its email field "
            f"({EMAIL_SELECTOR}). Re-capture the login page before changing "
            "this handler."
        )
    page.fill(EMAIL_SELECTOR, email)

    # The submit stays disabled until the Turnstile token lands; then it
    # enables on its own. Click it only when enabled.
    deadline = time.time() + 15
    while time.time() < deadline:
        submit = _button(page, EMAIL_SUBMIT_TEXT)
        if submit is not None and _enabled(submit):
            submit.click()
            return
        page.wait_for_timeout(1000)
    raise BrowserAutomationError(
        f"The '{EMAIL_SUBMIT_TEXT}' button never enabled after the email was "
        "filled. Turnstile may not have completed; re-run auth login."
    )


def _submit_code(page, code: str) -> None:
    code_field = page.locator(CODE_SELECTOR)
    if code_field.count() != 1 or not code_field.first.is_visible():
        raise BrowserAutomationError(
            "After the code request the site did not render its code field "
            f"({CODE_SELECTOR}). Re-capture the /verify page before changing "
            "this handler."
        )
    page.fill(CODE_SELECTOR, code)
    deadline = time.time() + 15
    while time.time() < deadline:
        verify = _button(page, CODE_SUBMIT_TEXT)
        if verify is not None and _enabled(verify):
            verify.click()
            return
        page.wait_for_timeout(1000)
    raise BrowserAutomationError(
        f"The '{CODE_SUBMIT_TEXT}' button never enabled after the code was "
        "filled. The code may have expired — re-run auth login for a fresh "
        "code."
    )


def _wait_for_path(page, path: str, timeout_s: int, what: str) -> None:
    """Wait until location.href contains ``path``, or raise."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        url = page.evaluate("() => location.href") or ""
        if path in url:
            return
        page.wait_for_timeout(1000)
    url = page.evaluate("() => location.href") or ""
    raise BrowserAutomationError(
        f"Atlas Capture login did not reach {what} within {timeout_s}s "
        f"(stopped at {url})."
    )


def _button(page, text: str):
    """Return a playwright button locator by visible text, or None."""
    try:
        button = page.get_by_role("button", name=text, exact=True)
        return button if button.count() == 1 else None
    except Exception:
        return None


def _enabled(locator) -> bool:
    try:
        return bool(locator.first.is_enabled())
    except Exception:
        return False


def _poll_gmail_code(timeout_s: int) -> str:
    """Retrieve the newest Atlas Stytch login code from Gmail.

    Runs the ``google`` CLI (profile ``adbertram``): search for the code email
    and read the newest hit. Never prints the code; returns it in memory only.
    """
    google = shutil.which("google")
    if not google:
        raise BrowserAutomationError(
            "The 'google' CLI is not on PATH — it is needed to read the "
            "emailed login code from Gmail (profile 'adbertram')."
        )
    deadline = time.time() + timeout_s
    last_status = "no email found yet"
    while time.time() < deadline:
        search = _run(
            google,
            ["gmail", "search", GMAIL_CODE_SENDER_QUERY, "-l", "3",
             "-p", "id,date", "--profile", GOOGLE_GMAIL_PROFILE],
        )
        if search.returncode == 0:
            try:
                messages = json.loads(search.stdout or "[]")
            except json.JSONDecodeError:
                messages = []
            if messages:
                message_id = messages[0].get("id")
                read = _run(google, ["gmail", "read", message_id,
                                     "--profile", GOOGLE_GMAIL_PROFILE])
                if read.returncode == 0:
                    code = _extract_code(read.stdout or "")
                    if code:
                        return code
                    last_status = "newest email had no 6-digit code"
        page_wait = min(4000, max(500, int(deadline - time.time())))
        time.sleep(page_wait)
    raise BrowserAutomationError(
        f"Could not retrieve the Atlas login code from Gmail within "
        f"{timeout_s}s ({last_status}). Re-run auth login to send a fresh "
        "code."
    )


def _extract_code(text: str) -> Optional[str]:
    """A 6-digit code delimited by non-digits (never a partial number)."""
    match = re.search(r"(?<![\d])(\d{6})(?![\d])", text or "")
    return match.group(1) if match else None


def _run(executable, args: list):
    return subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )


class AtlasCaptureBrowser(BrowserAutomation):
    """Browser automation for Atlas Capture via
    cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks plus one explicit login handler (see module docstring);
    the base class handles the rest of the auth lifecycle.
    """

    SESSION_NAME = "atlas-capture"
    LOGIN_URL = "https://audit.atlascapture.io/login"
    AUTH_CHECK_URL = "https://audit.atlascapture.io/dashboard"
    # An unauthenticated session asking for any worker URL is redirected to
    # /login or /verify; either means "not authenticated".
    AUTH_URL_PATTERN = r"/login|/verify"
    # The login email field is the preferred "logged out" signal: it exists on
    # /login and nowhere on the authenticated pages, so its absence on a
    # non-auth URL means the session is authenticated.
    AUTH_LOGIN_FORM_SELECTOR = EMAIL_SELECTOR

    # No username/password secrets: this account authenticates with a Stytch
    # emailed code, driven entirely by AUTH_LOGIN_HANDLER (headed only).
    AUTH_LOGIN_HANDLER = staticmethod(_atlas_login_handler)
