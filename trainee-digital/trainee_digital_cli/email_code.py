"""Retrieve trainee.digital's emailed login code out of Gmail.

trainee.digital signs in through Clerk with a 6-digit email verification
code (no password is stored for this account). ``trainee-digital auth login``
therefore has to read the code out of the mailbox. It does so through the
repo-owned `google` CLI, which already owns Adam's Gmail OAuth session.

Validated live 2026-09-03: the sign-in mail is FROM notifications@trainee.digital
with subject "<6 digits> is your verification code". Command choice (mirrors
the mercor/outlier CLIs): `google gmail search` lists message ids, and
`google gmail get <id> --raw` returns the Gmail API message resource whose
top-level ``internalDate`` (epoch milliseconds) is the freshness anchor.

Freshness comes from ``internalDate``, not from the RFC-2822 ``date`` header,
so a code minted before the current login attempt is never reused.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

from cli_tools_shared.auth import BrowserAutomationError

GOOGLE_CLI = "google"
# The sender used for login codes (validated against live messages:
# FROM notifications@trainee.digital, subject "696391 is your verification code").
SENDER = "notifications@trainee.digital"
SEARCH_QUERY = f"from:{SENDER} newer_than:1d"
SEARCH_LIMIT = 5
CODE_SUBJECT_RE = re.compile(r"^(\d{6}) is your verification code$")

POLL_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 4
# Gmail's internalDate is server receive time; allow a small skew so a mail
# stamped a moment before the code request is still accepted.
FRESHNESS_SKEW_MS = 60_000


def _run_google(args: List[str]) -> str:
    """Run the repo-owned `google` CLI and return its stdout."""
    binary = shutil.which(GOOGLE_CLI)
    if binary is None:
        raise BrowserAutomationError(
            "The 'google' CLI is required to read trainee.digital's login code "
            "from Gmail but is not on PATH. Install it from the cli-tools "
            "repo, then re-run 'trainee-digital auth login'."
        )
    result = subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BrowserAutomationError(
            f"'{GOOGLE_CLI} {' '.join(args)}' failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def _search_messages() -> List[Dict[str, Any]]:
    """Recent trainee.digital login-code messages, newest first.

    Each item carries ``id`` and ``subject`` (the code is in the subject, so
    non-code mail is skipped without a body fetch).
    """
    raw = _run_google(
        ["gmail", "search", SEARCH_QUERY, "--limit", str(SEARCH_LIMIT),
         "--properties", "id,subject"]
    ).strip()
    if not raw:
        return []
    messages = json.loads(raw)
    if not isinstance(messages, list):
        raise BrowserAutomationError(
            f"'{GOOGLE_CLI} gmail search' returned {type(messages).__name__}, "
            "expected a JSON array of messages."
        )
    return [message for message in messages if isinstance(message, dict)]


def _internal_date_ms(message_id: str) -> int:
    raw = _run_google(["gmail", "get", message_id, "--raw"]).strip()
    message = json.loads(raw)
    if not isinstance(message, dict):
        raise BrowserAutomationError(
            f"'{GOOGLE_CLI} gmail get {message_id} --raw' returned "
            f"{type(message).__name__}, expected a JSON object."
        )
    value = message.get("internalDate")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BrowserAutomationError(
            f"Gmail message {message_id} has no usable internalDate ({value!r})."
        ) from exc


def verification_code_from_subject(subject: str) -> Optional[str]:
    """The 6-digit code in a trainee.digital login-code subject line.

    Live emails use exactly "<6 digits> is your verification code". Returns
    ``None`` for any other subject so non-code mail is skipped while polling.
    """
    if not isinstance(subject, str):
        return None
    match = CODE_SUBJECT_RE.match(subject.strip())
    return match.group(1) if match else None


def fetch_verification_code(requested_at_ms: int) -> str:
    """Poll Gmail for a trainee.digital login code minted after ``requested_at_ms``.

    Args:
        requested_at_ms: Epoch milliseconds captured immediately before the
            code request was submitted (see browser.py).

    Returns:
        The 6-digit verification code as a string.

    Raises:
        BrowserAutomationError: When the code mail does not arrive in time or
            the `google` CLI cannot be run.
    """
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while True:
        for message in _search_messages():
            code = verification_code_from_subject(message.get("subject"))
            if code is None:
                continue
            try:
                internal_date = _internal_date_ms(message["id"])
            except KeyError:
                continue
            if internal_date < requested_at_ms - FRESHNESS_SKEW_MS:
                continue
            return code
        if time.monotonic() >= deadline:
            raise BrowserAutomationError(
                f"trainee.digital's login code did not arrive at the inbox "
                f"within {POLL_TIMEOUT_SECONDS}s of requesting it. The mail "
                "comes from notifications@trainee.digital with subject '<6 "
                "digits> is your verification code'. Re-run 'trainee-digital "
                "auth login'."
            )
        time.sleep(POLL_INTERVAL_SECONDS)
