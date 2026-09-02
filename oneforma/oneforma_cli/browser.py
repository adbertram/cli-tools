"""Browser automation for OneForma.

This account signs in with Google SSO, not with a OneForma-local password.
Validated live 2026-09-02 against the real site:

  1. GET https://my.oneforma.com/center/login renders a React login card whose
     "Continue with Google" button starts a normal Google OAuth code flow:
     accounts.google.com/v3/signin/identifier with
     client_id=588846154368-gen9mtfsl6rdjuaplgj571dlsm9mnsim.apps.googleusercontent.com,
     scope=openid email profile, redirecting back to
     https://my.oneforma.com/api/common/usermanage/login/oauth2/code/google.
  2. On success OneForma sets its own session cookies (`accessToken`,
     `of-refresh-token`, `JSESSIONID`) and lands on
     https://my.oneforma.com/contributor/dashboard. The site's own XHRs read
     `accessToken` and send it as `Authorization: Bearer <jwt>`; nothing is
     kept in localStorage.

The email/password step on /center/login/password belongs to OneForma-local
accounts. This account has no such password, which is why every attempt to
use one returned "Incorrect email or password." — it was the wrong login path,
not a stale credential.

BOOTSTRAP REQUIREMENT (Google, not OneForma): Google refuses to authenticate
inside headless automation — submitting the account email in a headless
browser lands on accounts.google.com/v3/signin/rejected with "This browser or
app may not be secure." A Google session therefore has to be established ONCE
in real headed Chrome using this profile's user-data-dir, after which the
Google cookies persist here and `Continue with Google` completes silently on
every later headless run. When those cookies are missing or expired, this
module raises a BrowserAutomationError naming the bootstrap rather than
pretending a password would help. Google 2-Step Verification (passkey, phone
tap-Yes, or an SMS code) is part of that one-time bootstrap and needs a human.
"""

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError

GOOGLE_BUTTON_NAME = "Continue with Google"
DASHBOARD_URL = "https://my.oneforma.com/contributor/dashboard"

# Google's own rejection page for automated browsers, and the sign-in states
# that mean the persisted Google session is gone.
GOOGLE_REJECTED_MARKER = "/signin/rejected"
GOOGLE_SIGNIN_MARKER = "accounts.google.com"


def _oneforma_login_handler(browser: "OneformaBrowser", page) -> None:
    """Complete OneForma's Google SSO flow using this profile's Google session.

    The only interaction this can perform is the one click OneForma requires;
    everything after it belongs to Google. If Google needs credentials, a
    second factor, or blocks the browser, that is the one-time bootstrap
    described in the module docstring and it is reported as such.
    """
    google_button = page.get_by_role("button", name=GOOGLE_BUTTON_NAME, exact=True)
    if google_button.count() == 0:
        raise BrowserAutomationError(
            "OneForma's login page did not render its "
            f"{GOOGLE_BUTTON_NAME!r} button. The login page layout changed; "
            "re-capture it before changing this handler."
        )
    google_button.click()

    # Google's redirect chain plus OneForma's callback take a few seconds.
    for _ in range(20):
        page.wait_for_timeout(1000)
        url = page.evaluate("() => location.href")
        if "my.oneforma.com/contributor" in url:
            return
        if GOOGLE_REJECTED_MARKER in url:
            raise BrowserAutomationError(
                "Google refused this browser (\"This browser or app may not "
                "be secure\"). Google does not allow sign-in from headless "
                "automation: establish the Google session once in real headed "
                "Chrome against this profile's user-data-dir "
                f"({browser._get_persistent_profile_dir()}), then re-run "
                "'oneforma auth login'."
            )

    url = page.evaluate("() => location.href")
    if GOOGLE_SIGNIN_MARKER in url:
        raise BrowserAutomationError(
            "Google asked for sign-in instead of reusing this profile's "
            "session, so the stored Google cookies are missing or expired. "
            "Re-run the one-time headed Google bootstrap for the profile at "
            f"{browser._get_persistent_profile_dir()} — Google 2-Step "
            "Verification (passkey, phone prompt, or SMS code) needs a human. "
            f"Stopped at: {url}"
        )
    raise BrowserAutomationError(
        f"Google SSO did not return to OneForma within 20s. Stopped at: {url}"
    )


class OneformaBrowser(BrowserAutomation):
    """Browser automation for OneForma via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks plus one explicit login handler (see module docstring)
    — the base class handles the rest of the auth lifecycle.
    """

    SESSION_NAME = "oneforma"
    LOGIN_URL = "https://my.oneforma.com/center/login"
    AUTH_CHECK_URL = DASHBOARD_URL
    # Validated 2026-09-02: an unauthenticated session loading any /contributor/*
    # URL is redirected to the login flow at /center/login.
    AUTH_URL_PATTERN = r"/center/login"
    # AUTH_LOGIN_FORM_SELECTOR is the preferred "logged out" signal — its
    # absence on a non-login URL means the user is authenticated. The login
    # card always renders the email input (the Google button sits beside it),
    # and neither input exists once authenticated and off /center/login.
    AUTH_LOGIN_FORM_SELECTOR = 'input[type="email"], input[type="password"]'

    # No username/password secrets: this account authenticates through Google,
    # whose session lives in this profile's persistent user-data-dir. The
    # single OneForma-side click is driven by AUTH_LOGIN_HANDLER.
    AUTH_LOGIN_HANDLER = staticmethod(_oneforma_login_handler)
