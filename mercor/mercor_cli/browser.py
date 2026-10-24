"""Browser automation for Mercor (work.mercor.com).

Mercor's worker app signs in through Firebase Auth. Validated live 2026-09-03
against Adam's real account (adbertram@gmail.com):

  1. GET https://work.mercor.com/login renders a React login card with a
     single `<input type="email">` (placeholder "your@email.com") plus "Login"
     and "Sign up" buttons -- there is no password field. "Or continue with"
     offers Google and Okta SSO. A cookie-consent dialog ("We Value Your
     Privacy") may overlay the card and needs "Reject All" before the form is
     reachable.
  2. Submitting the email with "Login" mails a one-time Firebase sign-in link
     and swaps the card for "Check your inbox -- We've sent you an activation
     link." The email comes FROM "Mercor <auth@mercor.com>" with subject
     "Sign in to Mercor" and carries a Firebase action URL
     (`https://mercor-prod-firebase.firebaseapp.com/__/auth/action?mode=signIn&oobCode=...`).
     Opening it lands on the authenticated app at https://work.mercor.com/explore.
  3. The authenticated session is the `token` cookie on `work.mercor.com` (the
     Firebase ID token JWT; ~12h `exp`). Firebase also keeps the refresh token
     in localStorage, so later headless runs restore the session and re-mint
     the cookie. The site's own API calls send that JWT as
     `Authorization: Bearer <token>` -- see client.py.

  BOT-PROTECTION REALITY (validated live): the login page also runs reCAPTCHA
  Enterprise, whose token is exchanged at
  `content-firebaseappcheck.googleapis.com/.../exchangeRecaptchaEnterpriseToken`
  for a Firebase App Check token. A headless Chromium gets HTTP 403 there and
  Firebase throttles App Check for ~24h ("AppCheck: Requests throttled due to
  403"), which blocks the login POST. Real system Chrome over CDP (normal
  fingerprint, aged persistent profile) passes. `AUTH_LOGIN_HANDLER` therefore
  drives the email-magic-link flow headlessly when it can, and raises a
  `BrowserAutomationError` naming the throttle plus the CDP bootstrap when it
  cannot. The wall's markers ("Requests throttled due to 403" /
  "appCheck/throttled") are written to the browser **console**, and the CDP
  harness exposes no page-console stream to the login handler, so they rarely
  land in the page body the handler can read. A headless attempt that times
  out with the login card unchanged is therefore classified as the wall and
  raises the same actionable error (see `_bot_wall_error`). The one-time
  bootstrap (see README "Authentication") uses that CDP path; once the profile
  is authenticated, `auth status` and `tasks list` run headlessly against the
  saved session.

`AUTH_LOGIN_HANDLER` reads the emailed link back through the repo-owned
`google` CLI (magic_link.py).
"""

from __future__ import annotations

import time

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError

EMAIL_INPUT_SELECTOR = 'input[type="email"]'
LOGIN_BUTTON_TEXT = "Login"
CONSENT_REJECT_TEXT = "Reject All"
# Text the page renders once the link has been mailed.
LINK_SENT_MARKER = "Check your inbox"
LINK_SENT_TIMEOUT_SECONDS = 30
VERIFY_TIMEOUT_SECONDS = 90
# Firebase App Check throttle markers surfaced by Mercor's login page when a
# bot-classified browser tries to sign in (see module docstring).
THROTTLE_MARKERS = ("Requests throttled due to 403", "appCheck/throttled")
# Body text of the untouched login card (validated live): when a submit times
# out and the card still shows these, nothing in the UI changed -- the failure
# is below the page (see module docstring).
LOGIN_CARD_MARKERS = ("Continue to Mercor", "Sign up")


def _first_visible(page, selector: str, *, text: str = None):
    """The first visible element matching ``selector`` (and ``text`` when given)."""
    for candidate in page.locator(selector).all():
        if not candidate.is_visible():
            continue
        if text is not None and (candidate.inner_text() or "").strip() != text:
            continue
        return candidate
    return None


def _is_headless(browser: "MercorBrowser") -> bool:
    """Whether this login is running headless (default True for mercor)."""
    probe = getattr(browser, "_headless_enabled", None)
    try:
        return bool(probe()) if callable(probe) else True
    except Exception:  # pragma: no cover -- defensive; never hides the wall
        return True


def _still_on_login_card(body_text: str) -> bool:
    """True when ``body_text`` still shows the untouched login card.

    The bot wall leaves the card fully unchanged (its markers live in the
    browser console, which the CDP harness does not surface to this handler),
    so a headless timeout with the card still present is the wall's signature.
    """
    return all(marker in body_text for marker in LOGIN_CARD_MARKERS)


def _bot_wall_error(
    email: str, url: str, body_text: str, profile_dir: str
) -> BrowserAutomationError:
    """Actionable error for Mercor's reCAPTCHA Enterprise / App Check wall.

    A headless Chromium is refused with HTTP 403 on the App Check token
    exchange and Firebase throttles the app for ~24h. The markers live in the
    browser console (``content-firebaseappcheck.googleapis.com/.../``
    ``exchangeRecaptchaEnterpriseToken``), never in the page body, so the login
    card stays silent and no link is mailed.
    """
    return BrowserAutomationError(
        "Mercor did not confirm it sent a sign-in link within "
        f"{LINK_SENT_TIMEOUT_SECONDS}s of submitting {email!r}, and the login "
        "card never changed. That silence is the signature of Mercor's bot "
        "wall: the login page runs reCAPTCHA Enterprise + Firebase App Check, "
        "which refuses a headless Chromium with HTTP 403 on the App Check "
        "token exchange "
        "(content-firebaseappcheck.googleapis.com/.../exchangeRecaptchaEnterpriseToken) "
        "and throttles the app for ~24h ('AppCheck: Requests throttled due to "
        "403' / 'appCheck/throttled'). Those markers are written to the "
        "browser console, not the page, so no link is mailed and no error text "
        "appears. Headless login only works once a real-Chrome session already "
        "exists in this profile; run the one-time bootstrap from the mercor "
        "README 'Bot-protection bootstrap' section against this profile "
        f"directory:\n{profile_dir}\n"
        "Then re-run 'mercor auth status'. Evidence: page was at "
        f"{url} and showed {body_text[:200]!r}."
    )


def _generic_timeout_error(
    email: str, url: str, body_text: str, *, headless: bool
) -> BrowserAutomationError:
    """Fallback error for a login timeout that is not the silent-wall shape."""
    return BrowserAutomationError(
        "Mercor did not confirm it sent a sign-in link within "
        f"{LINK_SENT_TIMEOUT_SECONDS}s of submitting {email!r} "
        f"(headless={headless}). The page is at {url} and shows: "
        f"{body_text[:300]!r}. If Mercor mailed the link anyway, it is "
        "single-use: re-run the login and open the fresh link. If no link "
        "arrived, confirm ACCOUNT_EMAIL is the address Mercor mails to and "
        "that the mail (from auth@mercor.com, subject 'Sign in to Mercor') is "
        "not in spam. If this happened under HEADLESS=true with the card never "
        "changing, Mercor's bot wall is the likely cause -- see the mercor "
        "README 'Bot-protection bootstrap' section for the real-Chrome login "
        "that bypasses it."
    )


def _mercor_login_handler(browser: "MercorBrowser", page) -> None:
    """Submit the account email, read the emailed link, and open it."""
    email = browser.config.account_email

    consent = _first_visible(page, "button", text=CONSENT_REJECT_TEXT)
    if consent is not None:
        consent.click()
        page.wait_for_timeout(800)

    email_field = _first_visible(page, EMAIL_INPUT_SELECTOR)
    if email_field is None:
        raise BrowserAutomationError(
            "Mercor's login page did not render a visible email input "
            f"({EMAIL_INPUT_SELECTOR}). The login page layout changed; "
            "re-capture it before changing this handler."
        )
    login_button = _first_visible(page, "button", text=LOGIN_BUTTON_TEXT)
    if login_button is None:
        raise BrowserAutomationError(
            "Mercor's login page did not render a visible "
            f"{LOGIN_BUTTON_TEXT!r} button. The login page layout changed; "
            "re-capture it before changing this handler."
        )

    email_field.fill(email)
    # Captured before the click so a link minted by an earlier attempt can
    # never satisfy this one. Mercor's links are single-use.
    requested_at_ms = int(time.time() * 1000)
    login_button.click()

    deadline = time.monotonic() + LINK_SENT_TIMEOUT_SECONDS
    body_text = ""
    while True:
        page.wait_for_timeout(1000)
        body_text = page.evaluate("() => document.body.innerText || ''")
        if LINK_SENT_MARKER in body_text:
            break
        if any(marker in body_text for marker in THROTTLE_MARKERS):
            raise BrowserAutomationError(
                "Mercor's login page reports Firebase App Check throttling "
                f"('{THROTTLE_MARKERS[0]}'). Headless Chromium is rejected by "
                "Mercor's reCAPTCHA Enterprise / App Check wall; the one-time "
                "bootstrap must run in real Chrome over CDP against this "
                "profile's user-data-dir "
                f"({browser._get_persistent_profile_dir()}). See the mercor "
                "README 'Authentication' section for the exact steps."
            )
        if time.monotonic() >= deadline:
            try:
                url = page.evaluate("() => location.href")
            except Exception:  # pragma: no cover -- page may have navigated away
                url = ""
            headless = _is_headless(browser)
            if headless and _still_on_login_card(body_text):
                raise _bot_wall_error(
                    email,
                    url,
                    body_text,
                    str(browser._get_persistent_profile_dir()),
                )
            raise _generic_timeout_error(email, url, body_text, headless=headless)

    from .magic_link import fetch_sign_in_link

    page.goto(fetch_sign_in_link(requested_at_ms))

    deadline = time.monotonic() + VERIFY_TIMEOUT_SECONDS
    while True:
        page.wait_for_timeout(1000)
        url = page.evaluate("() => location.href")
        if "/login" not in url:
            return
        if time.monotonic() >= deadline:
            raise BrowserAutomationError(
                "Mercor's sign-in link did not authenticate the session within "
                f"{VERIFY_TIMEOUT_SECONDS}s -- the browser is still on {url}. The "
                "link may have already been used or expired."
            )


class MercorBrowser(BrowserAutomation):
    """Browser automation for Mercor via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks plus one explicit login handler (see module docstring) --
    the base class owns the rest of the auth lifecycle.
    """

    SESSION_NAME = "mercor"
    LOGIN_URL = "https://work.mercor.com/login"
    # The app root redirects an authenticated session into the app and an
    # unauthenticated one to /login (validated live 2026-09-03).
    AUTH_CHECK_URL = "https://work.mercor.com/"
    AUTH_URL_PATTERN = r"/login|/register"
    # The session JWT cookie Mercor's own backend reads; set on
    # work.mercor.com by the app after Firebase restores the user.
    AUTH_COOKIE_PATTERNS = [r"^token$"]
    # The login card's email input only exists while signed out; it is the
    # secondary signal for the DOM path.
    AUTH_LOGIN_FORM_SELECTOR = EMAIL_INPUT_SELECTOR

    # Mercor has no password: the single-page USERNAME/PASSWORD/SUBMIT
    # constants are deliberately unset and the login is fully driven by
    # AUTH_LOGIN_HANDLER (see module docstring for the bot-wall caveat).
    AUTH_LOGIN_HANDLER = staticmethod(_mercor_login_handler)
