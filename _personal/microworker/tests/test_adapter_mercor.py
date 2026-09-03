"""The mercor adapter: raw `tasks list` record -> task contract.

The base record is REAL: it is the first record of
`tests/fixtures/mercor_tasks_list.json`, captured live 2026-09-03 from
`GET https://aws.api.mercor.com/work/listings-explore-page` on Adam's
authenticated Mercor worker session -- listing `list_AAABoGYcR_Q8k7gMhOdC84s-`
"Certified Medical Coder (ICD-10) -- Multilingual Clinical Documentation & AI
Evaluation", normalized through mercor_cli/parsers.py `normalize_listing`
(the shape `mercor tasks list` emits).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli_tools_shared.exceptions import ClientError

from microworker_cli import schema
from microworker_cli.adapters import mercor

FIXTURE = json.loads(
    (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mercor_tasks_list.json"
    ).read_text(encoding="utf-8")
)


def raw(**overrides):
    record = dict(FIXTURE[0])
    record.update(overrides)
    return record


def test_real_record_maps_and_validates():
    task = mercor.to_task(raw()).task
    schema.validate_task(task)
    assert task["site"] == "mercor"
    assert task["task_id"] == "list_AAABoGYcR_Q8k7gMhOdC84s-"
    assert task["title"] == FIXTURE[0]["title"]
    assert task["url"] == FIXTURE[0]["url"]
    assert task["pay_amount"] is None  # published as a range (45.0..65.0)
    assert task["pay_currency"] is None
    assert task["slots_open"] == 5      # remainingSlots on the real record
    assert task["expires_at"] is None
    assert task["raw"] is not None


def test_single_price_point_maps_to_pay_amount():
    """rateMin == rateMax is a single published price point (e.g. a per-task
    or one-time fixed price) and maps to pay_amount with null currency."""
    task = mercor.to_task(
        raw(rateMin=2000.0, rateMax=2000.0, payRateFrequency="per-task")
    ).task
    assert task["pay_amount"] == 2000.0
    assert task["pay_currency"] is None
    schema.validate_task(task)


def test_range_keeps_pay_amount_null():
    """A range (rateMin < rateMax) is not a single published price: null, and
    the numbers stay visible in raw rather than the low bound being reported
    as the price."""
    task = mercor.to_task(raw(rateMin=10.0, rateMax=20.0)).task
    assert task["pay_amount"] is None
    assert task["raw"]["rateMin"] == 10.0
    assert task["raw"]["rateMax"] == 20.0


@pytest.mark.parametrize("rate_min,rate_max", [
    (None, None),
    (None, 20.0),
    (10.0, None),
    ("10.0", 20.0),      # non-numeric string is not a published number
    (True, 20.0),
])
def test_unusable_rates_leave_pay_amount_null(rate_min, rate_max):
    task = mercor.to_task(raw(rateMin=rate_min, rateMax=rate_max)).task
    assert task["pay_amount"] is None
    schema.validate_task(task)


@pytest.mark.parametrize("remaining,expected", [
    (5, 5), (0, 0), (None, None),
    (True, None), ("5", None), (5.0, None),
])
def test_slots_open_table(remaining, expected):
    assert mercor.slots_open(remaining) == expected


def test_no_site_published_price_was_misread():
    """unparsed_payment stays False: Mercor's rate numbers are read and kept
    verbatim in raw, and a null pay_amount is the adapter's deliberate mapping
    (range / no currency code), not a parse failure."""
    assert mercor.to_task(raw()).unparsed_payment is False
    assert mercor.to_task(raw(rateMin=10.0, rateMax=10.0)).unparsed_payment is False


@pytest.mark.parametrize("missing", ["listingId", "title", "url"])
def test_missing_required_key_is_an_error(missing):
    record = raw()
    del record[missing]
    with pytest.raises(ClientError, match=f"mercor record is missing keys: {missing}"):
        mercor.to_task(record)


@pytest.mark.parametrize("bad_id", [None, "", "   ", True, {"oops": 1}, "x" * 201])
def test_unusable_listing_id_is_an_error(bad_id):
    with pytest.raises(ClientError):
        mercor.to_task(raw(listingId=bad_id))
