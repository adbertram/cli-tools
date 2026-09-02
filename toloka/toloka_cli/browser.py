"""Browser automation for Toloka."""

from cli_tools_shared.auth import BrowserAutomation


class TolokaBrowser(BrowserAutomation):
    """Browser automation for Toloka via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks only -- no methods. The base class handles auth
    lifecycle using these class-level constants.

    SELECTOR VALIDATION STATUS (2026-09-02): https://www.toloka.site was
    completely unreachable throughout this CLI's development -- every
    request, including /login, returned Cloudflare Tunnel error 1033 (HTTP
    530), confirmed by repeated live checks (curl + browser navigation) over
    several minutes with no recovery. No real DOM was ever observable, so the
    values below are the scaffold's generic browser-template defaults, NOT
    validated selectors (see the microworkers_cli/browser.py sibling for what
    a validated version of this file looks like once real markup is
    captured).

    Before relying on `toloka auth login`, re-run validation once the site
    recovers:
      1. Navigate to LOGIN_URL and capture the real login form via
         page.evaluate("document.documentElement.outerHTML") or a targeted
         query.
      2. Confirm AUTH_URL_PATTERN against the actual unauthenticated-redirect
         URL, and AUTH_SUCCESS_SELECTOR / AUTH_LOGIN_FORM_SELECTOR against a
         real authenticated vs. logged-out page snapshot.
      3. Add AUTH_LOGIN_USERNAME_SELECTOR / AUTH_LOGIN_PASSWORD_SELECTOR /
         AUTH_LOGIN_SUBMIT_SELECTOR (plus AUTH_LOGIN_USERNAME_SECRET =
         "toloka-username" / AUTH_LOGIN_PASSWORD_SECRET = "toloka-password",
         both already stored in the CLI-tools secret manager) for
         non-interactive login, once the real form field selectors are known.
    """

    SESSION_NAME = "toloka"
    LOGIN_URL = "https://www.toloka.site/login"
    AUTH_CHECK_URL = "https://www.toloka.site"
    # UNVALIDATED generic default -- confirm against the real unauthenticated
    # redirect once the site is reachable.
    AUTH_URL_PATTERN = r"/login|/register"
    # AUTH_SUCCESS_SELECTOR must target a VISIBLE element on the authenticated
    # page. UNVALIDATED -- left blank until a real page snapshot is captured.
    AUTH_SUCCESS_SELECTOR = ""
    # AUTH_LOGIN_FORM_SELECTOR is the preferred "logged out" signal -- its
    # absence on a non-login URL means the user is authenticated. UNVALIDATED
    # generic default (matches any password input or login-form action).
    AUTH_LOGIN_FORM_SELECTOR = 'input[type="password"], form[action*="login"]'
