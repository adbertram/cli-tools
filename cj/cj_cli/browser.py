"""Browser session automation for CJ Affiliate.

CJ has no public API endpoint for applying to (joining) an advertiser
program -- the action only exists in the publisher Marketplace web UI.
This module exposes the minimum declarative hooks the shared
``BrowserAutomation`` base needs to manage that persistent session.

All session lifecycle (login flow, storage-state persistence, auth
verification, logout) is handled by ``cli_tools_shared`` -- this file
intentionally contains no methods beyond ``__init__``.
"""

from cli_tools_shared.auth import BrowserAutomation


CJ_BROWSER_SESSION = "cj"


class CJBrowser(BrowserAutomation):
    """BrowserAutomation hooks for the CJ publisher Marketplace."""

    SESSION_NAME = CJ_BROWSER_SESSION

    # Member login page -- ``auth login`` navigates here for the user.
    LOGIN_URL = "https://members.cj.com/member/login"

    # An authenticated page we can hit to confirm the session is live.
    # The publisher dashboard at /publisher/<id>/dashboard.cj redirects
    # to /login when the session is missing or expired.
    AUTH_CHECK_URL = "https://members.cj.com/member/publisher/dashboard.cj"

    # Any URL containing one of these substrings means we are NOT
    # authenticated (CJ bounces logged-out users back to login pages).
    AUTH_URL_PATTERN = r"/login|/sso|/signup"

    # Absence-of-login-form auth check.  Positive nav-link selectors
    # (e.g. ``a[href*='/member/publisher/']``) break whenever CJ refactors
    # its dashboard HTML — and they did.  A login form, on the other hand,
    # either renders or it does not.  When the URL is not a login URL
    # (already proven by AUTH_URL_PATTERN above) and no password input or
    # login form is on the page, the session is authenticated.
    AUTH_LOGIN_FORM_SELECTOR = (
        'input[type="password"], '
        'input[name="password"], '
        'form[action*="login"], '
        'form#loginForm'
    )

    # Run headed by default -- the CJ login form challenges automation
    # heuristically and the user must sign in interactively the first
    # time anyway.
    AUTOMATION_HEADED = True
