"""The crowdgen adapter: raw `crowdgen tasks list` record -> task contract.

No real CrowdGen task record has ever been captured (registration is
Kasada-blocked for automation and onboarding is human-gated), so the adapter's
contract is currently a loud refusal: nothing is mapped from an unobserved
shape. These tests pin that boundary so a future real capture cannot silently
start producing guessed records.
"""

from __future__ import annotations

import pytest
from cli_tools_shared.exceptions import ClientError

from microworker_cli.adapters import crowdgen


def test_site_name():
    assert crowdgen.SITE == "crowdgen"


def test_raw_keys_empty_until_live_capture():
    # No raw field has been observed yet, so no key may be claimed as required.
    assert crowdgen.RAW_KEYS == ()


def test_to_task_refuses_empty_record():
    with pytest.raises(ClientError, match="empty"):
        crowdgen.to_task({})


def test_to_task_refuses_unobserved_record_shape():
    record = {
        "id": "made-up-project-id",
        "title": "A made-up project",
        "url": "https://app.crowdgen.com/projects/available/made-up",
    }
    with pytest.raises(ClientError, match="refused"):
        crowdgen.to_task(record)


def test_to_task_refuses_any_shape():
    # Even a record shaped like other sites' records is refused: there is no
    # evidence CrowdGen returns those keys.
    for record in (
        {"campaign_id": "x", "title": "t", "url": "u", "payment": "$1.00"},
        {"task_id": "t", "pay_amount": 1.0, "pay_currency": "USD"},
        [{"id": 1}],
        "a string",
        42,
        None,
    ):
        with pytest.raises(ClientError):
            crowdgen.to_task(record)
