"""Non-interactive Progress Entra (Microsoft) SSO login for ServiceNow.

progress1.service-now.com is fronted by a SAML redirect to
``login.microsoftonline.com``. When the saved browser session expires, every
ServiceNow page silently becomes the Microsoft sign-in page, so the CLI must be
able to walk that sign-in flow again without a human at the terminal.

Credential and MFA sourcing follow the ``browser-automation`` skill:

* the account password comes from the managed ``lastpass`` CLI — never from a
  prompt, never from a file in this repository, and it is never printed,
  logged, or written anywhere;
* the MFA code comes from the ``imessage`` CLI, because this account publishes
  a ``OneWaySMS`` factor alongside the Microsoft Authenticator push.

There is exactly one path through each step. A missing credential, an absent
SMS factor, a rejected password, or a challenge that only a physical device can
answer raises immediately and names what happened. Nothing here substitutes a
default, retries around a wall, or degrades to a partial session.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime, timedelta
from typing import Dict, List

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import print_info

# --- Entra sign-in surface (validated against the live Progress tenant) -----

USERNAME_SELECTOR = 'input[name="loginfmt"]'
PASSWORD_SELECTOR = 'input[name="passwd"]'
SUBMIT_SELECTOR = "#idSIButton9"
OTC_SELECTOR = 'input[name="otc"]'
OTC_SUBMIT_SELECTOR = "#idSubmit_SAOTCC_Continue"
OTC_REMEMBER_SELECTOR = "#idChkBx_SAOTCC_TileRememberMFA"
KMSI_SELECTOR = "#KmsiCheckboxField"
PUSH_NUMBER_SELECTOR = "#idRichContext_DisplaySign"
ANOTHER_WAY_SELECTOR = "#signInAnotherWay"
FACTOR_SELECTOR = "div[data-value]"
SMS_FACTOR_SELECTOR = 'div[data-value="OneWaySMS"]'
PHONE_CONFIRM_SELECTOR = "#idTxtBx_SAOTCS_PhoneNumber"
ERROR_SELECTOR = "#usernameError, #passwordError, #idSpan_SAOTCC_Error_OTC"

#: Microsoft Authenticator factors that only the enrolled device can answer.
DEVICE_BOUND_FACTORS = {"PhoneAppNotification", "PhoneAppOTP", "TwoWayVoiceMobile"}

# --- Step names -------------------------------------------------------------

STEP_PASSWORD = "password"
STEP_USERNAME = "username"
STEP_OPEN_FACTOR_PICKER = "open_factor_picker"
STEP_REQUEST_SMS = "request_sms"
STEP_ENTER_SMS_CODE = "enter_sms_code"
STEP_STAY_SIGNED_IN = "stay_signed_in"
STEP_WAIT = "wait"

# --- Timing -----------------------------------------------------------------

LOGIN_TIMEOUT_SECONDS = 420
SMS_TIMEOUT_SECONDS = 150
SMS_POLL_SECONDS = 5
PAGE_POLL_MS = 2500
#: Seconds a submitted step gets to move the sign-in flow forward. Entra keeps
#: rendering the same form while it processes a submission, so without this the
#: driver would resubmit the password on the next poll.
STEP_SETTLE_SECONDS = 45
#: Milliseconds between filling a field and clicking submit. Entra's sign-in
#: form ignores a click that arrives in the same tick as the input event: the
#: click is accepted but the form never posts. Measured against the live tenant:
#: with no delay the password step never advances; with this delay it advances
#: in under three seconds.
FIELD_SETTLE_MS = 1500
#: Clock skew tolerance between the Messages database and this process.
SMS_CLOCK_SKEW = timedelta(seconds=30)

_CODE_RE = re.compile(r"\b(\d{6,8})\b")


# ---------------------------------------------------------------------------
# Credential sourcing (LastPass)
# ---------------------------------------------------------------------------


def _run_cli(argv: List[str], what: str) -> str:
    """Run a managed CLI and return its stdout, or raise naming the failure."""
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise ClientError(
            f"{what} failed: `{' '.join(argv)}` exited {result.returncode}. "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def lastpass_value(entry: str, field: str) -> str:
    """Read one field of a LastPass entry through the managed ``lastpass`` CLI.

    Args:
        entry: LastPass entry id or unique name.
        field: ``username`` or ``password``.

    Raises:
        ClientError: When the CLI fails or the entry holds no value. The value
            itself is never printed or included in any message.
    """
    if field not in ("username", "password"):
        raise ClientError(f"Unsupported LastPass field {field!r}; use username or password.")
    value = _run_cli(
        ["lastpass", "items", field, entry],
        f"Reading the ServiceNow SSO {field} from LastPass entry {entry}",
    ).strip()
    if not value:
        raise ClientError(
            f"LastPass entry {entry} has an empty {field}. Store the Progress SSO "
            f"{field} in that entry, then re-run 'progress-servicenow auth login --force'."
        )
    return value


def login_email(username: str, domain: str) -> str:
    """Return the UPN Entra expects for a LastPass username.

    The Progress sign-in page states the required format explicitly
    (``username@progress.com``), and the vault stores the bare account name.
    """
    username = username.strip()
    if not username:
        raise ClientError("The LastPass username for the Progress SSO account is empty.")
    if "@" in username:
        return username
    return f"{username}@{domain}"


# ---------------------------------------------------------------------------
# MFA code sourcing (iMessage)
# ---------------------------------------------------------------------------


def _recent_messages(limit: int) -> List[Dict]:
    """Return recent Messages rows through the managed ``imessage`` CLI."""
    raw = _run_cli(
        ["imessage", "messages", "list", "--limit", str(limit)],
        "Reading the MFA text message from the imessage CLI",
    )
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ClientError(
            "The imessage CLI returned an unexpected payload shape: expected a list of "
            f"messages, got {type(rows).__name__}."
        )
    return rows


def find_sms_code(rows: List[Dict], requested_at: datetime) -> str:
    """Extract the Microsoft verification code from Messages rows.

    Only inbound messages that mention Microsoft and arrived at or after
    ``requested_at`` (minus the clock-skew tolerance) qualify, so an older code
    from a previous sign-in can never be replayed.

    Raises:
        ClientError: When no qualifying message carries a code.
    """
    cutoff = requested_at - SMS_CLOCK_SKEW
    newest_code = None
    newest_at = None
    for row in rows:
        if row.get("is_from_me"):
            continue
        text = row.get("text") or ""
        if "microsoft" not in text.lower():
            continue
        stamp = row.get("date")
        if not stamp:
            continue
        received_at = datetime.fromisoformat(stamp)
        if received_at < cutoff:
            continue
        match = _CODE_RE.search(text)
        if not match:
            continue
        if newest_at is None or received_at > newest_at:
            newest_at = received_at
            newest_code = match.group(1)
    if newest_code is None:
        raise ClientError(
            "No Microsoft verification text has arrived since the code was requested at "
            f"{requested_at.isoformat(timespec='seconds')}."
        )
    return newest_code


def wait_for_sms_code(requested_at: datetime) -> str:
    """Poll Messages until Microsoft's verification text arrives."""
    deadline = time.time() + SMS_TIMEOUT_SECONDS
    last_error = None
    while time.time() < deadline:
        try:
            return find_sms_code(_recent_messages(25), requested_at)
        except ClientError as exc:
            last_error = exc
        time.sleep(SMS_POLL_SECONDS)
    raise ClientError(
        f"The Microsoft MFA text did not arrive within {SMS_TIMEOUT_SECONDS} seconds. "
        f"{last_error} Confirm the phone is receiving SMS and that the Messages database "
        "is readable ('imessage auth status')."
    )


# ---------------------------------------------------------------------------
# Sign-in state machine
# ---------------------------------------------------------------------------


#: Validation notices Entra shows for a field it has just revealed and that has
#: not been filled yet. They are prompts, not credential rejections.
EMPTY_FIELD_PROMPTS = (
    "enter your password",
    "enter your username",
    "enter your email",
    "enter your account",
)


def is_empty_field_prompt(message: str) -> bool:
    """True when a sign-in notice is a "fill this in" prompt, not a rejection."""
    lowered = message.lower()
    return any(prompt in lowered for prompt in EMPTY_FIELD_PROMPTS)


def select_step(state: Dict[str, bool]) -> str:
    """Choose the next sign-in action from the observed page state.

    Pure decision function so the flow is testable without a browser.

    The username is always handled before the password. Entra's combined
    sign-in view renders both boxes at once but its client only consumes the
    username on that first submit; a password written into the box beforehand
    is discarded when the view switches to "Enter password". So each view gets
    exactly one field and one submit.
    """
    if state.get("otc_ready"):
        return STEP_ENTER_SMS_CODE
    if state.get("factor_picker_ready"):
        return STEP_REQUEST_SMS
    if state.get("push_challenge"):
        return STEP_OPEN_FACTOR_PICKER
    if state.get("kmsi_ready"):
        return STEP_STAY_SIGNED_IN
    if state.get("username_ready"):
        return STEP_USERNAME
    if state.get("password_ready"):
        return STEP_PASSWORD
    return STEP_WAIT


class ProgressSsoLogin:
    """Drive the Progress Entra sign-in flow on an already-open headless page."""

    def __init__(self, browser, page, *, lastpass_entry: str, email_domain: str):
        self._browser = browser
        self._page = page
        self._lastpass_entry = lastpass_entry
        self._email_domain = email_domain
        self._sms_requested_at = None

    # -- page inspection ---------------------------------------------------

    def _visible(self, selector: str) -> bool:
        locator = self._page.locator(selector)
        return bool(locator.count()) and locator.first.is_visible()

    def _enabled_and_visible(self, selector: str) -> bool:
        locator = self._page.locator(selector)
        if not locator.count() or not locator.first.is_visible():
            return False
        return bool(locator.first.is_enabled())

    def _field_is_empty(self, selector: str) -> bool:
        return not bool(
            self._page.locator(selector).first.evaluate("(el) => (el.value || '').trim()")
        )

    def _factor_values(self) -> List[str]:
        return self._page.evaluate(
            """() => Array.from(document.querySelectorAll('div[data-value]'))
                .filter(e => !!(e.offsetParent || e.getClientRects().length))
                .map(e => e.getAttribute('data-value'))"""
        )

    def observe(self) -> Dict[str, bool]:
        """Snapshot the sign-in controls the live page currently offers."""
        username_visible = self._enabled_and_visible(USERNAME_SELECTOR)
        return {
            "otc_ready": self._enabled_and_visible(OTC_SELECTOR),
            "factor_picker_ready": self._visible(FACTOR_SELECTOR),
            "push_challenge": self._visible(PUSH_NUMBER_SELECTOR),
            "kmsi_ready": self._visible(KMSI_SELECTOR),
            "password_ready": self._enabled_and_visible(PASSWORD_SELECTOR),
            "username_ready": username_visible and self._field_is_empty(USERNAME_SELECTOR),
        }

    def view_signature(self) -> tuple:
        """Identify the sign-in view: the pending step plus the visible heading.

        Entra switches views client-side without changing the URL, and two
        different views can want the same step (the combined form and the
        "Enter password" form both want a password). The heading is what
        actually distinguishes them, so progress is measured on both.
        """
        heading = self._page.evaluate(
            "() => { const h = document.querySelector('div[role=heading], h1');"
            " return h ? (h.textContent || '').trim() : ''; }"
        )
        return (select_step(self.observe()), heading)

    # -- guards ------------------------------------------------------------

    def _raise_on_rejected_credentials(self) -> None:
        locator = self._page.locator(ERROR_SELECTOR)
        if not locator.count() or not locator.first.is_visible():
            return
        message = " ".join(part.strip() for part in locator.all_text_contents() if part.strip())
        if is_empty_field_prompt(message):
            # "Please enter your password." is Entra asking for the field it
            # just revealed, not a rejection of anything we submitted.
            return
        raise ClientError(
            "Microsoft rejected the Progress SSO sign-in: "
            f"{message or 'the page displayed a sign-in error'}. "
            f"Update the password in LastPass entry {self._lastpass_entry}, then re-run "
            "'progress-servicenow auth login --force'."
        )

    def _raise_on_phone_confirmation(self) -> None:
        if not self._visible(PHONE_CONFIRM_SELECTOR):
            return
        raise ClientError(
            "Microsoft is asking for the last digits of the registered phone number before "
            "it will text a code. That confirmation is not automatable. Sign in once at "
            "https://progress1.service-now.com/esc in a browser, then re-run "
            "'progress-servicenow auth login --force'."
        )

    # -- steps -------------------------------------------------------------

    def _fill_username(self) -> None:
        username = lastpass_value(self._lastpass_entry, "username")
        self._page.fill(USERNAME_SELECTOR, login_email(username, self._email_domain))

    def _submit_username(self) -> None:
        self._fill_username()
        self._page.wait_for_timeout(FIELD_SETTLE_MS)
        self._page.locator(SUBMIT_SELECTOR).first.click()

    def _submit_password(self) -> None:
        password = lastpass_value(self._lastpass_entry, "password")
        try:
            self._page.fill(PASSWORD_SELECTOR, password)
        finally:
            password = None
        print_info("Submitting the Progress SSO password.")
        self._page.wait_for_timeout(FIELD_SETTLE_MS)
        self._page.locator(SUBMIT_SELECTOR).first.click()

    def _open_factor_picker(self) -> None:
        if not self._visible(ANOTHER_WAY_SELECTOR):
            number = self._page.locator(PUSH_NUMBER_SELECTOR).first.evaluate(
                "(el) => (el.textContent || '').trim()"
            )
            raise ClientError(
                "Microsoft is requiring Authenticator approval and offers no alternative "
                f"factor. Approve the sign-in request in Microsoft Authenticator (number "
                f"{number}), then re-run 'progress-servicenow auth login --force'."
            )
        print_info("Authenticator push requested; switching to a code-based factor.")
        self._page.locator(ANOTHER_WAY_SELECTOR).first.click()

    def _request_sms(self) -> None:
        factors = self._factor_values()
        if "OneWaySMS" not in factors:
            raise ClientError(
                "Microsoft offers no SMS factor for this account, so the MFA code cannot be "
                f"retrieved automatically. Available factors: {', '.join(factors) or 'none'}. "
                "Approve the sign-in in Microsoft Authenticator, then re-run "
                "'progress-servicenow auth login --force'."
            )
        self._sms_requested_at = datetime.now()
        print_info("Requesting the Microsoft MFA code by SMS.")
        self._page.locator(SMS_FACTOR_SELECTOR).first.click()

    def _enter_sms_code(self) -> None:
        if self._sms_requested_at is None:
            raise ClientError(
                "Microsoft is asking for a verification code that this session never "
                "requested, so no code can be matched to it. Re-run "
                "'progress-servicenow auth login --force'."
            )
        code = wait_for_sms_code(self._sms_requested_at)
        try:
            self._page.fill(OTC_SELECTOR, code)
        finally:
            code = None
        remember = self._page.locator(OTC_REMEMBER_SELECTOR)
        if remember.count() and remember.first.is_visible() and not remember.first.is_checked():
            remember.first.check()
        submit = OTC_SUBMIT_SELECTOR if self._visible(OTC_SUBMIT_SELECTOR) else SUBMIT_SELECTOR
        self._page.wait_for_timeout(FIELD_SETTLE_MS)
        self._page.locator(submit).first.click()

    def _stay_signed_in(self) -> None:
        self._page.locator(SUBMIT_SELECTOR).first.click()

    # -- driver ------------------------------------------------------------

    def _await_view_change(self, submitted: tuple) -> None:
        """Block until the submitted view is replaced by a different one.

        Entra keeps rendering the same form while it processes a submission, so
        polling the page alone would resubmit the password (or re-request the
        SMS) every few seconds. Each view is acted on exactly once.

        Raises:
            ClientError: When the submitted view never advances the flow.
        """
        deadline = time.time() + STEP_SETTLE_SECONDS
        while time.time() < deadline:
            self._page.wait_for_timeout(PAGE_POLL_MS)
            if self._browser._check_auth(self._page):
                return
            self._raise_on_rejected_credentials()
            self._raise_on_phone_confirmation()
            if self.view_signature() != submitted:
                return
        step, heading = submitted
        raise ClientError(
            f"The Progress SSO sign-in stalled: the {step!r} step on the {heading!r} view did "
            f"not advance the flow within {STEP_SETTLE_SECONDS} seconds. The browser is on "
            f"{self._page.url.split('?')[0]}."
        )

    def run(self) -> None:
        """Walk the sign-in flow until the ServiceNow session cookie is set."""
        handlers = {
            STEP_PASSWORD: self._submit_password,
            STEP_USERNAME: self._submit_username,
            STEP_OPEN_FACTOR_PICKER: self._open_factor_picker,
            STEP_REQUEST_SMS: self._request_sms,
            STEP_ENTER_SMS_CODE: self._enter_sms_code,
            STEP_STAY_SIGNED_IN: self._stay_signed_in,
        }
        deadline = time.time() + LOGIN_TIMEOUT_SECONDS
        while time.time() < deadline:
            if self._browser._check_auth(self._page):
                return
            self._raise_on_rejected_credentials()
            self._raise_on_phone_confirmation()
            signature = self.view_signature()
            step = signature[0]
            if step == STEP_WAIT:
                self._page.wait_for_timeout(PAGE_POLL_MS)
                continue
            handlers[step]()
            self._await_view_change(signature)
        raise ClientError(
            f"The Progress SSO sign-in did not complete within {LOGIN_TIMEOUT_SECONDS} "
            f"seconds. The browser was last on {self._page.url.split('?')[0]}."
        )


def run_sso_login(browser, page) -> None:
    """``AUTH_LOGIN_HANDLER`` for :class:`ProgressServiceNowBrowser`.

    ``cli_tools_shared`` owns the login lifecycle and hands this handler an
    already-open headless page on the login URL; the handler owns only the
    Progress Entra choreography.
    """
    ProgressSsoLogin(
        browser,
        page,
        lastpass_entry=browser.LASTPASS_ENTRY,
        email_domain=browser.LOGIN_EMAIL_DOMAIN,
    ).run()
