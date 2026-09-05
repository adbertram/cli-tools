"""The outlier adapter: raw `tasks list` record -> task contract.

No live assignment existed on the Outlier account when this adapter was built:
the account's queue is empty and gated behind Outlier's KYC / pay-setup step
(`outlier queue status` reports `empty_queue_reason: "KYCInfoCollection"`), so
the record below is the output of `outlier_cli.parsers.normalize_task_rows()`
run on one of the twelve `peek_queue` response fixtures Outlier ships inside
its own deployed frontend bundle — not a captured real record like
`microworkers_record`.
"""

from __future__ import annotations

import pytest
from cli_tools_shared.exceptions import ClientError

from microworker_cli import schema
from microworker_cli.adapters import adapter_for, outlier


def raw(**overrides):
    record = {
        "id": "66edda0f65beb7be44e8d0a7",
        "url": "https://app.outlier.ai/expert/course?id=67c17b368fd2e378fa49d92c",
        "type": "OUTLIER_QUALIFICATION_IN_QUEUE",
        "assignment_type": "chosen",
        "node_type": None,
        "project_id": "66edda0f65beb7be44e8d0a7",
        "review_level": -1,
        "onboarding_flow_id": "66edda11c59ea1429a668c76",
        "name": "Mail Valley - Intro Course v2",
        "display_name": "Mail Valley - Intro Course v2",
        "description": "Mail Valley - Intro Course v2",
        "qualification_id": "67c17b368fd2e378fa49d931",
        "qualification_type": "course",
        "qualification_status": "worker_pending",
        "qualification_list_status": "pending",
        "qualification_estimated_time": 0,
        "is_assessment": False,
        "is_pay_multiplier": False,
        "created_at": "2025-02-28T09:00:38.967Z",
        "updated_at": "2025-03-01T20:54:59.600Z",
    }
    record.update(overrides)
    return record


def test_full_mapping():
    task = outlier.to_task(raw()).task
    schema.validate_task(task)
    assert task == {
        "site": "outlier",
        "task_id": "66edda0f65beb7be44e8d0a7",
        "title": "Mail Valley - Intro Course v2",
        "description": "Mail Valley - Intro Course v2",
        "url": "https://app.outlier.ai/expert/course?id=67c17b368fd2e378fa49d92c",
        "pay_amount": None,
        "pay_currency": None,
        "est_minutes": None,
        "slots_open": None,
        "expires_at": None,
        "raw": raw(),
    }


def test_registered_under_its_site_name():
    assert adapter_for("outlier") is outlier.to_task


def test_site_publishes_no_price_to_misread():
    """Outlier puts no payment on an assignment, so the `mapped.py` seam
    reports False as a fact about the site, not as a default."""
    assert outlier.to_task(raw()).unparsed_payment is False


def test_estimated_time_is_not_claimed_as_minutes():
    """`qualification_estimated_time` is an unlabelled number in Outlier's own
    UI, so a non-zero value must still leave `est_minutes` null."""
    task = outlier.to_task(raw(qualification_estimated_time=45)).task
    assert task["est_minutes"] is None
    assert task["raw"]["qualification_estimated_time"] == 45


def test_title_is_the_display_name():
    task = outlier.to_task(
        raw(display_name="Shown To Worker", name="Internal Name")).task
    assert task["title"] == "Shown To Worker"


@pytest.mark.parametrize("key", ["id", "url", "display_name"])
def test_missing_required_key_is_an_error(key):
    record = raw()
    del record[key]
    with pytest.raises(ClientError, match=f"outlier record is missing keys: {key}"):
        outlier.to_task(record)


@pytest.mark.parametrize("bad_id", [None, "", "   ", True, {"oops": 1}, "x" * 201])
def test_unusable_id_is_an_error(bad_id):
    with pytest.raises(ClientError):
        outlier.to_task(raw(id=bad_id))
