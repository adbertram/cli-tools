"""Browser automation for CrowdGen (Appen).

Selectors and flow facts below were validated live 2026-09-03 against the real
site through headed real Chrome over CDP (Kasada-protected API):

  - The worker portal is a React SPA at app.crowdgen.com. Unauthenticated
    visits to "/" or "/login" render the login view: a single
    <form id="register"> whose inputs are #register_email (type=text,
    placeholder "Enter Email Address") and #register_password (type=password,
    placeholder "Enter Password"), submitted by a <button type="submit">
    labelled "Sign In". The input ids are captured verbatim from a live DOM
    snapshot kept at tests/fixtures/login_page.html (206 KB, 2026-09-03).
  - Login POSTs JSON to https://api.crowdgen.com/api/v1/user/auth/login
    (observed). Login MFA is a TOTP authenticator app (Google/Microsoft/Authy).
  - Sessions are cookie/JWT based: the SPA reads an auth cookie ("authToken" /
    "authjwt" constants) and sends `Authorization: Bearer <token>` to
    api.crowdgen.com (constant map in the deployed bundle main.b5c37aa5.js).
  - /api/v1/* POSTs (login, register-new) sit behind Kasada (kpsdk). That only
    affects fresh registration/login from automation; the authenticated worker
    session is what this CLI persists and reuses.

TOTP hooks are intentionally NOT set yet: the authenticator-app TOTP challenge
is only reachable after an account completes sign-up onboarding (mobile
number -> address/agreements -> payout -> government-ID check), all of which
are human gates. Once that exists and `crowdgen auth login` reaches the TOTP
step, capture the TOTP input/submit selectors from the live page and set
AUTH_LOGIN_TOTP_SELECTOR / AUTH_LOGIN_TOTP_SUBMIT_SELECTOR / AUTH_LOGIN_TOTP_SECRET
(secret-manager Base32 seed name "crowdgen-totp-seed") here.
"""

from cli_tools_shared.auth import BrowserAutomation


class CrowdgenBrowser(BrowserAutomation):
    """Browser automation for CrowdGen via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks only — no methods. The base class handles auth lifecycle
    using these class-level constants.
    """

    SESSION_NAME = "crowdgen"
    LOGIN_URL = "https://app.crowdgen.com/login"
    # Logged-out visits to "/" SPA-redirect to the login view (validated live);
    # an authenticated session lands on the dashboard instead.
    AUTH_CHECK_URL = "https://app.crowdgen.com/"
    AUTH_URL_PATTERN = r"/login|/apply/signup|/forgot-password|/reset-password|/register"
    # Preferred "logged out" signal: the password input (#register_password) is
    # rendered only on the login view. Absent on a non-login URL => authenticated.
    AUTH_LOGIN_FORM_SELECTOR = "input#register_password"

    # Non-interactive credential-fill login (selectors validated live against
    # tests/fixtures/login_page.html, 2026-09-03).
    AUTH_LOGIN_USERNAME_SELECTOR = "input#register_email"
    AUTH_LOGIN_PASSWORD_SELECTOR = "input#register_password"
    AUTH_LOGIN_SUBMIT_SELECTOR = 'button[type="submit"]'
    AUTH_LOGIN_USERNAME_SECRET = "crowdgen-username"
    AUTH_LOGIN_PASSWORD_SECRET = "crowdgen-password"

    # TOTP challenge step: not yet reachable (account onboarding is human
    # gated) — see module docstring. Left empty on purpose; partial TOTP
    # configuration is rejected by the shared engine.
    AUTH_LOGIN_TOTP_SELECTOR = ""
    AUTH_LOGIN_TOTP_SUBMIT_SELECTOR = ""
    AUTH_LOGIN_TOTP_SECRET = ""
