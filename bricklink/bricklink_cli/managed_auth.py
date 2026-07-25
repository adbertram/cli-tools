"""Managed credential and email-code providers for BrickLink browser auth."""

import json
import re
import subprocess
import time

from cli_tools_shared.auth import BrowserAutomationError


LASTPASS_ITEM = "lego.com"
GOOGLE_PROFILE = "adbertram"
CONFIRMATION_QUERY = (
    'from:blservice@bricklink.com subject:"Your BrickLink confirmation code"'
)
LEGO_TWO_FACTOR_QUERY = (
    'from:account@mail.identity.lego.com subject:"Your LEGO"'
)
CONFIRMATION_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _run(command: list[str]) -> str:
    """Run an approved credential command without exposing captured output."""
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BrowserAutomationError(
            f"Managed credential command failed: {command[0]} {command[1]}."
        ) from exc
    return result.stdout


def get_lastpass_credential(field: str) -> str:
    """Read one BrickLink login field from the managed LastPass CLI."""
    if field not in {"username", "password"}:
        raise ValueError(f"Unsupported LastPass credential field: {field}")
    value = _run(["lastpass", "items", field, LASTPASS_ITEM]).rstrip("\n")
    if not value:
        raise BrowserAutomationError(
            f"Managed LastPass returned an empty BrickLink {field}."
        )
    return value


class GmailConfirmationCodeProvider:
    """Poll the managed Gmail account for a fresh BrickLink confirmation code."""

    def __init__(
        self,
        *,
        profile: str = GOOGLE_PROFILE,
        timeout_seconds: int = 90,
        poll_seconds: int = 3,
    ):
        self.profile = profile
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def get_code(self, *, requested_after: int) -> str:
        deadline = time.time() + self.timeout_seconds
        query = f"{CONFIRMATION_QUERY} after:{int(requested_after)}"
        while time.time() < deadline:
            search_output = _run(
                [
                    "google",
                    "gmail",
                    "search",
                    query,
                    "--limit",
                    "1",
                    "--properties",
                    "id,from,subject,date",
                    "--profile",
                    self.profile,
                ]
            )
            try:
                matches = json.loads(search_output)
            except json.JSONDecodeError as exc:
                raise BrowserAutomationError(
                    "Google Gmail search returned malformed JSON."
                ) from exc
            if not isinstance(matches, list):
                raise BrowserAutomationError(
                    "Google Gmail search did not return a JSON array."
                )
            if matches:
                message_id = matches[0].get("id")
                if not message_id:
                    raise BrowserAutomationError(
                        "Google Gmail search result did not include a message id."
                    )
                message_output = _run(
                    [
                        "google",
                        "gmail",
                        "get",
                        message_id,
                        "--include-body",
                        "--profile",
                        self.profile,
                    ]
                )
                try:
                    message = json.loads(message_output)
                except json.JSONDecodeError as exc:
                    raise BrowserAutomationError(
                        "Google Gmail get returned malformed JSON."
                    ) from exc
                body = message.get("body", "") if isinstance(message, dict) else ""
                code_match = CONFIRMATION_CODE_PATTERN.search(body)
                if not code_match:
                    raise BrowserAutomationError(
                        "Fresh BrickLink confirmation email did not contain a six-digit code."
                    )
                return code_match.group(1)
            time.sleep(self.poll_seconds)
        raise BrowserAutomationError(
            "No fresh BrickLink confirmation email arrived before the timeout."
        )


def get_bricklink_confirmation_code(*, requested_after: int) -> str:
    return GmailConfirmationCodeProvider().get_code(requested_after=requested_after)


class GmailLegoTwoFactorCodeProvider:
    """Poll the managed Gmail account for a fresh LEGO identity code."""

    def __init__(
        self,
        *,
        profile: str = GOOGLE_PROFILE,
        timeout_seconds: int = 90,
        poll_seconds: int = 3,
    ):
        self.profile = profile
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def get_code(self, *, requested_after: int) -> str:
        deadline = time.time() + self.timeout_seconds
        query = f"{LEGO_TWO_FACTOR_QUERY} after:{int(requested_after)}"
        while time.time() < deadline:
            search_output = _run(
                [
                    "google",
                    "gmail",
                    "search",
                    query,
                    "--limit",
                    "1",
                    "--properties",
                    "id,from,subject,date",
                    "--profile",
                    self.profile,
                ]
            )
            try:
                matches = json.loads(search_output)
            except json.JSONDecodeError as exc:
                raise BrowserAutomationError(
                    "Google Gmail search returned malformed JSON."
                ) from exc
            if not isinstance(matches, list):
                raise BrowserAutomationError(
                    "Google Gmail search did not return a JSON array."
                )
            if matches:
                subject = matches[0].get("subject", "")
                code_match = CONFIRMATION_CODE_PATTERN.search(subject)
                if not code_match:
                    raise BrowserAutomationError(
                        "Fresh LEGO identity email did not contain a six-digit code."
                    )
                return code_match.group(1)
            time.sleep(self.poll_seconds)
        raise BrowserAutomationError(
            "No fresh LEGO identity email arrived before the timeout."
        )


def get_lego_two_factor_code(*, requested_after: int) -> str:
    return GmailLegoTwoFactorCodeProvider().get_code(
        requested_after=requested_after
    )
