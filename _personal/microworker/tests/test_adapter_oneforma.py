"""The oneforma adapter: raw `tasks list` record -> task contract.

The base record below is a real row captured live 2026-09-02 from
`POST /api/resource/job/v1/list-job` on Adam's authenticated OneForma session
(job 14201, "Lab Technician US"), normalized through
oneforma_cli/parsers.py `normalize_job_row`.
"""

from __future__ import annotations

import pytest
from cli_tools_shared.exceptions import ClientError

from microworker_cli import schema
from microworker_cli.adapters import adapter_for, oneforma


def raw(**overrides):
    record = {
        "id": "14201",
        "url": "https://my.oneforma.com/contributor/jobs/apply",
        "title": "Lab Technician US",
        "project_id": "1829920407671809",
        "project_name": "Project Bunsen",
        "job_type": "Data Collection",
        "project_category": "Artificial Intelligence",
        "rate": "100.0000",
        "rate_min": None,
        "rate_max": None,
        "rate_unit": "Per Hour",
        "rate_currency_symbol": "$",
        "deadline": "2026-09-30",
        "days_left": "28",
        "publish_date": "2026-09-02",
        "applicant_count": 158,
        "apply_status": None,
        "target_countries": ["United States"],
        "locale": "English (United States)",
        "platform": "WebApp",
        "invited": False,
    }
    record.update(overrides)
    return record


def test_full_mapping():
    task = oneforma.to_task(raw())
    schema.validate_task(task)
    assert task == {
        "site": "oneforma",
        "task_id": "14201",
        "title": "Lab Technician US",
        "url": "https://my.oneforma.com/contributor/jobs/apply",
        "pay_amount": 100.0,
        "pay_currency": "USD",
        "est_minutes": None,
        "slots_open": None,
        "expires_at": "2026-09-30",
        "raw": raw(),
    }


def test_registered_in_adapters():
    assert adapter_for("oneforma") is oneforma.to_task


@pytest.mark.parametrize("rate, expected", [
    ("100.0000", 100.0),
    ("0.5000", 0.5),
    (30, 30.0),
    (12.5, 12.5),
    ("", None),
    ("   ", None),
    ("not a number", None),
    (None, None),
    (True, None),
])
def test_parse_rate_table(rate, expected):
    assert oneforma.parse_rate(rate) == expected


@pytest.mark.parametrize("symbol, expected", [
    ("$", "USD"),
    (" $ ", "USD"),
    ("€", None),
    ("", None),
    (None, None),
    (5, None),
])
def test_parse_currency_table(symbol, expected):
    assert oneforma.parse_currency(symbol) == expected


def test_currency_is_none_when_rate_is_unknown():
    """A currency without an amount is not a payment fact — both stay unset."""
    task = oneforma.to_task(raw(rate=None))
    assert task["pay_amount"] is None
    assert task["pay_currency"] is None
    schema.validate_task(task)


def test_unknown_symbol_keeps_amount_but_not_currency():
    task = oneforma.to_task(raw(rate_currency_symbol="€"))
    assert task["pay_amount"] == 100.0
    assert task["pay_currency"] is None
    schema.validate_task(task)


@pytest.mark.parametrize("missing", ["id", "url", "title", "rate",
                                     "rate_currency_symbol", "deadline"])
def test_missing_required_key_is_a_client_error(missing):
    record = raw()
    del record[missing]
    with pytest.raises(ClientError) as excinfo:
        oneforma.to_task(record)
    assert missing in str(excinfo.value)


@pytest.mark.parametrize("bad_id", [None, "", "   ", True, {"oops": 1}])
def test_unusable_id_is_a_client_error(bad_id):
    with pytest.raises(ClientError):
        oneforma.to_task(raw(id=bad_id))


def test_integer_id_is_stringified():
    task = oneforma.to_task(raw(id=14201))
    assert task["task_id"] == "14201"
    schema.validate_task(task)


def test_null_deadline_maps_to_null_expiry():
    task = oneforma.to_task(raw(deadline=None))
    assert task["expires_at"] is None
    schema.validate_task(task)
