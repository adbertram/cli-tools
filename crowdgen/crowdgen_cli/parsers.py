"""Parsers for CrowdGen (Appen) worker data.

Evidence state (2026-09-03): CrowdGen's worker surface ("My Projects", ADAP,
projects/available) is only reachable behind an authenticated contributor
session. No authenticated capture exists yet — registration is refused by
Kasada for automation-created browser sessions on this network (every
/api/v1 POST/GET returns 429 with a KPSDK challenge page even from headed real
Chrome over CDP with freshly-minted x-kpsdk-ct/x-kpsdk-cd tokens), and the
remaining sign-up steps (mobile -> address/agreements -> payout -> government
ID) are human gates. The deployed frontend bundle (main.b5c37aa5.js) names the
endpoints (`projects/available`, `projects/active`, `projects/match`,
`adap/contributorProjects` under https://api.crowdgen.com/api/v1/), but their
response record shapes are unobserved.

Per the evidence-backed-only rule, this module never guesses a payload key.
`task_rows` accepts only provably-empty responses (the expected pre-shortlist
dashboard) and raises for anything else, telling the caller to capture a live
fixture before any record mapping is written.
"""

from __future__ import annotations

from typing import Any

from cli_tools_shared.exceptions import ClientError

EMPTY_SCALARS = (None, "", False, 0)


def _empty_value(value: Any) -> bool:
    """True for values that can only mean "no data here"."""
    if value is None:
        return True
    if isinstance(value, list):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0
    if isinstance(value, bool):
        return value is False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        return value.strip() == ""
    return False


def is_empty_payload(body: Any) -> bool:
    """Is this API response provably empty (a pre-shortlist dashboard)?

    A JSON array that is empty, or an object whose every value is empty, is a
    dashboard with no projects. Anything else is a payload whose shape has not
    been observed and must not be auto-mapped.
    """
    if body is None:
        return True
    if isinstance(body, list):
        return len(body) == 0
    if isinstance(body, dict):
        return all(_empty_value(value) for value in body.values())
    return False


def unverified_payload_error(endpoint: str, body: Any) -> ClientError:
    """Error for a non-empty API payload whose shape is not yet captured."""
    preview = repr(body)[:200]
    return ClientError(
        "CrowdGen GET " + endpoint + " returned a non-empty response whose "
        "shape has not been validated against a live authenticated capture. "
        "Payload preview: " + preview + " — run 'crowdgen tasks list' with an "
        "authenticated profile, save the response under "
        "tests/fixtures/, then finalize task_rows() in parsers.py."
    )


def task_rows(endpoint: str, body: Any) -> list:
    """Reduce a CrowdGen projects response to task rows.

    Only provably-empty responses yield [] today; a non-empty response raises
    `unverified_payload_error` instead of guessing record keys.
    """
    if is_empty_payload(body):
        return []
    raise unverified_payload_error(endpoint, body)
