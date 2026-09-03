"""Browser automation for HumanRail."""

from cli_tools_shared.auth import BrowserAutomation


class HumanrailBrowser(BrowserAutomation):
    """Browser automation for HumanRail via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks only — no methods. The base class handles auth lifecycle
    using these class-level constants.

    HumanRail (routehuman.com) is a React SPA ("Worker Console"). Validated
    live 2026-09-02 against the real login form and post-login session state:
      - Login form: GET-rendered React form at /login with
        <input id="email" name="email" type="email">,
        <input id="password" name="password" type="password">, and a
        <button type="submit">Sign in</button>. Submitting POSTs JSON to
        /api/auth/login, which returns {"token", "worker_id"}.
      - The frontend stores the session as a bearer token in localStorage
        under the key "ee_auth_token" (plus "ee_worker_id") — there is no
        session cookie. Every subsequent API call reads that token and sends
        it as `Authorization: Bearer <token>`.
      - An authenticated visit to /login redirects client-side to /dashboard
        (a page that renders correctly). /onboarding is a known-buggy route
        on this account (throws a minified React error and unmounts to a
        blank #root) but that does not affect login, the auth token, or any
        other route — AUTH_CHECK_URL below avoids it.
    """

    SESSION_NAME = "humanrail"
    LOGIN_URL = "https://routehuman.com/login"
    # /dashboard renders normally for an authenticated session and is the
    # client-side redirect target when an authenticated browser opens /login.
    AUTH_CHECK_URL = "https://routehuman.com/dashboard"
    # Logged-out visits to protected routes bounce to /login (validated); a
    # brand-new session also lands on /register during sign-up.
    AUTH_URL_PATTERN = r"/login|/register"
    # Preferred "logged out" signal: the login form's password input is
    # present only when NOT authenticated.
    AUTH_LOGIN_FORM_SELECTOR = 'input[name="password"]'
    # Most robust signal for this token-based (non-cookie) session: the
    # bearer token HumanRail's own frontend reads on every API call.
    AUTH_STORAGE_KEY = "ee_auth_token"

    # Non-interactive credential-fill login (validated live 2026-09-02).
    AUTH_LOGIN_USERNAME_SELECTOR = 'input[name="email"]'
    AUTH_LOGIN_PASSWORD_SELECTOR = 'input[name="password"]'
    AUTH_LOGIN_SUBMIT_SELECTOR = 'button[type="submit"]'
    AUTH_LOGIN_USERNAME_SECRET = "humanrail-username"
    AUTH_LOGIN_PASSWORD_SECRET = "humanrail-password"
