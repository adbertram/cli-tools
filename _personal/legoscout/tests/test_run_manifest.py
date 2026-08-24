"""The run manifest proves active-source and appraisal coverage."""
from __future__ import annotations

import json

import pytest

from legoscout_cli.orchestrator import build_run_manifest
from legoscout_cli.ledger import build_record
from legoscout_cli.sources import registry


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _source(candidates, *, blocked=False):
    return {
        "source": "Active Source",
        "checked": not blocked,
        "blocked": blocked,
        "blocker": "blocked fixture" if blocked else None,
        "candidate_records": candidates,
        "unavailable_updates": [],
        "unchanged_duplicate_keys": [],
        "learning_notes": [],
        "actions_requiring_approval": [],
        "evidence_summary": "The fixture reached a terminal state.",
        "completed_at": "2026-08-15T00:00:00Z",
    }


def _appraisal(key):
    return {
        "listing_key": key,
        "listing_category": "bulk",
        "estimated_total": 25.0,
        "handling_fee": 0.0,
        "per_lb_price": 5.0,
        "per_lb_price_basis": "landed",
        "confidence": "medium",
        "shipping_estimated": False,
        "pickup_miles": 1.0,
        "fee_breakdown": {
            "source": "shopgoodwill",
            "hammer": 25.0,
            "premium_pct": 0.0,
            "premium_fixed": 0.0,
            "premium_amount": 0.0,
            "premium_is_default": False,
            "sales_tax_pct": 0.0,
            "sales_tax_amount": 0.0,
            "sales_tax_rule": "none",
            "sales_tax_is_default": False,
            "tax_basis": "hammer_plus_premium",
            "shipping_handling": 0.0,
            "shipping_unknown": False,
            "landed_is_floor": False,
            "landed_total": 25.0,
            "fee_multiple": 1.0,
            "confidence_note": "fixture",
        },
        "observations": {
            "model_score": 50,
            "model_rationale": "The fixture has neutral deal evidence.",
        },
    }


def _candidate(number):
    key = "shopgoodwill|manifest-%02d" % number
    return {
        "listing_key": key,
        "source": "shopgoodwill",
        "title": "LEGO bulk lot",
        "url": "https://shopgoodwill.com/item/manifest-%02d" % number,
        "direct_url": "https://shopgoodwill.com/item/manifest-%02d" % number,
        "posted_date": "2026-08-15",
        "auction_start_date": "not-an-auction",
        "auction_end_date": "not-an-auction",
        "current_price": None,
        "buy_now_price": 25.0,
        "static_price": None,
        "price_basis": "buy_now",
        "listing_type": "fixed",
        "weight_lbs": 5.0,
        "item_location": "Evansville, IN 47725",
        "origin_zip": "47725",
        "seller_id": None,
        "seller_name": None,
        "available_fulfillment": ["shipping"],
        "image_urls": [],
        "shipping_estimate": {
            "status": "quoted",
            "shipping_price": 0.0,
            "handling_price": None,
            "service": "fixture",
        },
    }


def _run_one(tmp_path, candidate, appraisal):
    _write(tmp_path / "shopgoodwill.json", _source([candidate]))
    _write(tmp_path / "shopgoodwill.appraisal-1.json", [appraisal])
    return build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])


def test_manifest_uses_active_registry_sources_not_dormant_rows(
        monkeypatch, tmp_path):
    monkeypatch.setattr(registry, "active_namespaces", lambda: ["active-source"])
    _write(tmp_path / "active-source.json", _source([], blocked=True))
    _write(tmp_path / "reddit.json", _source([], blocked=False))

    manifest = build_run_manifest(str(tmp_path))

    assert manifest["active_sources"] == ["active-source"]
    assert [item["source"] for item in manifest["sources"]] == ["active-source"]
    assert manifest["complete"] is True


def test_manifest_checks_fixed_batches_and_nested_verdicts(tmp_path):
    candidates = [_candidate(number) for number in range(26)]
    _write(tmp_path / "shopgoodwill.json", _source(candidates))
    _write(tmp_path / "shopgoodwill.appraisal-1.json",
           [_appraisal(item["listing_key"]) for item in candidates[:25]])
    _write(tmp_path / "shopgoodwill.appraisal-2.json",
           [_appraisal(candidates[25]["listing_key"])])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    assert manifest["complete"] is True
    source = manifest["sources"][0]
    assert source["expected_appraisal_batches"] == 2
    assert [batch["candidate_count"] for batch in source["appraisal_batches"]] == [25, 1]
    assert all(batch["complete"] for batch in source["appraisal_batches"])
    assert [batch["buildable_count"] for batch in source["appraisal_batches"]] == [25, 1]


def test_manifest_reports_a_misplaced_model_verdict(tmp_path):
    candidates = [_candidate(1)]
    _write(tmp_path / "shopgoodwill.json", _source(candidates))
    bad = _appraisal(candidates[0]["listing_key"])
    bad["model_score"] = bad["observations"].pop("model_score")
    _write(tmp_path / "shopgoodwill.appraisal-1.json", [bad])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    assert manifest["complete"] is False
    assert "misplaced top-level model_score" in manifest["sources"][0]["problems"][0]


@pytest.mark.parametrize(
    ("mutate", "error_text"),
    [
        (lambda _candidate, appraisal: appraisal.update(confidence=None),
         "confidence: None is not of type 'string'"),
        (lambda _candidate, appraisal: appraisal.update(risks_unknowns=["risk"]),
         "risks_unknowns: ['risk'] is not of type 'string'"),
        (lambda _candidate, appraisal: appraisal.update(fee_breakdown=None),
         "fee_breakdown is None"),
        (lambda _candidate, appraisal: appraisal["fee_breakdown"].pop(
            "premium_amount"),
         "fee_breakdown.premium_amount is absent"),
    ],
)
def test_manifest_rejects_exact_key_pairs_that_cannot_build(
        tmp_path, mutate, error_text):
    candidate = _candidate(1)
    appraisal = _appraisal(candidate["listing_key"])
    mutate(candidate, appraisal)

    manifest = _run_one(tmp_path, candidate, appraisal)

    assert manifest["complete"] is False
    batch = manifest["sources"][0]["appraisal_batches"][0]
    assert batch["candidate_count"] == 1
    assert batch["appraisal_count"] == 1
    assert batch["listing_keys"] == [candidate["listing_key"]]
    assert batch["buildable_count"] == 0
    assert batch["build_errors"][0]["listing_key"] == candidate["listing_key"]
    assert error_text in batch["build_errors"][0]["error"]


def test_manifest_counts_out_of_radius_pickup_only_candidate_as_gate_rejected(tmp_path):
    """The pickup gate's sanctioned answer is `status: rejected` with the reason
    in notes -- `legoscout-pricing` `<fulfillment>` says exactly that. The dry
    proof must retry under that status and count the pair as buildable, with
    `gate_rejected_count` naming what happened, instead of failing the whole
    batch like a coverage defect."""
    candidate = _candidate(1)
    appraisal = _appraisal(candidate["listing_key"])
    candidate["available_fulfillment"] = ["local_pickup"]
    candidate["item_location"] = "Tallahassee, FL"
    candidate["origin_zip"] = "32301"
    candidate["shipping_estimate"] = None
    appraisal["pickup_miles"] = None

    manifest = _run_one(tmp_path, candidate, appraisal)

    assert manifest["complete"] is True
    batch = manifest["sources"][0]["appraisal_batches"][0]
    assert batch["listing_keys"] == [candidate["listing_key"]]
    assert batch["buildable_count"] == 1
    assert batch["gate_rejected_count"] == 1
    assert batch["build_errors"] == []


def test_manifest_still_fails_a_pair_that_rejects_even_with_rejected_status(tmp_path):
    """The rejected-status retry is ONLY for the pickup-radius gate. A record
    with a second, independent defect must still fail the batch by name."""
    candidate = _candidate(1)
    appraisal = _appraisal(candidate["listing_key"])
    candidate["available_fulfillment"] = ["local_pickup"]
    candidate["item_location"] = "Tallahassee, FL"
    candidate["origin_zip"] = "32301"
    candidate["shipping_estimate"] = None
    appraisal["pickup_miles"] = None
    # A second, unrelated defect: an illegal listing_type fails under ANY
    # status, so the rejected-status retry cannot mask it.
    candidate["listing_type"] = "weird"

    manifest = _run_one(tmp_path, candidate, appraisal)

    assert manifest["complete"] is False
    batch = manifest["sources"][0]["appraisal_batches"][0]
    assert batch["buildable_count"] == 0
    assert batch["build_errors"][0]["listing_key"] == candidate["listing_key"]


def test_manifest_build_proof_does_not_open_the_seller_ledger(
        monkeypatch, tmp_path):
    candidate = _candidate(1)
    candidate["seller_id"] = "fixture-seller"
    candidate["seller_name"] = "Fixture Seller"
    appraisal = _appraisal(candidate["listing_key"])
    monkeypatch.setattr(
        build_record.sellers_db,
        "is_favorite",
        lambda *_args, **_kwargs: pytest.fail("manifest opened the seller ledger"),
    )

    manifest = _run_one(tmp_path, candidate, appraisal)

    assert manifest["complete"] is True
