"""The microworkers adapter: raw `tasks list` record -> task contract."""

from __future__ import annotations

import pytest
from cli_tools_shared.exceptions import ClientError

from microworker_cli import schema
from microworker_cli.adapters import adapter_for, microworkers


def raw(**overrides):
    record = {
        "id": "https://microworkers.com/jobs.php?id=1",
        "campaign_id": "abc123",
        "title": "Sign up and screenshot",
        "provider": "microworkers",
        "url": "https://microworkers.com/jobs.php?id=1",
        "payment": "$0.15",
        "success_rate_required": 75,
        "ttr_days": 7,
        "ttf_minutes": 4,
        "positions_done": 2980,
        "positions_total": 3000,
    }
    record.update(overrides)
    return record


def test_real_record_maps_and_validates(microworkers_record):
    task = microworkers.to_task(microworkers_record).task
    schema.validate_task(task)
    assert task["site"] == "microworkers"
    assert task["task_id"] == str(microworkers_record["campaign_id"])
    assert task["raw"] is microworkers_record
    assert task["expires_at"] is None


def test_full_mapping():
    task = microworkers.to_task(raw()).task
    schema.validate_task(task)
    assert task == {
        "site": "microworkers",
        "task_id": "abc123",
        "title": "Sign up and screenshot",
        "description": None,
        "url": "https://microworkers.com/jobs.php?id=1",
        "pay_amount": 0.15,
        "pay_currency": "USD",
        "est_minutes": 4,
        "slots_open": 20,
        "expires_at": None,
        "raw": raw(),
    }


@pytest.mark.parametrize("payment, expected", [
    ("$0.15", (0.15, "USD")),
    ("$12.00", (12.0, "USD")),
    (" $1.05 ", (1.05, "USD")),
    ("$1", (None, None)),
    ("0.15", (None, None)),
    ("$0.1", (None, None)),
    ("USD 0.15", (None, None)),
    ("$0.15 - $0.30", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
    (0.15, (None, None)),
])
def test_payment_table(payment, expected):
    assert microworkers.parse_payment(payment) == expected


@pytest.mark.parametrize("done, total, expected", [
    (2980, 3000, 20),
    (0, 0, 0),
    (None, 3000, None),
    (2980, None, None),
    ("2980", 3000, None),
])
def test_slots_open_table(done, total, expected):
    assert microworkers.slots_open(done, total) == expected


@pytest.mark.parametrize("campaign_id", [None, "", "   "])
def test_missing_or_empty_campaign_id_is_client_error(campaign_id):
    with pytest.raises(ClientError, match="campaign_id"):
        microworkers.to_task(raw(campaign_id=campaign_id))


@pytest.mark.parametrize("campaign_id", [True, {"oops": 1}, ["a"], 1.5])
def test_non_scalar_campaign_id_is_client_error(campaign_id):
    with pytest.raises(ClientError, match="must be a string or an integer"):
        microworkers.to_task(raw(campaign_id=campaign_id))


def test_overlong_campaign_id_is_client_error():
    with pytest.raises(ClientError, match="characters"):
        microworkers.to_task(raw(campaign_id="x" * 5000))


def test_absent_raw_key_is_client_error():
    record = raw()
    del record["ttf_minutes"]
    with pytest.raises(ClientError, match="missing keys: ttf_minutes"):
        microworkers.to_task(record)


def test_integer_campaign_id_becomes_string():
    assert microworkers.to_task(raw(campaign_id=42)).task["task_id"] == "42"


def test_adapter_registry():
    assert adapter_for("microworkers") is microworkers.to_task
    # Every config.json site now has a registered adapter (2026-09-03 added
    # mercor + the atlas-capture/trainee-digital/crowdgen refusal adapters),
    # so the roster-wide contract is: every site resolves to a callable.
    for site in ("atlas-capture", "crowdgen", "humanrail", "mercor",
                 "microworkers", "oneforma", "outlier",
                 "trainee-digital"):
        assert callable(adapter_for(site))
    # A site outside the roster must still be refused, never mapped by guesswork.
    with pytest.raises(ClientError, match="no adapter for site 'nosuchsite'"):
        adapter_for("nosuchsite")


@pytest.mark.parametrize("site", ["crowdgen", "atlas-capture"])
def test_unimplemented_adapters_raise_client_error(site):
    """A ClientError, so the CLI's exit-2 contract handler sees it.

    A `NotImplementedError` escapes that handler and exits 1, which the
    discovery agent reads as an unexpected crash rather than bad input.
    """
    with pytest.raises(ClientError, match=site):
        adapter_for(site)({"id": 1})
