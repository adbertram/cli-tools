"""Browser automation for trainee.digital.

This account signs in through Clerk with a 6-digit emailed verification code,
not with a password. Validated live 2026-09-03 against the real site:

  1. The Clerk Account Portal at https://accounts.trainee.digital/sign-in
     renders a sign-in card with "Continue with Google", an email field
     (``#identifier-field``) and a password field. Submitting the account
     email (adbertram@gmail.com) does NOT ask for a password -- this account
     has none -- and Clerk goes straight to a "Check your email" / "Enter
     code." factor-one step, mailing the code from notifications@trainee.digital
     with subject "<6 digits> is your verification code".
  2. Entering the code signs the session in. Clerk then sets the ``__session``
     cookie on trainee.digital (and accounts.trainee.digital) and redirects to
     https://trainee.digital. The app's own API calls send a short-lived Clerk
     session token (minted via the frontend API from that cookie) as
     ``Authorization: Bearer <jwt>`` -- see client.py.
  3. ``AUTH_COOKIE_PATTERNS`` therefore treats the presence of the
     ``__session`` cookie on trainee.digital as the authenticated signal.

CLOUDFLARE BOT WALL (accounts portal only): accounts.trainee.digital sits
behind a Cloudflare "Performing security verification" interstitial that does
not clear for headless automation browsers. trainee.digital itself (and its
``/api/*`` endpoints) is not walled, so once the session exists every command
runs headless against the saved profile. The one-time login therefore has to
happen in real system Chrome over CDP against this profile's user-data-dir
(the same bootstrap the mercor and oneforma CLIs use); after that the saved
profile authenticates headless. When the headless handler meets the wall it
raises a BrowserAutomationError naming the profile dir instead of pretending
a password would help. An interactive Turnstile/human-verification prompt is a
hard stop for a human, never something this code clicks through.
"""

from __future__ import annotations

import time

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError

EMAIL_INPUT_SELECTOR = "#identifier-field"
CONTINUE_BUTTON_TEXT = "Continue"
EMAIL_SENT_MARKER = "Check your email"
CODE_PROMPT_MARKER = "Enter code"
# Cloudflare's managed-challenge interstitial served on the accounts portal.
CHALLENGE_TITLE_MARKERS = ("just a moment",)
CHALLENGE_BODY_MARKERS = (
    "performing security verification",
    "verifies you are not a bot",
    "verify you are a human",
    "verify you are not a bot",
)
# A human-verification widget (Turnstile checkbox etc.) is a hard stop.
HUMAN_MARKERS = ("verify you are human", "press and hold", "checkbox challenge")
CHALLENGE_SETTLE_SECONDS = 30
CHALLENGE_POLL_SECONDS = 2
CODE_SENT_TIMEOUT_SECONDS = 30
LOGIN_REDIRECT_TIMEOUT_SECONDS = 45


def _body_text(page) -> str:
    try:
        return page.evaluate("() => document.body ? document.body.innerText || '' : ''")
    except Exception:
        return ""


def _on_challenge(page) -> bool:
    """True when the page shows the Cloudflare managed interstitial."""
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    body = _body_text(page).lower()
    return any(marker in title for marker in CHALLENGE_TITLE_MARKERS) or any(
        marker in body for marker in CHALLENGE_BODY_MARKERS
    )


def _trainee_digital_login_handler(browser: "TraineeDigitalBrowser", page) -> None:
    """Complete trainee.digital's Clerk emailed-code sign-in on the open page.

    The only credential this flow needs is the account email plus the code
    Clerk mails to it (read back through the `google` CLI); there is no
    password. Google SSO and any human-verification prompt are deliberately
    not automated -- they are covered by the bootstrap/raise paths below.
    """
    email = browser.config.account_email

    # Cloudflare managed challenge: wait a bounded time for it to self-clear
    # (real browsers pass it automatically), then raise with the CDP bootstrap
    # instructions that are the documented one-time login path.
    deadline = time.monotonic() + CHALLENGE_SETTLE_SECONDS
    while _on_challenge(page) and time.monotonic() < deadline:
        page.wait_for_timeout(CHALLENGE_POLL_SECONDS * 1000)
    if _on_challenge(page):
        raise BrowserAutomationError(
            "trainee.digital's Clerk portal (accounts.trainee.digital) is "
            "behind a Cloudflare verification interstitial that does not clear "
            "for headless automation. Complete the one-time login in real "
            "system Chrome over CDP against this profile's user-data-dir "
            f"({browser._get_persistent_profile_dir()}) -- the README "
            "'Authentication' section has the exact steps -- then re-run "
            "'trainee-digital auth login' (it will see the saved session)."
        )

    email_field = page.locator(EMAIL_INPUT_SELECTOR).first
    if email_field.count() == 0 or not email_field.is_visible():
        raise BrowserAutomationError(
            "trainee.digital's sign-in page did not render a visible email "
            f"field ({EMAIL_INPUT_SELECTOR}). The page shows: "
            f"{_body_text(page)[:300]!r}; re-capture it before changing this "
            "handler."
        )
    email_field.fill(email)

    # Captured before the click so a code minted by an earlier attempt can
    # never satisfy this one. Clerk's codes are single-use.
    requested_at_ms = int(time.time() * 1000)
    page.get_by_role("button", name=CONTINUE_BUTTON_TEXT, exact=True).first.click()

    # Clerk either goes straight to the emailed-code step (this account has no
    # password) or asks for a password first. The latter is not a path this
    # CLI can automate -- no password is stored for the account -- and means
    # the login surface changed.
    sent_deadline = time.monotonic() + CODE_SENT_TIMEOUT_SECONDS
    while True:
        page.wait_for_timeout(1000)
        body = _body_text(page)
        if EMAIL_SENT_MARKER in body or CODE_PROMPT_MARKER in body:
            break
        if "password" in body.lower():
            raise BrowserAutomationError(
                "trainee.digital's Clerk sign-in asked for a password after "
                f"submitting {email!r}, but this account has no stored password "
                "(it was created via Google OAuth / emailed code). The sign-in "
                "page may have changed; re-capture it before changing this "
                "handler."
            )
        if time.monotonic() >= sent_deadline:
            raise BrowserAutomationError(
                "trainee.digital did not confirm the code step within "
                f"{CODE_SENT_TIMEOUT_SECONDS}s of submitting {email!r}. Page: "
                f"{body[:300]!r}"
            )

    from .email_code import fetch_verification_code

    code = fetch_verification_code(requested_at_ms)

    # The Clerk code field is a single text input rendered visually as slots;
    # playwright cannot hit-test the hidden input, so focus it in-page and send
    # real keystrokes. Six digits auto-submit (validated live 2026-09-03).
    focused = page.evaluate(
        "() => { const el = document.querySelector('input[type=text]'); "
        "if (!el) return 'no-input'; el.focus(); return 'focused'; }"
    )
    if focused != "focused":
        raise BrowserAutomationError(
            "trainee.digital's code step did not render its text input. Page: "
            f"{_body_text(page)[:300]!r}"
        )
    page.keyboard.type(code)

    # Wait for the redirect off the Clerk portal onto trainee.digital.
    redirect_deadline = time.monotonic() + LOGIN_REDIRECT_TIMEOUT_SECONDS
    while time.monotonic() < redirect_deadline:
        page.wait_for_timeout(1000)
        url = page.evaluate("() => location.href")
        if not url.startswith("https://accounts.trainee.digital"):
            return
        body = _body_text(page).lower()
        if any(marker in body for marker in HUMAN_MARKERS):
            raise BrowserAutomationError(
                "trainee.digital's Clerk sign-in is showing a human-verification "
                "prompt. That is a hard stop for automation: complete the "
                "one-time login in real Chrome over CDP against this profile's "
                f"user-data-dir ({browser._get_persistent_profile_dir()})."
            )
        if "incorrect" in body or "invalid code" in body or "expired" in body:
            raise BrowserAutomationError(
                "trainee.digital rejected the emailed verification code "
                "(incorrect, invalid or expired). Re-run 'trainee-digital auth "
                "login' for a fresh code."
            )
    raise BrowserAutomationError(
        "The Clerk sign-in did not redirect off the portal within "
        f"{LOGIN_REDIRECT_TIMEOUT_SECONDS}s. Stopped at: "
        f"{page.evaluate('() => location.href')}"
    )


class TraineeDigitalBrowser(BrowserAutomation):
    """Browser automation for trainee.digital via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks plus one explicit login handler (see module docstring)
    -- the base class owns the rest of the auth lifecycle.
    """

    SESSION_NAME = "trainee-digital"
    # Clerk Account Portal for this instance (validated live 2026-09-03:
    # accounts.trainee.digital/sign-in, the sign_in_url from the Clerk env API).
    LOGIN_URL = "https://accounts.trainee.digital/sign-in"
    # The site root serves the app shell on every request; the authenticated
    # signal is the Clerk ``__session`` cookie on trainee.digital.
    AUTH_CHECK_URL = "https://trainee.digital/"
    AUTH_URL_PATTERN = r"accounts\.trainee\.digital"
    # The Clerk session cookie the site's own backend reads. Presence on the
    # app origin means the session persisted past the portal redirect.
    AUTH_COOKIE_PATTERNS = [r"^__session$"]
    # The portal's email input only exists while signed out; it is the
    # secondary signal for the DOM path.
    AUTH_LOGIN_FORM_SELECTOR = EMAIL_INPUT_SELECTOR
    # No username/password secrets: this account authenticates through Clerk's
    # emailed code. AUTH_LOGIN_HANDLER owns the choreography (submit email,
    # read the code from Gmail, type it) on the already-open page.
    AUTH_LOGIN_HANDLER = staticmethod(_trainee_digital_login_handler)
