"""The humanrail adapter: raw `tasks list` record -> task contract.

No live task existed on the HumanRail account when this adapter was built
(the site's own /api/workers/me/tasks/available returned zero tasks), so
these are synthetic records built from the raw field names verified in
humanrail_cli/parsers.py (`normalize_task_row`) and the site's own frontend
bundle — not a captured real record like `microworkers_record`.
"""

from __future__ import annotations

import pytest
from cli_tools_shared.exceptions import ClientError

from microworker_cli import schema
from microworker_cli.adapters import adapter_for, humanrail


def raw(**overrides):
    record = {
        "id": "3f7c1e2a-2b1a-4a3e-9c2d-1a2b3c4d5e6f",
        "url": "https://routehuman.com/queue/3f7c1e2a-2b1a-4a3e-9c2d-1a2b3c4d5e6f",
        "type": "contract_review",
        "payout_sats": 2500,
        "risk_tier": "low",
        "skills_required": ["contract_review"],
        "estimated_minutes": 20,
        "sla_deadline": "2026-09-03T00:00:00Z",
        "sla_seconds": 3600,
    }
    record.update(overrides)
    return record


def test_full_mapping():
    task = humanrail.to_task(raw())
    schema.validate_task(task)
    assert task == {
        "site": "humanrail",
        "task_id": "3f7c1e2a-2b1a-4a3e-9c2d-1a2b3c4d5e6f",
        "title": "Contract Review",
        "url": "https://routehuman.com/queue/3f7c1e2a-2b1a-4a3e-9c2d-1a2b3c4d5e6f",
        "pay_amount": 2500,
        "pay_currency": "SATS",
        "est_minutes": 20,
        "slots_open": None,
        "expires_at": "2026-09-03T00:00:00Z",
        "raw": raw(),
    }


@pytest.mark.parametrize("task_type, expected", [
    ("contract_review", "Contract Review"),
    ("compliance_checklist", "Compliance Checklist"),
    ("data_labeling", "Data Labeling"),
    ("", None),
    (None, None),
    (42, None),
])
def test_title_for_table(task_type, expected):
    assert humanrail.title_for(task_type) == expected


def test_payout_sats_none_means_currency_none():
    task = humanrail.to_task(raw(payout_sats=None))
    assert task["pay_amount"] is None
    assert task["pay_currency"] is None


@pytest.mark.parametrize("task_id", [None, "", "   "])
def test_missing_or_empty_id_is_client_error(task_id):
    with pytest.raises(ClientError, match="'id'"):
        humanrail.to_task(raw(id=task_id))


@pytest.mark.parametrize("task_id", [True, False, {"oops": 1}, ["a"], 1.5])
def test_non_scalar_id_is_client_error(task_id):
    """A non-scalar id must never be stringified into a primary key.

    `bool` is here because it is an `int` subclass in Python: without an
    explicit check, JSON `true` becomes the task id `"True"`.
    """
    with pytest.raises(ClientError, match="must be a string or an integer"):
        humanrail.to_task(raw(id=task_id))


def test_overlong_id_is_client_error():
    with pytest.raises(ClientError, match="characters"):
        humanrail.to_task(raw(id="x" * 5000))


def test_padded_id_is_stripped():
    assert humanrail.to_task(raw(id="  42  "))["task_id"] == "42"


def test_absent_raw_key_is_client_error():
    record = raw()
    del record["estimated_minutes"]
    with pytest.raises(ClientError, match="missing keys: estimated_minutes"):
        humanrail.to_task(record)


def test_integer_id_becomes_string():
    assert humanrail.to_task(raw(id=42))["task_id"] == "42"


def test_slots_open_is_always_none():
    assert humanrail.to_task(raw())["slots_open"] is None


def test_adapter_registry():
    assert adapter_for("humanrail") is humanrail.to_task
