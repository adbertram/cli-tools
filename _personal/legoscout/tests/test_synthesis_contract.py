"""Synthesis rejects source facts that cannot become actionable deals."""
from __future__ import annotations

import pytest

from legoscout_cli.ledger import build_record
from legoscout_cli.orchestrator import (
    AppraisalBatchKeyError,
    appraisal_coverage,
    validate_appraisal_batch,
)


def _record(key, **changes):
    record = {
        "listing_key": key,
        "source": key.split("|", 1)[0],
        "listing_type": "fixed",
        "price_basis": "current_price",
        "current_price": 25.0,
        "available_fulfillment": ["shipping"],
        "status": "active",
        "fee_breakdown": {"hammer": 25.0},
    }
    record.update(changes)
    return record


def _appraisal(key, **changes):
    record = {
        "listing_key": key,
        "listing_category": "bulk",
        "observations": {
            "model_score": 50,
            "model_rationale": "The fixture has neutral deal evidence.",
        },
    }
    record.update(changes)
    return record


def test_appraisal_batch_returns_results_by_matching_listing_key():
    candidates = [_record("ebay|1"), _record("ebay|2")]
    appraisals = [
        _appraisal("ebay|2", classification="bulk"),
        _appraisal("ebay|1", classification="set"),
    ]

    by_key = validate_appraisal_batch(candidates, appraisals)

    assert by_key == {
        "ebay|1": appraisals[1],
        "ebay|2": appraisals[0],
    }


def test_appraisal_batch_rejects_missing_result_keys():
    candidates = [_record("ebay|1"), _record("ebay|2")]

    with pytest.raises(
            AppraisalBatchKeyError,
            match=r"missing appraisal results: ebay\|2"):
        validate_appraisal_batch(candidates, [_appraisal("ebay|1")])


def test_appraisal_batch_rejects_extra_result_keys():
    candidates = [_record("ebay|1")]
    appraisals = [
        _appraisal("ebay|1"),
        _appraisal("ebay|2"),
    ]

    with pytest.raises(
            AppraisalBatchKeyError,
            match=r"extra appraisal results: ebay\|2"):
        validate_appraisal_batch(candidates, appraisals)


@pytest.mark.parametrize(
    ("candidates", "appraisals", "message"),
    [
        (
            [_record("ebay|1"), _record("ebay|1")],
            [_appraisal("ebay|1")],
            r"duplicate source candidate keys: ebay\|1",
        ),
        (
            [_record("ebay|1")],
            [_appraisal("ebay|1"), _appraisal("ebay|1")],
            r"duplicate appraisal result keys: ebay\|1",
        ),
    ],
)
def test_appraisal_batch_rejects_duplicate_keys(
        candidates, appraisals, message):
    with pytest.raises(AppraisalBatchKeyError, match=message):
        validate_appraisal_batch(candidates, appraisals)


@pytest.mark.parametrize("bad_root", ({"listing_key": "ebay|1"}, "bad", None))
def test_appraisal_batch_rejects_non_array_roots(bad_root):
    with pytest.raises(AppraisalBatchKeyError, match="must be an array"):
        validate_appraisal_batch(bad_root, [])
    with pytest.raises(AppraisalBatchKeyError, match="must be an array"):
        validate_appraisal_batch([], bad_root)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"observations": {"model_score": None,
                            "model_rationale": "No score."}}, "model_score"),
        ({"observations": {"model_score": 50,
                            "model_rationale": ""}}, "model_rationale"),
        ({"model_score": 50, "model_rationale": "Top level."}, "misplaced"),
    ],
)
def test_appraisal_batch_rejects_an_unusable_model_verdict(changes, message):
    appraisal = _appraisal("ebay|1")
    appraisal.update(changes)

    with pytest.raises(AppraisalBatchKeyError, match=message):
        validate_appraisal_batch([_record("ebay|1")], [appraisal])


def test_appraisal_coverage_reports_exact_sorted_keys():
    report = appraisal_coverage(
        [_record("ebay|2"), _record("ebay|1")],
        [_appraisal("ebay|1"), _appraisal("ebay|2")])

    assert report == {
        "complete": True,
        "candidate_count": 2,
        "appraisal_count": 2,
        "listing_keys": ["ebay|1", "ebay|2"],
        "error": None,
    }


def test_build_rejects_list_roots_before_attribute_access():
    with pytest.raises(ValueError, match="candidate must be an object"):
        build_record.build_deal_record(
            [], _appraisal("ebay|1"),
            first_seen_at="2026-08-15T00:00:00Z",
            last_seen_at="2026-08-15T00:00:00Z")
    with pytest.raises(ValueError, match="appraisal must be an object"):
        build_record.build_deal_record(
            _record("ebay|1"), [],
            first_seen_at="2026-08-15T00:00:00Z",
            last_seen_at="2026-08-15T00:00:00Z")


def test_synthesis_rejects_a_hammer_that_disagrees_with_the_price_basis():
    record = _record(
        "shopgoodwill|stale-bin", listing_type="auction_with_buy_now",
        current_price=50.0, buy_now_price=10.0, price_basis="current_price",
        fee_breakdown={"hammer": 10.0})

    with pytest.raises(ValueError, match="hammer=10.0 disagrees with the current_price of 50.0"):
        build_record._require_semantically_valid(record)
