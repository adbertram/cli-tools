"""Retrieve Mercor's passwordless sign-in link out of Gmail.

Mercor has no password. Its login mails a Firebase Auth action link
(`https://mercor-prod-firebase.firebaseapp.com/__/auth/action?mode=signIn&oobCode=...`),
and only opening that link completes sign-in, so `mercor auth login` has to
read the email. It does so through the repo-owned `google` CLI, which already
owns Adam's Gmail OAuth session.

Validated live 2026-09-03: the sign-in mail is FROM "Mercor <auth@mercor.com>"
with subject "Sign in to Mercor". Command choice (mirrors the outlier CLI):
`google gmail search` lists message ids, and `google gmail get <id> --raw`
returns the Gmail API message resource whose `payload` carries the
base64url-encoded `text/html` part containing the anchor.

Freshness comes from the raw resource's `internalDate` (epoch milliseconds),
not from the RFC-2822 `date` header, so a link minted before the current login
attempt is never reused -- Mercor's links are single-use and expire.
"""

from __future__ import annotations

import base64
import binascii
import html
import json
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

from cli_tools_shared.auth import BrowserAutomationError

GOOGLE_CLI = "google"
# The sender Mercor uses for sign-in links (validated against live messages:
# FROM "Mercor <auth@mercor.com>", subject "Sign in to Mercor").
SENDER = "auth@mercor.com"
SEARCH_QUERY = f"from:{SENDER} newer_than:1d"
SEARCH_LIMIT = 5
VERIFY_LINK_RE = re.compile(
    r"https://mercor-prod-firebase\.firebaseapp\.com/__/auth/action\?[^\s\"'<>]+"
)

# Mercor's login page shows the "Check your inbox" card immediately; the mail
# usually lands in a few seconds. Polling longer than that gives the mail a
# generous delivery window without hanging a CLI run.
POLL_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 5
# Gmail's internalDate is server receive time; allow a small skew so a mail
# stamped a moment before the click is still accepted.
FRESHNESS_SKEW_MS = 60_000


def _run_google(args: List[str]) -> str:
    """Run the repo-owned `google` CLI and return its stdout."""
    binary = shutil.which(GOOGLE_CLI)
    if binary is None:
        raise BrowserAutomationError(
            "The 'google' CLI is required to read Mercor's sign-in email but is "
            "not on PATH. Install it from the cli-tools repo, then re-run "
            "'mercor auth login'."
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


def _search_message_ids() -> List[str]:
    """Message ids of recent Mercor sign-in mail, newest first."""
    raw = _run_google(
        ["gmail", "search", SEARCH_QUERY, "--limit", str(SEARCH_LIMIT)]
    ).strip()
    if not raw:
        return []
    messages = json.loads(raw)
    if not isinstance(messages, list):
        raise BrowserAutomationError(
            f"'{GOOGLE_CLI} gmail search' returned {type(messages).__name__}, "
            "expected a JSON array of messages."
        )
    return [message["id"] for message in messages if "id" in message]


def _message_resource(message_id: str) -> Dict[str, Any]:
    raw = _run_google(["gmail", "get", message_id, "--raw"]).strip()
    message = json.loads(raw)
    if not isinstance(message, dict):
        raise BrowserAutomationError(
            f"'{GOOGLE_CLI} gmail get {message_id} --raw' returned "
            f"{type(message).__name__}, expected a JSON object."
        )
    return message


def _decoded_parts(part: Dict[str, Any], collected: List[str]) -> None:
    """Collect every decoded body in a Gmail payload part tree."""
    data = (part.get("body") or {}).get("data")
    if data:
        try:
            collected.append(
                base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
            )
        except (binascii.Error, ValueError) as exc:
            raise BrowserAutomationError(
                f"Gmail message body was not valid base64url: {exc}"
            ) from exc
    for child in part.get("parts") or []:
        _decoded_parts(child, collected)


def _sign_in_link(message: Dict[str, Any]) -> Optional[str]:
    """The sign-in URL in a raw Gmail message resource, if it has one."""
    bodies: List[str] = []
    _decoded_parts(message.get("payload") or {}, bodies)
    for body in bodies:
        match = VERIFY_LINK_RE.search(body)
        if match:
            # The href lives in HTML, where `&` is written `&amp;`.
            return html.unescape(match.group(0))
    return None


def fetch_sign_in_link(requested_at_ms: int) -> str:
    """Poll Gmail for a Mercor sign-in link minted at or after ``requested_at_ms``.

    Args:
        requested_at_ms: Epoch milliseconds captured immediately before the
            login form was submitted.

    Returns:
        The absolute ``https://mercor-prod-firebase.firebaseapp.com/__/auth/action?...`` URL.

    Raises:
        BrowserAutomationError: When no fresh link arrives before the poll
            budget expires, or when the `google` CLI cannot be used.
    """
    cutoff_ms = requested_at_ms - FRESHNESS_SKEW_MS
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    newest_seen_ms = 0
    while True:
        for message_id in _search_message_ids():
            message = _message_resource(message_id)
            internal_date = int(message["internalDate"])
            newest_seen_ms = max(newest_seen_ms, internal_date)
            if internal_date < cutoff_ms:
                continue
            link = _sign_in_link(message)
            if link:
                return link
        if time.monotonic() >= deadline:
            break
        time.sleep(POLL_INTERVAL_SECONDS)
    raise BrowserAutomationError(
        "No Mercor sign-in email newer than the login request arrived within "
        f"{POLL_TIMEOUT_SECONDS}s. Newest message from {SENDER} was stamped "
        f"{newest_seen_ms or 'never'} (epoch ms); the request was made at "
        f"{requested_at_ms}. Check that the 'google' CLI is authenticated for "
        "the Mercor account's mailbox."
    )
