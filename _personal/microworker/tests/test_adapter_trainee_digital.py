"""The trainee-digital adapter: raw `tasks list` record -> task contract.

The base record below is a real row captured live 2026-09-03 from
`GET /api/orders` on Adam's authenticated trainee.digital session (order
med-seg, "Medical Image Segmentation Labels"), normalized through
trainee_digital_cli/parsers.py `normalize_order`. The same six real rows are
saved in tests/fixtures/trainee_digital_tasks_list.json and are exercised
against the adapter in `test_real_feed_rows_all_map`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli_tools_shared.exceptions import ClientError

from microworker_cli import schema
from microworker_cli.adapters import trainee_digital

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def raw(**overrides):
    record = {
        "id": "med-seg",
        "url": "https://trainee.digital/orders",
        "title": "Medical Image Segmentation Labels",
        "category": "Medical Imaging",
        "pay": "$0.40",
        "unit": "per page",
        "volume": "1,200 pages",
        "deadline": "5 days",
        "posted": "1d ago",
    }
    record.update(overrides)
    return record


def test_full_mapping():
    task = trainee_digital.to_task(raw()).task
    schema.validate_task(task)
    assert task == {
        "site": "trainee-digital",
        "task_id": "med-seg",
        "title": "Medical Image Segmentation Labels",
        "description": None,
        "url": "https://trainee.digital/orders",
        "pay_amount": 0.4,
        "pay_currency": "USD",
        "est_minutes": None,
        "slots_open": None,
        "expires_at": None,
        "raw": raw(),
    }


def test_real_feed_rows_all_map():
    """Every row of the captured real feed maps through the adapter and
    validates against the task contract."""
    payload = json.loads((FIXTURES / "trainee_digital_tasks_list.json").read_text())
    assert len(payload["tasks"]) == 6
    for record in payload["tasks"]:
        mapped = trainee_digital.to_task(record)
        schema.validate_task(mapped.task)
        assert mapped.task["site"] == "trainee-digital"
        assert mapped.unparsed_payment is False, f"unparsed: {record}"
        assert mapped.task["pay_currency"] == "USD"


@pytest.mark.parametrize("pay, expected", [
    ("$0.40", 0.4),
    ("$2,200", 2200.0),
    ("$480", 480.0),
    ("$0.90", 0.9),
    ("", None),
    ("   ", None),
    ("not a number", None),
    ("USD 1.50", None),
    ("≈ $480 total", None),
    (None, None),
    (True, None),
])
def test_parse_pay_table(pay, expected):
    assert trainee_digital.parse_pay(pay) == expected


@pytest.mark.parametrize("pay, expected", [
    ("$0.40", "USD"),
    ("$2,200", "USD"),
    (" $0.40 ", "USD"),
    ("€5", None),
    ("", None),
    (None, None),
    (5, None),
])
def test_parse_currency_table(pay, expected):
    assert trainee_digital.parse_currency(pay) == expected


def test_currency_is_none_when_pay_is_unknown():
    """A currency without an amount is not a payment fact -- both stay unset."""
    task = trainee_digital.to_task(raw(pay=None)).task
    assert task["pay_amount"] is None
    assert task["pay_currency"] is None
    schema.validate_task(task)


def test_unknown_pay_marks_unparsed_payment():
    mapped = trainee_digital.to_task(raw(pay="USD 1.50"))
    assert mapped.task["pay_amount"] is None
    assert mapped.unparsed_payment is True


@pytest.mark.parametrize("missing", ["id", "url", "title", "pay",
                                     "volume", "deadline"])
def test_missing_required_key_is_a_client_error(missing):
    record = raw()
    del record[missing]
    with pytest.raises(ClientError) as excinfo:
        trainee_digital.to_task(record)
    assert missing in str(excinfo.value)


@pytest.mark.parametrize("bad_id", [None, "", "   ", True, {"oops": 1}])
def test_unusable_id_is_a_client_error(bad_id):
    with pytest.raises(ClientError):
        trainee_digital.to_task(raw(id=bad_id))


def test_integer_id_is_stringified():
    task = trainee_digital.to_task(raw(id=42)).task
    assert task["task_id"] == "42"
    schema.validate_task(task)


def test_relative_deadline_is_not_an_expiry():
    """The feed's `deadline` is a relative human string ("5 days"), never a
    timestamp, so it must not be stored as `expires_at`."""
    task = trainee_digital.to_task(raw()).task
    assert task["expires_at"] is None
    schema.validate_task(task)
