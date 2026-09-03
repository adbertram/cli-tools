"""Tests for reading Outlier's phone-verification code out of iMessage.

Every row below is the verbatim shape `imessage messages list --limit 25
-p "id,text,date,sender"` returned on Adam's device on 2026-09-02, including
the two properties that break naive polling:

  * `sender` is null on every row, so matching has to be done on the message
    text, never on a contact or short code.
  * `date` is a naive LOCAL-time ISO-8601 string, not epoch milliseconds and
    not UTC — comparing it against a UTC instant rejects every message.

Outlier also re-sends the SAME code within its resend window (488230 arrived
three times, at 19:46:02, 19:47:26 and 19:48:56), so an unchanged code is not
evidence of a stale one; only the receive time decides freshness.
"""

from datetime import datetime

import pytest

from outlier_cli import sms_code
from cli_tools_shared.exceptions import ClientError

LIVE_ROWS = [
    {
        "id": "60721",
        "text": (
            "Your Outlier verification code is: 488230. Don't share this code "
            "with anyone; our employees will never ask for the code."
        ),
        "date": "2026-09-02T19:48:56.893316",
        "sender": None,
    },
    {
        "id": "60720",
        "text": (
            "Your Outlier verification code is: 488230. Don't share this code "
            "with anyone; our employees will never ask for the code."
        ),
        "date": "2026-09-02T19:47:26.101000",
        "sender": None,
    },
    {
        "id": "60719",
        "text": (
            "Your Outlier verification code is: 488230. Don't share this code "
            "with anyone; our employees will never ask for the code."
        ),
        "date": "2026-09-02T19:46:02.441622",
        "sender": None,
    },
    {
        "id": "60718",
        "text": "G-671484 is your Google verification code. Don't share your code with anyone.",
        "date": "2026-09-02T18:36:41.889172",
        "sender": None,
    },
    {
        "id": "60717",
        "text": "Confirm",
        "date": "2026-09-02T17:56:08.469200",
        "sender": None,
    },
]


def _epoch_ms(local_iso: str) -> int:
    return int(datetime.fromisoformat(local_iso).timestamp() * 1000)


def test_extracts_the_code_from_the_live_message_text():
    match = sms_code.CODE_RE.search(LIVE_ROWS[0]["text"])
    assert match is not None
    assert match.group(1) == "488230"


def test_ignores_another_service_six_digit_code():
    assert sms_code.CODE_RE.search(LIVE_ROWS[3]["text"]) is None


def test_received_at_ms_reads_the_naive_local_timestamp():
    row = LIVE_ROWS[0]
    assert sms_code._received_at_ms(row) == _epoch_ms(row["date"])


def test_returns_the_newest_code_when_it_is_fresh(monkeypatch):
    monkeypatch.setattr(sms_code, "_recent_messages", lambda: LIVE_ROWS)
    requested_at_ms = _epoch_ms("2026-09-02T19:48:50")
    assert sms_code.fetch_verification_code(requested_at_ms) == "488230"


def test_accepts_a_repeat_of_the_same_code(monkeypatch):
    """A resend carries the same digits; only the receive time decides."""
    monkeypatch.setattr(sms_code, "_recent_messages", lambda: LIVE_ROWS)
    # Requested just before the 19:47:26 resend: the 19:48:56 row is newer
    # still, and identical, and must be accepted rather than judged stale.
    requested_at_ms = _epoch_ms("2026-09-02T19:47:20")
    assert sms_code.fetch_verification_code(requested_at_ms) == "488230"


def test_rejects_a_code_that_predates_the_request(monkeypatch):
    monkeypatch.setattr(sms_code, "_recent_messages", lambda: LIVE_ROWS)
    monkeypatch.setattr(sms_code, "POLL_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(sms_code, "POLL_INTERVAL_SECONDS", 0)
    requested_at_ms = _epoch_ms("2026-09-02T20:30:00")
    with pytest.raises(ClientError) as excinfo:
        sms_code.fetch_verification_code(requested_at_ms)
    assert "No Outlier verification SMS newer than the request" in str(excinfo.value)


def test_rejects_a_non_list_response(monkeypatch):
    monkeypatch.setattr(
        sms_code, "_run_imessage", lambda args: '{"error": "nope"}'
    )
    with pytest.raises(ClientError) as excinfo:
        sms_code._recent_messages()
    assert "expected a JSON array" in str(excinfo.value)
