"""Retrieve Outlier's phone-verification code out of iMessage.

Outlier's Create Profile step texts a 6-digit code and renders the code-entry
screen as client-side state only: reloading
`https://app.outlier.ai/onboarding/complete-profile` puts the phone form back
(validated live 2026-09-02). Requesting the code and entering it therefore have
to happen inside one browser session, which means the CLI reads the SMS itself
rather than taking a `--code` option from a caller.

It does so through the repo-owned `imessage` CLI, which already owns access to
the local Messages database — the same shape `magic_link.py` uses for the
`google` CLI.

Message body, captured verbatim from Adam's device on 2026-09-02:

    Your Outlier verification code is: 488230. Don't share this code with
    anyone; our employees will never ask for the code.

`imessage messages list --properties "id,text,date"` returns `date` as a naive
local-time ISO-8601 string, so freshness is compared in local time against the
moment the code was requested. A code minted before that moment is never
reused.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List

from cli_tools_shared.exceptions import ClientError

IMESSAGE_CLI = "imessage"
LIST_LIMIT = 20
CODE_RE = re.compile(r"Outlier verification code is:\s*(\d{6})")

# Outlier's own resend cooldown is 30s (frontend constant `I8` in chunk
# `63627`), so a two-minute budget covers ordinary SMS delivery without
# hanging the run.
POLL_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 5
# Allow for clock skew between the browser's request timestamp and the
# Messages database's receive timestamp.
FRESHNESS_SKEW_MS = 30_000


def _run_imessage(args: List[str]) -> str:
    binary = shutil.which(IMESSAGE_CLI)
    if binary is None:
        raise ClientError(
            "The 'imessage' CLI is required to read Outlier's verification code "
            "but is not on PATH. Install it from the cli-tools repo, then re-run "
            "this command."
        )
    result = subprocess.run([binary, *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ClientError(
            f"'{IMESSAGE_CLI} {' '.join(args)}' failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def _recent_messages() -> List[Dict[str, Any]]:
    raw = _run_imessage(
        ["messages", "list", "--limit", str(LIST_LIMIT), "--properties", "id,text,date"]
    ).strip()
    if not raw:
        return []
    messages = json.loads(raw)
    if not isinstance(messages, list):
        raise ClientError(
            f"'{IMESSAGE_CLI} messages list' returned {type(messages).__name__}, "
            "expected a JSON array of messages."
        )
    return messages


def _received_at_ms(message: Dict[str, Any]) -> int:
    """Epoch milliseconds for a message's naive local-time `date` field."""
    return int(datetime.fromisoformat(message["date"]).timestamp() * 1000)


def fetch_verification_code(requested_at_ms: int) -> str:
    """Poll iMessage for an Outlier code received at or after ``requested_at_ms``.

    Args:
        requested_at_ms: Epoch milliseconds captured immediately before the
            Create Profile form was submitted.

    Returns:
        The 6-digit verification code.

    Raises:
        ClientError: When no fresh code arrives before the poll budget expires,
            or when the `imessage` CLI cannot be used.
    """
    cutoff_ms = requested_at_ms - FRESHNESS_SKEW_MS
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    newest_seen_ms = 0
    while True:
        for message in _recent_messages():
            text = message.get("text") or ""
            match = CODE_RE.search(text)
            if not match:
                continue
            received_ms = _received_at_ms(message)
            newest_seen_ms = max(newest_seen_ms, received_ms)
            if received_ms >= cutoff_ms:
                return match.group(1)
        if time.monotonic() >= deadline:
            break
        time.sleep(POLL_INTERVAL_SECONDS)
    raise ClientError(
        "No Outlier verification SMS newer than the request arrived within "
        f"{POLL_TIMEOUT_SECONDS}s. Newest Outlier code message was stamped "
        f"{newest_seen_ms or 'never'} (epoch ms); the code was requested at "
        f"{requested_at_ms}. Check that the 'imessage' CLI can read the Messages "
        "database."
    )
