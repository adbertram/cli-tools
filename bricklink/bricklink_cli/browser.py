"""Declarative Bricklink browser-session hooks."""

import re
import time

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.auth import BrowserAutomationError, PlaywrightBrowserAutomation

from .confirmation import CONFIRMATION_CODE_URL_PATTERN
from .managed_auth import (
    get_bricklink_confirmation_code,
    get_lastpass_credential,
    get_lego_two_factor_code,
)


# Robust, visibility-checked click script for LEGO's select-account page.
# LEGO identity renders one account card (the account email) plus a
# continue / select / use-this-account control. The exact DOM is undocumented
# and changes across LEGO's releases, so instead of a fragile CSS selector we
# match by accessible text on any visible, enabled button / role=button / link.
# No username or password is ever entered on this page.
SELECT_ACCOUNT_CLICK_JS = r"""() => {
    const verbs = /continue|select|use this account/i;
    const isActionable = (el) => {
        const rect = el.getBoundingClientRect();
        if (!rect || rect.width === 0 || rect.height === 0) return false;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none') return false;
        if (style.opacity === '0') return false;
        if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
        return true;
    };
    const textOf = (el) => {
        const own = (el.innerText || el.textContent || '').trim();
        const aria = (el.getAttribute && el.getAttribute('aria-label')) || '';
        const title = (el.getAttribute && el.getAttribute('title')) || '';
        return (own + ' ' + aria + ' ' + title).replace(/\s+/g, ' ');
    };
    const candidates = Array.from(document.querySelectorAll(
        'button, [role="button"], a'
    ));
    const match = candidates.find(
        (el) => isActionable(el) && verbs.test(textOf(el))
    );
    if (!match) return false;
    match.click();
    return true;
}"""


activity = get_activity_logger("bricklink")


class BricklinkBrowser(PlaywrightBrowserAutomation):
    SESSION_NAME = "bricklink"
    LOGIN_URL = "https://www.bricklink.com/v2/login.page"
    AUTH_CHECK_URL = "https://www.bricklink.com/myMsg.asp"
    # ``identity.lego.com/<locale>/login`` is the real expired-session
    # landing page (e.g. ``identity.lego.com/en-US/login?ReturnUrl=...``).
    # The previous pattern ``identity\.lego\.com/login`` did not match
    # because the locale segment sits between the host and ``/login``.
    # We anchor on the host and a ``login`` segment anywhere in the path
    # so live-auth detection works for every locale.
    AUTH_URL_PATTERN = (
        r"identity\.lego\.com/(?:[^?]*login|[^?]*select-account|auth/two-factor-authentication)"
        r"|/v2/login\.page"
    )
    # LEGO identity's account-selection interstitial. Reached when an SSO
    # session already exists and BrickLink requests ``prompt=select_account``
    # (``identity.lego.com/select-account?clientname=BrickLink&...``). It is a
    # login-flow state, NOT an authenticated BrickLink page: it must not be
    # treated as auth success by ``_check_auth`` or its fallback.
    SELECT_ACCOUNT_URL_PATTERN = re.compile(
        r"identity\.lego\.com/[^?#]*select-account", re.IGNORECASE
    )
    # Shared auth probing checks this before the broad ``AUTH_SUCCESS_URL``.
    AUTH_FAILURE_URL_PATTERN = CONFIRMATION_CODE_URL_PATTERN.pattern
    AUTH_SUCCESS_URL = r"bricklink\.com"
    AUTH_COOKIE_PATTERNS = ()
    PLAYWRIGHT_EXECUTABLE_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    AUTH_LOGIN_USERNAME_SELECTOR = "#username"
    AUTH_LOGIN_PASSWORD_SELECTOR = "#password"
    AUTH_LOGIN_SUBMIT_SELECTOR = 'button[type="submit"]'
    AUTH_LOGIN_AUTOMATION_TIMEOUT = 90

    MESSAGES_URL = "https://www.bricklink.com/myMsg.asp"
    CONTACT_URL = "https://www.bricklink.com/contact.asp"
    REFUND_URL = "https://www.bricklink.com/v3/order/refund.page"
    STORE_SETTINGS_URL = "https://www.bricklink.com/v2/mystore/display.page"
    SHIPPING_SETTINGS_URL = "https://www.bricklink.com/v2/mystore/shipping.page"
    SHIPPING_METHOD_EDIT_URL = "https://www.bricklink.com/v2/mystore/shipping_edit.page"
    # INVOICE_URL removed 2026-05-16; Bricklink retired `/v3/billing/invoice.page`
    # and the `invoice` command group along with it. See browser_runtime.py for
    # the Invoices comment block.
    ORDER_SEARCH_URL = "https://www.bricklink.com/orderSearch.asp?a=p"
    WANTED_NOTIFY_URL = "https://www.bricklink.com/wantedNotify.asp"

    def _complete_noninteractive_login(self, page) -> None:
        """Authenticate with managed LastPass credentials and Gmail codes."""
        requested_after = int(time.time()) - 10
        # LEGO identity can redirect straight to select-account
        # (prompt=select_account) when an SSO session already exists, in which
        # case no username/password form is rendered. Skip credential entry and
        # go directly to the account-selection + poll loop. No credential is
        # entered on the select-account page.
        if not self._is_select_account_page(page):
            first_step = (
                ("username", page.locator(self.AUTH_LOGIN_USERNAME_SELECTOR)),
                ("submit", page.locator(self.AUTH_LOGIN_SUBMIT_SELECTOR)),
            )
            for label, locator in first_step:
                if locator.count() != 1 or not locator.first.is_visible():
                    raise BrowserAutomationError(
                        f"BrickLink login requires one visible {label} control."
                    )
            if not first_step[1][1].first.is_enabled():
                raise BrowserAutomationError("BrickLink login submit control is disabled.")

            username = get_lastpass_credential("username")
            try:
                self._fill_login_secret(page, self.AUTH_LOGIN_USERNAME_SELECTOR, username)
                first_step[1][1].first.click()
            finally:
                username = None

            password_control = page.locator(self.AUTH_LOGIN_PASSWORD_SELECTOR)
            password_deadline = time.time() + 15
            while time.time() < password_deadline:
                if password_control.count() == 1 and password_control.first.is_visible():
                    break
                page.wait_for_timeout(250)
            else:
                raise BrowserAutomationError(
                    "BrickLink login did not reveal one visible password control"
                    f"{self._login_page_error_suffix(page)}"
                )
            submit_control = page.locator(self.AUTH_LOGIN_SUBMIT_SELECTOR)
            if submit_control.count() != 1 or not submit_control.first.is_visible():
                raise BrowserAutomationError(
                    "BrickLink password step requires one visible submit control."
                )
            if not submit_control.first.is_enabled():
                raise BrowserAutomationError(
                    "BrickLink password-step submit control is disabled."
                )

            password = get_lastpass_credential("password")
            try:
                self._fill_login_secret(page, self.AUTH_LOGIN_PASSWORD_SELECTOR, password)
                submit_control.first.click()
            finally:
                password = None
        else:
            activity.info("LEGO select-account page active; skipping credential entry")

        deadline = time.time() + self.AUTH_LOGIN_AUTOMATION_TIMEOUT
        confirmation_submitted = False
        lego_two_factor_submitted = False
        select_account_submitted = False
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            if self._check_auth(page):
                return
            if (
                not select_account_submitted
                and self._is_select_account_page(page)
            ):
                activity.info("Selecting account on LEGO select-account page")
                self._click_select_account_control(page)
                select_account_submitted = True
            if (
                not lego_two_factor_submitted
                and "identity.lego.com/auth/two-factor-authentication"
                in (page.url or "")
            ):
                code_selector = 'input[name="token"][autocomplete="one-time-code"]'
                code_control = page.locator(code_selector)
                if code_control.count() != 1 or not code_control.first.is_visible():
                    raise BrowserAutomationError(
                        "LEGO two-factor authentication requires one visible code control."
                    )
                submit_control = page.locator(self.AUTH_LOGIN_SUBMIT_SELECTOR)
                if submit_control.count() != 1 or not submit_control.first.is_visible():
                    raise BrowserAutomationError(
                        "LEGO two-factor authentication requires one visible submit control."
                    )
                if not submit_control.first.is_enabled():
                    raise BrowserAutomationError(
                        "LEGO two-factor authentication submit control is disabled."
                    )
                activity.info("Completing LEGO two-factor authentication")
                code = get_lego_two_factor_code(requested_after=requested_after)
                try:
                    self._fill_login_secret(page, code_selector, code)
                    submit_control.first.click()
                finally:
                    code = None
                lego_two_factor_submitted = True
            if (
                not confirmation_submitted
                and CONFIRMATION_CODE_URL_PATTERN.search(page.url or "")
            ):
                code_input = page.query_selector("#confirmation-code")
                if not code_input:
                    raise BrowserAutomationError(
                        "BrickLink confirmation code input #confirmation-code was not found."
                    )
                code = get_bricklink_confirmation_code(
                    requested_after=requested_after
                )
                try:
                    self._fill_login_secret(page, "#confirmation-code", code)
                    submitted = page.evaluate(
                        """() => {
                            const buttons = Array.from(document.querySelectorAll('button'));
                            const button = buttons.find(
                                (b) => (b.innerText || '').trim() === 'Submit'
                            );
                            if (!button) return false;
                            button.click();
                            return true;
                        }"""
                    )
                finally:
                    code = None
                if not submitted:
                    raise BrowserAutomationError(
                        "BrickLink confirmation code Submit button was not found."
                    )
                confirmation_submitted = True
        raise BrowserAutomationError(
            "Managed BrickLink login did not reach an authenticated state within "
            f"{self.AUTH_LOGIN_AUTOMATION_TIMEOUT} seconds."
        )

    def _on_authenticated(self, page) -> None:
        """Finalize the BrickLink session on a protected page before closing."""
        activity.info("Finalizing BrickLink session on protected page")
        page.goto(self.AUTH_CHECK_URL)
        activity.info(
            "Protected-page finalization authenticated=%s",
            self._check_auth(page),
        )

    @classmethod
    def _is_select_account_page(cls, url_or_page) -> bool:
        """Return True when ``url_or_page`` is LEGO's select-account page."""
        url = getattr(url_or_page, "url", url_or_page) or ""
        return bool(cls.SELECT_ACCOUNT_URL_PATTERN.search(url))

    def _click_select_account_control(self, page) -> None:
        """Click the account-continue control on LEGO's select-account page.

        The page is a login-flow state, not a BrickLink page, so no username
        or password is entered here. The exact LEGO DOM is undocumented, so
        ``SELECT_ACCOUNT_CLICK_JS`` uses a generic strategy that clicks the
        first visible, enabled ``button``/``[role=button]``/``a`` whose
        accessible text matches continue/select/use-this-account.
        """
        clicked = page.evaluate(SELECT_ACCOUNT_CLICK_JS)
        if not clicked:
            raise BrowserAutomationError(
                "LEGO select-account page did not expose a visible "
                "continue/select control."
            )

    @staticmethod
    def _login_page_error_suffix(page) -> str:
        """Return a ``: <reason>`` suffix from the login page's visible error.

        LEGO identity rejects an unknown identifier with a visible validation
        message (e.g. "Whoops, we don't recognise that username."). Surfacing it
        makes a failed managed login self-explanatory instead of a generic
        "no password control" error. The text is public UI copy, never a secret.
        """
        try:
            messages = page.evaluate(
                "() => Array.from(document.querySelectorAll("
                "'[class*=error],[role=alert],[aria-invalid=\"true\"]'))"
                ".map(e => (e.innerText || e.getAttribute('aria-label') || '').trim())"
                ".filter(Boolean)"
            )
        except Exception:  # noqa: BLE001
            return ""
        if not isinstance(messages, list):
            return ""
        seen: list[str] = []
        for message in messages:
            text = " ".join(str(message).split())
            if text and text not in seen:
                seen.append(text)
        if not seen:
            return ""
        return f": {seen[0]}"

    @staticmethod
    def _fill_login_secret(page, selector: str, secret: str) -> None:
        """Fill a verified control, redacting the secret from any surfaced error.

        The underlying fill embeds the value into a page-evaluated JS string,
        so a raw harness/Playwright error can echo the secret. Keep the real
        error type and a redacted message so the failing control and cause are
        visible instead of swallowed, but suppress the exception chain
        (``from None``) so the original cause — whose own message/args may still
        contain the secret — is never rendered in a traceback.
        """
        try:
            page.fill(selector, secret)
        except Exception as exc:
            message = BricklinkBrowser._redact_secret(str(exc), secret)
            raise BrowserAutomationError(
                f"BrickLink could not fill managed login control {selector!r}: "
                f"{type(exc).__name__}: {message}"
            ) from None

    @staticmethod
    def _redact_secret(text: str, secret: str) -> str:
        """Remove every known encoding of ``secret`` from diagnostic ``text``."""
        if not secret:
            return text
        import json as _json

        redacted = text.replace(secret, "<redacted>")
        # The fill path serializes the value with json.dumps before embedding it
        # in page JS, so a harness error can echo the JSON-escaped form.
        json_form = _json.dumps(secret)
        redacted = redacted.replace(json_form, "<redacted>")
        redacted = redacted.replace(json_form[1:-1], "<redacted>")
        return redacted

def normalize_subject(subject: str) -> str:
    value = subject.strip()
    while value.lower().startswith("re: "):
        value = value[4:]
    value = re.sub(r"\s*\(view order\)\s*$", "", value, flags=re.IGNORECASE)
    value = value.replace("#", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value.lower()
