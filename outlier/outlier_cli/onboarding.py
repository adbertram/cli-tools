"""Browser-driven onboarding steps for Outlier.

Outlier has no JSON API for advancing onboarding. The only non-UI endpoints
the deployed frontend exposes for these steps are its own QA bypass routes
(`/internal/experts/qualification/onboarding/bypass-*`,
`/internal/worker/verifications/complete-phone-verification`), which mark a
step complete without performing it. This CLI never calls those: it drives the
real form so the site's own validation, rate limiting and fraud-session
plumbing (`POST /internal/fraud/log_session`) run exactly as they do for a
person.

Every selector and every marker string below was captured from the live
authenticated app on 2026-09-02:

  * `https://app.outlier.ai/onboarding/complete-profile` renders the "Create
    Profile" card with `#complete-profile-first-name`,
    `#complete-profile-last-name` and `#complete-profile-phone`
    (`<input type="number" inputmode="tel" placeholder="(000) 000-0000">`),
    plus a submit `<button>` labelled "Verify phone number" that stays
    `disabled` until the phone field validates.
  * The screens that follow, and every error string this module matches, are
    verbatim from the app's own i18n table in chunk
    `87936-b412118544497d44.js` (`onboarding-personal-info-form`,
    `onboarding-phone-verification-form`,
    `onboarding-phone-verification-channel-dialog`).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from cli_tools_shared.exceptions import ClientError

COMPLETE_PROFILE_PATH = "/onboarding/complete-profile"
SKILL_SELECTION_PATH = "/onboarding/skill-selection"

FIRST_NAME_SELECTOR = "#complete-profile-first-name"
LAST_NAME_SELECTOR = "#complete-profile-last-name"
PHONE_SELECTOR = "#complete-profile-phone"

SUBMIT_BUTTON_TEXT = "Verify phone number"
CHANNEL_DIALOG_MARKER = "How would you like to receive your code?"
CHANNEL_SEND_BUTTON_TEXT = "Send Code"
CODE_SCREEN_MARKER = "Enter code"
# The code-entry screen renders six single-digit boxes
# (`<input type="number" maxlength="1">`) and no submit control: filling
# the sixth digit submits. Captured live 2026-09-02.
CODE_DIGIT_SELECTOR = 'input[type="number"][maxlength="1"]'
CODE_LENGTH = 6

CHANNEL_LABELS = {"sms": "SMS", "whatsapp": "WhatsApp"}

# --- Import skills (skill-selection) -------------------------------------
#
# Captured live 2026-09-03. The page carries no `<input>` at all until the
# Resume card's "File Upload" button is clicked; that mounts a drag-and-drop
# dialog holding two file inputs, neither with an id, name or class:
#
#   accept="application/pdf,.pdf,application/vnd.openxmlformats-officedocument
#           .wordprocessingml.document,.docx"   (visible)
#   accept=".pdf,.docx"                          (hidden)
#
# Only the first carries the long MIME form, so `accept*="application/pdf"`
# names it unambiguously.
RESUME_UPLOAD_BUTTON_TEXT = "File Upload"
RESUME_FILE_INPUT_SELECTOR = 'input[type="file"][accept*="application/pdf"]'
RESUME_SUFFIXES = (".pdf", ".docx")
# The app's own progress copy for the upload, verbatim from chunk
# `87936-b412118544497d44.js` (`onboarding-skills-import`).
RESUME_PROGRESS_MARKERS = (
    "Please wait, uploading resume...",
    "uploading...",
    "parsing...",
    "processing...",
)
RESUME_UPLOAD_START_TIMEOUT_SECONDS = 30
RESUME_UPLOAD_FINISH_TIMEOUT_SECONDS = 180

# Verbatim from the app's i18n table; each is a terminal condition, not a
# transient render state.
PHONE_ERROR_MARKERS = (
    "You have entered an invalid phone number for your country.",
    "We can't send a verification code to this phone number.",
    "This phone number is already associated with an Outlier account.",
    "You have exceeded the daily limit on phone verification attempts.",
    "You have exceeded the limit on phone verification attempts.",
    "Something went wrong submitting those details.",
    "We couldn't send a verification code. Please try again.",
    "We couldn’t send a verification code. Please try again.",
    "We couldn't send a text message. Please try again later.",
    "We couldn’t send a text message. Please try again later.",
)
CODE_ERROR_MARKERS = (
    "That code didn't look right.",
    "That code didn’t look right.",
    "Maximum number of attempts exceeded.",
)

STEP_TIMEOUT_SECONDS = 45
POLL_INTERVAL_MS = 1000


def _body_text(page) -> str:
    return page.evaluate("() => document.body.innerText || ''")


def _first_visible(page, selector: str, *, text: Optional[str] = None):
    """First visible element matching ``selector`` (and containing ``text``).

    Outlier renders each onboarding card twice — a zero-size layout copy and
    the real one — so index-based selection targets the hidden element.
    """
    for candidate in page.locator(selector).all():
        if not candidate.is_visible():
            continue
        if text is not None and text not in (candidate.inner_text() or ""):
            continue
        return candidate
    return None


def _raise_for_markers(text: str, markers) -> None:
    for marker in markers:
        if marker in text:
            raise ClientError(f"Outlier rejected the request: {marker}")


def _wait_for(page, predicate, *, timeout: int, description: str) -> str:
    """Poll the rendered page until ``predicate(text)`` holds; return the text."""
    deadline = time.monotonic() + timeout
    while True:
        page.wait_for_timeout(POLL_INTERVAL_MS)
        text = _body_text(page)
        _raise_for_markers(text, PHONE_ERROR_MARKERS)
        _raise_for_markers(text, CODE_ERROR_MARKERS)
        if predicate(text):
            return text
        if time.monotonic() >= deadline:
            raise ClientError(
                f"Outlier did not show {description} within {timeout}s. "
                f"The page is at {page.evaluate('() => location.href')} and reads: "
                f"{text.strip()[:600]!r}"
            )


def _require(page, selector: str, *, what: str, text: Optional[str] = None):
    element = _first_visible(page, selector, text=text)
    if element is None:
        raise ClientError(
            f"Outlier's Create Profile screen did not render {what} "
            f"({selector!r}{'' if text is None else f' containing {text!r}'}). "
            "The screen layout changed; re-capture it before changing this module."
        )
    return element


def _complete_profile_url(config) -> str:
    return f"{config.base_url.rstrip('/')}{COMPLETE_PROFILE_PATH}"


def _skill_selection_url(config) -> str:
    return f"{config.base_url.rstrip('/')}{SKILL_SELECTION_PATH}"


def _has_progress_marker(text: str) -> bool:
    return any(marker in text for marker in RESUME_PROGRESS_MARKERS)


def _code_boxes(page):
    """The six visible single-digit inputs of the code-entry screen."""
    boxes = [box for box in page.locator(CODE_DIGIT_SELECTOR).all() if box.is_visible()]
    if len(boxes) != CODE_LENGTH:
        raise ClientError(
            f"Outlier's code-entry screen rendered {len(boxes)} visible digit "
            f"boxes ({CODE_DIGIT_SELECTOR!r}), expected {CODE_LENGTH}. The screen "
            "layout changed; re-capture it before changing this module."
        )
    return boxes


def _enter_code(page, code: str) -> None:
    """Type the code into the six digit boxes, one character per box.

    Each box is focused explicitly and then written with a CDP
    ``Input.insertText``. Both halves matter, and both were measured against
    the live Create Profile screen on 2026-09-02:

      * ``element.click()`` fires a click event without moving focus in
        Chrome, so clicking a box and then typing sends the characters to
        whatever already had focus — every box stays empty.
      * ``locator.press(digit)`` focuses correctly but writes the character
        TWICE: ``Input.dispatchKeyEvent`` carries ``text`` on the ``keyDown``
        and then sends a second ``char`` event with the same text. Typing
        "488230" that way left the boxes holding "44", "88", "88", "22", "33".

    Focusing via ``el.focus()`` and inserting the character produced exactly
    one character per box in the same input stack. The digits are read back
    afterwards so any future component change fails loudly here instead of
    timing out further down.
    """
    if len(code) != CODE_LENGTH or not code.isdigit():
        raise ClientError(
            f"Expected a {CODE_LENGTH}-digit verification code, got {code!r}."
        )
    for index, digit in enumerate(code):
        box = _code_boxes(page)[index]
        box.evaluate("el => el.focus()")
        page.type_text(digit)
        page.wait_for_timeout(250)
    entered = "".join((box.input_value() or "") for box in _code_boxes(page))
    if entered != code:
        raise ClientError(
            f"Outlier's code boxes hold {entered!r} after typing the "
            f"{CODE_LENGTH}-digit code. The code-entry component changed; "
            "re-capture it before changing this module."
        )


def verify_phone(
    config,
    phone: str,
    *,
    channel: str = "sms",
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Complete Create Profile end to end: submit, read the SMS, enter the code.

    Outlier keeps the code-entry screen in client-side state only, so both
    halves have to happen in one browser session; the code is read from the
    device through the `imessage` CLI (see ``sms_code``).
    """
    if channel not in CHANNEL_LABELS:
        raise ClientError(
            f"Unknown channel {channel!r}. Outlier offers: "
            f"{', '.join(sorted(CHANNEL_LABELS))}."
        )

    from .sms_code import fetch_verification_code

    browser = config.get_browser()
    try:
        page = browser.get_page(_complete_profile_url(config))
        page.wait_for_timeout(POLL_INTERVAL_MS * 5)

        if first_name is not None:
            _require(page, FIRST_NAME_SELECTOR, what="the first-name field").fill(first_name)
        if last_name is not None:
            _require(page, LAST_NAME_SELECTOR, what="the last-name field").fill(last_name)

        phone_field = _require(page, PHONE_SELECTOR, what="the phone-number field")
        phone_field.fill(phone)
        page.wait_for_timeout(POLL_INTERVAL_MS)

        submit = _require(
            page, "button", what=f"the {SUBMIT_BUTTON_TEXT!r} button", text=SUBMIT_BUTTON_TEXT
        )
        if not submit.is_enabled():
            raise ClientError(
                f"Outlier kept the {SUBMIT_BUTTON_TEXT!r} button disabled after "
                f"entering {phone!r}. The site rejects that number as entered for "
                "the account's country."
            )

        requested_at_ms = int(time.time() * 1000)
        submit.click()

        text = _wait_for(
            page,
            lambda t: CHANNEL_DIALOG_MARKER in t or CODE_SCREEN_MARKER in t,
            timeout=STEP_TIMEOUT_SECONDS,
            description="the channel picker or the code-entry screen",
        )

        channel_selected = None
        if CHANNEL_DIALOG_MARKER in text:
            label = CHANNEL_LABELS[channel]
            _require(
                page,
                "button, [role='radio'], label",
                what=f"the {label!r} channel option",
                text=label,
            ).click()
            page.wait_for_timeout(POLL_INTERVAL_MS)
            requested_at_ms = int(time.time() * 1000)
            _require(
                page,
                "button",
                what=f"the {CHANNEL_SEND_BUTTON_TEXT!r} button",
                text=CHANNEL_SEND_BUTTON_TEXT,
            ).click()
            channel_selected = channel
            _wait_for(
                page,
                lambda t: CODE_SCREEN_MARKER in t,
                timeout=STEP_TIMEOUT_SECONDS,
                description="the code-entry screen",
            )

        code = fetch_verification_code(requested_at_ms)
        _enter_code(page, code)

        _wait_for(
            page,
            lambda t: CODE_SCREEN_MARKER not in t,
            timeout=STEP_TIMEOUT_SECONDS,
            description="the screen that follows a verified phone number",
        )

        return {
            "phone_number": phone,
            "channel": channel_selected,
            "requested_at_ms": requested_at_ms,
            "verified": True,
            "url": page.evaluate("() => location.href"),
        }
    finally:
        browser.close()


def upload_resume(config, file_path: str) -> Dict[str, Any]:
    """Attach a resume to the Import skills step.

    The Resume card mounts its file input only after its "File Upload" button
    is clicked, so the click has to happen before the input can be targeted.
    Progress is judged by the app's own copy ("uploading...", "parsing...",
    "processing..."): the marker must appear, proving Outlier accepted the
    file, and then clear, proving the parse finished.
    """
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise ClientError(f"Resume file not found: {path}")
    if path.suffix.lower() not in RESUME_SUFFIXES:
        raise ClientError(
            f"Outlier's resume upload accepts {', '.join(RESUME_SUFFIXES)}; "
            f"got {path.suffix or 'no extension'} ({path.name})."
        )

    browser = config.get_browser()
    try:
        page = browser.get_page(_skill_selection_url(config))
        page.wait_for_timeout(POLL_INTERVAL_MS * 6)

        _require(
            page,
            "button",
            what=f"the Resume card's {RESUME_UPLOAD_BUTTON_TEXT!r} button",
            text=RESUME_UPLOAD_BUTTON_TEXT,
        ).click()

        _wait_for(
            page,
            lambda _t: page.evaluate(
                "(sel) => document.querySelector(sel) !== null",
                RESUME_FILE_INPUT_SELECTOR,
            ),
            timeout=STEP_TIMEOUT_SECONDS,
            description="the resume file input",
        )
        page.set_input_files(RESUME_FILE_INPUT_SELECTOR, str(path))

        _wait_for(
            page,
            _has_progress_marker,
            timeout=RESUME_UPLOAD_START_TIMEOUT_SECONDS,
            description="the resume upload to start",
        )
        _wait_for(
            page,
            lambda t: not _has_progress_marker(t),
            timeout=RESUME_UPLOAD_FINISH_TIMEOUT_SECONDS,
            description="the resume upload to finish",
        )

        text = _body_text(page)
        if path.stem not in text:
            raise ClientError(
                f"Outlier finished processing but the Import skills screen does "
                f"not name {path.stem!r}. The screen reads: {text.strip()[:800]!r}"
            )
        return {
            "resume_file": str(path),
            "uploaded": True,
            "url": page.evaluate("() => location.href"),
        }
    finally:
        browser.close()
