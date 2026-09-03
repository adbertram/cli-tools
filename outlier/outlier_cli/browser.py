"""Browser automation for Outlier (app.outlier.ai).

Outlier is a Next.js SPA with a passwordless account model. Validated live
2026-09-02 against Adam's real account:

  1. GET https://app.outlier.ai/login renders a React card with
     `<input type="email" id="email-login" data-testid="email-input">` and a
     `<button type="submit">Continue</button>`. There is no password field —
     "Continue with Google" and the emailed link are the only two paths.
     The card is rendered TWICE (a hidden layout copy plus the visible one),
     so every control has to be picked by visibility, not by index.
  2. Submitting the email mails a one-time link
     `https://app.outlier.ai/login/verify?token=...&ajs=...` and swaps the
     card for "To continue, click the link sent to <email>". Opening that URL
     POSTs `/internal/login/outlier/magic-link-verify` and lands on the
     authenticated app.
  3. The authenticated session is the `_jwt` cookie on `.outlier.ai` (a JWT
     whose payload carries `userId`, `loginMethod:"magic_link"` and a ~3-day
     `exp`). Nothing is kept in localStorage. The site's own XHRs additionally
     send `X-CSRF-Token` read from the `_csrf` cookie — see client.py.

`AUTH_LOGIN_HANDLER` drives all of that headlessly: no terminal prompt and no
visible browser, because MicroWorker's worker subagents run without a tty.
The emailed link is read back through the repo-owned `google` CLI
(magic_link.py).

Note on `AUTH_TOKEN_COOKIE`: the shared engine's JWT path rejects a token whose
payload has no `aud` claim, and Outlier's `_jwt` has none. The cookie-name
match (`AUTH_COOKIE_PATTERNS`) is therefore the correct high-signal hook here.
"""

from __future__ import annotations

import time

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError

EMAIL_INPUT_SELECTOR = 'input[type="email"][data-testid="email-input"]'
CONTINUE_BUTTON_SELECTOR = 'button[type="submit"]'
CONTINUE_BUTTON_TEXT = "Continue"
# Text the page renders once the link has been mailed.
LINK_SENT_MARKER = "click the link sent to"
LINK_SENT_TIMEOUT_SECONDS = 30
VERIFY_TIMEOUT_SECONDS = 60


def _first_visible(page, selector: str, *, text: str = None):
    """The first visible element matching ``selector`` (and ``text`` when given).

    Outlier renders the login card twice — a zero-size copy first, then the
    real one — so `locator(...).first` would target the hidden element.
    """
    for candidate in page.locator(selector).all():
        if not candidate.is_visible():
            continue
        if text is not None and (candidate.inner_text() or "").strip() != text:
            continue
        return candidate
    return None


def _outlier_login_handler(browser: "OutlierBrowser", page) -> None:
    """Submit the account email, read the emailed link, and open it."""
    email = browser.config.account_email

    email_field = _first_visible(page, EMAIL_INPUT_SELECTOR)
    if email_field is None:
        raise BrowserAutomationError(
            "Outlier's login page did not render a visible email input "
            f"({EMAIL_INPUT_SELECTOR}). The login page layout changed; "
            "re-capture it before changing this handler."
        )
    continue_button = _first_visible(
        page, CONTINUE_BUTTON_SELECTOR, text=CONTINUE_BUTTON_TEXT
    )
    if continue_button is None:
        raise BrowserAutomationError(
            "Outlier's login page did not render a visible "
            f"{CONTINUE_BUTTON_TEXT!r} button. The login page layout changed; "
            "re-capture it before changing this handler."
        )

    email_field.fill(email)
    # Captured before the click so a link minted by an earlier attempt can
    # never satisfy this one. Outlier's links are single-use.
    requested_at_ms = int(time.time() * 1000)
    continue_button.click()

    deadline = time.monotonic() + LINK_SENT_TIMEOUT_SECONDS
    while True:
        page.wait_for_timeout(1000)
        body_text = page.evaluate("() => document.body.innerText || ''")
        if LINK_SENT_MARKER in body_text:
            break
        if time.monotonic() >= deadline:
            raise BrowserAutomationError(
                "Outlier did not confirm it sent a sign-in link within "
                f"{LINK_SENT_TIMEOUT_SECONDS}s of submitting {email!r}. The page "
                f"is at {page.evaluate('() => location.href')}."
            )

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
                "Outlier's sign-in link did not authenticate the session within "
                f"{VERIFY_TIMEOUT_SECONDS}s — the browser is still on {url}. The "
                "link may have already been used or expired."
            )


class OutlierBrowser(BrowserAutomation):
    """Browser automation for Outlier via cli_tools_shared.auth.BrowserAutomation.

    Declarative hooks plus one explicit login handler (see module docstring) —
    the base class owns the rest of the auth lifecycle.
    """

    SESSION_NAME = "outlier"
    LOGIN_URL = "https://app.outlier.ai/login"
    # The app root redirects an authenticated session into the app and an
    # unauthenticated one to /login (validated live 2026-09-02).
    AUTH_CHECK_URL = "https://app.outlier.ai/"
    AUTH_URL_PATTERN = r"/login"
    # Highest-signal hook Outlier offers: the session JWT cookie its own
    # backend reads. Set on `.outlier.ai` by /internal/login/... on success.
    AUTH_COOKIE_PATTERNS = [r"^_jwt$"]
    # Secondary signal for the DOM path: the login card's email input only
    # exists while signed out.
    AUTH_LOGIN_FORM_SELECTOR = EMAIL_INPUT_SELECTOR

    # Fully non-interactive: no password exists for this account, so the
    # single-page USERNAME/PASSWORD/SUBMIT constants are deliberately unset.
    AUTH_LOGIN_HANDLER = staticmethod(_outlier_login_handler)
