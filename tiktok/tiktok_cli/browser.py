"""Browser automation for TikTok (declarative hooks + headless login handler).

`favorites list` has no public or internal API path that works without a
logged-in session: TikTok's own web app posts every "Favorites" tab query to
`GET /api/user/collect/item_list/` on tiktok.com's own domain, signed in-page
by TikTok's ``webmssdk`` (msToken / X-Bogus headers minted client-side). An
unauthenticated probe of that exact endpoint returns HTTP 200 with an empty
body — the route exists, but requires the caller's own session cookies. The
client therefore runs the request INSIDE the live tiktok.com page through
`page.evaluate()` (see client.py), the same in-page-fetch pattern this repo
already uses for OfferUp — not click-driven UI scraping.

Login detection: TikTok's header renders a "Log in" nav control when signed
out (React-hydrated, so the SSR HTML alone does not show it) and no such
control once signed in. This mirrors the proven detection in
`offerup_cli/browser.py`.

Sign-in flow (validated live via the harness headless Chromium):

  1. GET https://www.tiktok.com/login renders a channel chooser. Selecting
     "Use phone / email / username" navigates to /login/phone-or-email, which
     offers "Log in with email or username".
  2. GET https://www.tiktok.com/login/phone-or-email/email renders the email
     form directly: `input[name="username"]` (placeholder "Email or
     username"), `input[type="password"]` (placeholder "Password"), and a
     `button[data-e2e="login-button"]` ("Log in", type=submit). Both fields
     are visible together; no intermediate click is required.
  3. Submitting redirects a valid session off /login (e.g. /foryou). TikTok
     may instead serve a CAPTCHA slider, a 6-digit verification-code step for
     two-factor accounts, or a "Maximum number of attempts reached" rate-limit
     message — all of which are detected and reported as explicit blockers.

`AUTH_LOGIN_HANDLER` drives the email/password step headlessly through the
CLI-owned harness browser (which renders TikTok fine), so `auth login` never
opens the plain/headed Chrome that crashes this host. The one thing it cannot
do is answer an out-of-band verification code or a CAPTCHA, so those are a
hard stop with an explicit message rather than a silent failure.
"""

from __future__ import annotations

import time

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
from cli_tools_shared.config import read_cli_tool_secret, secret_manager_set_command

# Truthy result means NOT authenticated. Polls for the signed-out "Log in" nav
# control, and treats an unhydrated page as signed out as well.
_LOGGED_OUT_JS = """async () => {
    const isLoginControl = () => Array.from(
        document.querySelectorAll('header a, header button, nav a, nav button')
    ).some(el => /^(log ?in|sign ?in)$/i.test((el.textContent || '').trim()));
    const isHydrated = () =>
        document.querySelectorAll('header a, header button').length > 2;
    for (let attempt = 0; attempt < 10; attempt++) {
        if (isLoginControl()) { return true; }
        if (isHydrated()) { return false; }
        await new Promise(resolve => setTimeout(resolve, 1000));
    }
    return true;
}"""

# The email/password form renders directly at this URL (validated live).
EMAIL_LOGIN_URL = "https://www.tiktok.com/login/phone-or-email/email"
USERNAME_SELECTOR = 'input[name="username"]'
PASSWORD_SELECTOR = 'input[type="password"]'
SUBMIT_SELECTOR = 'button[data-e2e="login-button"]'
# Two-factor accounts show a 6-digit code input after email/password. The code
# is delivered out-of-band (SMS/email), not minted from a seed, so it cannot
# be answered headlessly — the handler reports it as a blocker.
VERIFY_CODE_SELECTOR = 'input[placeholder="Enter 6-digit code"]'

# CLI-tools secret-manager names (see references/secrets.md naming schema).
USERNAME_SECRET = "tiktok-username"
PASSWORD_SECRET = "tiktok-password"

LOGIN_AUTOMATION_TIMEOUT = 30  # seconds to reach an authenticated state
EMAIL_FORM_SETTLE_MS = 5000

# One probe that classifies the post-submit page into a blocker category, so
# the handler can raise a specific message instead of a generic timeout.
_PAGE_ISSUE_JS = """() => {
    const norm = (s) => (s || '').trim().replace(/\\s+/g, ' ').toLowerCase();
    const body = norm(document.body.innerText || '');
    const href = location.href.toLowerCase();
    if (/captcha/i.test(href)) return 'captcha';
    if (document.querySelector(
        '[id*="captcha" i], [class*="captcha" i], iframe[src*="captcha" i]'
    )) return 'captcha';
    if (/captcha|complete the puzzle|drag the slider|slide to (complete|verify)/.test(body)) {
        return 'captcha';
    }
    if (/maximum number of attempts|too many (login )?attempts|try again later/.test(body)) {
        return 'rate_limit';
    }
    if (/incorrect|wrong password|couldn't find|doesn't exist|no account/.test(body)) {
        return 'bad_credentials';
    }
    return null;
}"""


def _first_visible(page, selector: str):
    """The first visible element matching ``selector`` (or None)."""
    for candidate in page.locator(selector).all():
        if candidate.is_visible():
            return candidate
    return None


def _page_issue(page) -> "str | None":
    """Return a blocker/error category for the current page, or ``None``."""
    try:
        result = page.evaluate(_PAGE_ISSUE_JS)
    except Exception:
        return None
    return result if isinstance(result, str) and result else None


def _tiktok_login_handler(browser: "TiktokBrowser", page) -> None:
    """Complete TikTok's email/password sign-in on the headless harness page."""
    username = read_cli_tool_secret(USERNAME_SECRET)
    password = read_cli_tool_secret(PASSWORD_SECRET)
    if username is None:
        raise BrowserAutomationError(
            "Missing TikTok login username. Store it with: "
            f"{secret_manager_set_command(USERNAME_SECRET)}"
        )
    if password is None:
        raise BrowserAutomationError(
            "Missing TikTok login password. Store it with: "
            f"{secret_manager_set_command(PASSWORD_SECRET)}"
        )

    page.goto(EMAIL_LOGIN_URL)
    page.wait_for_timeout(EMAIL_FORM_SETTLE_MS)

    username_field = _first_visible(page, USERNAME_SELECTOR)
    password_field = _first_visible(page, PASSWORD_SELECTOR)
    submit = _first_visible(page, SUBMIT_SELECTOR)
    if username_field is None or password_field is None or submit is None:
        raise BrowserAutomationError(
            "TikTok's email login form did not render its expected fields "
            f"(username={username_field is not None}, "
            f"password={password_field is not None}, "
            f"submit={submit is not None}). The login page layout changed; "
            "re-capture it before changing this handler."
        )

    username_field.fill(username)
    password_field.fill(password)
    submit.click()

    deadline = time.monotonic() + LOGIN_AUTOMATION_TIMEOUT
    while time.monotonic() < deadline:
        page.wait_for_timeout(1000)
        issue = _page_issue(page)
        if issue == "captcha":
            raise BrowserAutomationError(
                "TikTok presented a CAPTCHA / human-verification challenge "
                "during login. This cannot be solved automatically and must "
                "not be automated around. Re-run 'tiktok auth login "
                "--credential-type browser_session' from an interactive shell "
                "and complete the challenge in the CLI-owned browser profile."
            )
        if issue == "rate_limit":
            raise BrowserAutomationError(
                "TikTok is rate-limiting logins for this account/IP "
                "('Maximum number of attempts reached. Try again later.'). "
                "Wait before retrying — do not hammer the login. Re-run "
                "'tiktok auth login --credential-type browser_session' after "
                "the cooldown, ideally from an interactive shell."
            )
        if issue == "bad_credentials":
            raise BrowserAutomationError(
                "TikTok rejected the stored credentials. Rotate "
                f"{secret_manager_set_command(PASSWORD_SECRET)} and "
                "re-run the login."
            )
        if browser._check_auth(page):
            return
        if _first_visible(page, VERIFY_CODE_SELECTOR) is not None:
            raise BrowserAutomationError(
                "TikTok requested a 6-digit verification code (two-factor "
                "authentication). The code is delivered to Adam's phone/email, "
                "not generated from a seed, so it cannot be completed "
                "headlessly. Re-run 'tiktok auth login --credential-type "
                "browser_session' from an interactive shell to enter the code."
            )
    raise BrowserAutomationError(
        "TikTok login did not reach an authenticated state within "
        f"{LOGIN_AUTOMATION_TIMEOUT}s. The credentials may have been rejected, "
        "or TikTok served an unexpected challenge page."
    )


class TiktokBrowser(BrowserAutomation):
    """Browser automation for TikTok via cli_tools_shared.auth.BrowserAutomation."""

    SESSION_NAME = "tiktok"
    LOGIN_URL = "https://www.tiktok.com/login"
    AUTH_CHECK_URL = "https://www.tiktok.com/"
    AUTH_URL_PATTERN = r"/login"
    # Polls for the control rather than reading the DOM once, so a slow nav
    # render cannot report a cold profile as signed in, and an unhydrated page
    # reports "not authenticated" instead of a false healthy session.
    AUTH_FAILURE_PAGE_JS = _LOGGED_OUT_JS

    # Fully non-interactive: the email/password form is submitted headlessly by
    # AUTH_LOGIN_HANDLER (see module docstring). The shared single-page
    # USERNAME/PASSWORD/SUBMIT selector constants are deliberately left unset
    # because that declarative path only runs on the crashing headed flow.
    AUTH_LOGIN_HANDLER = staticmethod(_tiktok_login_handler)
