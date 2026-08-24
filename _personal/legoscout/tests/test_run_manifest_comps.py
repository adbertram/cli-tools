"""The manifest's comps-batch gate: a SET candidate must have a matching
comps result to build; a BULK candidate never needed one."""
from __future__ import annotations

import json

from legoscout_cli.orchestrator import build_run_manifest


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _source(candidates):
    return {
        "source": "Active Source", "checked": True, "blocked": False, "blocker": None,
        "candidate_records": candidates, "unavailable_updates": [],
        "unchanged_duplicate_keys": [], "learning_notes": [],
        "actions_requiring_approval": [],
        "evidence_summary": "The fixture reached a terminal state.",
        "completed_at": "2026-08-20T00:00:00Z",
    }


def _candidate(number, key_prefix="shopgoodwill|manifest"):
    key = "%s-%02d" % (key_prefix, number)
    return {
        "listing_key": key, "source": "shopgoodwill", "title": "LEGO 75192-1",
        "url": "https://shopgoodwill.com/item/%02d" % number,
        "direct_url": "https://shopgoodwill.com/item/%02d" % number,
        "posted_date": "2026-08-20", "auction_start_date": "not-an-auction",
        "auction_end_date": "not-an-auction", "current_price": None,
        "buy_now_price": 300.0, "static_price": None, "price_basis": "buy_now",
        "listing_type": "fixed", "weight_lbs": 13.0,
        "item_location": "Evansville, IN 47725", "origin_zip": "47725",
        "seller_id": None, "seller_name": None,
        "available_fulfillment": ["shipping"], "image_urls": [],
        "shipping_estimate": {"status": "quoted", "shipping_price": 0.0,
                              "handling_price": None, "service": "fixture"},
    }


def _appraisal(key, listing_category="set"):
    return {
        "listing_key": key, "listing_category": listing_category,
        "estimated_total": 300.0, "handling_fee": 0.0, "per_lb_price": 23.08,
        "per_lb_price_basis": "landed", "confidence": "medium",
        "shipping_estimated": False, "pickup_miles": 1.0,
        "set_completeness": "complete", "set_condition": "U",
        "fee_breakdown": {
            "source": "shopgoodwill", "hammer": 300.0, "premium_pct": 0.0,
            "premium_fixed": 0.0, "premium_amount": 0.0, "premium_is_default": False,
            "sales_tax_pct": 0.0, "sales_tax_amount": 0.0, "sales_tax_rule": "none",
            "sales_tax_is_default": False, "tax_basis": "hammer_plus_premium",
            "shipping_handling": 0.0, "shipping_unknown": False,
            "landed_is_floor": False, "landed_total": 300.0, "fee_multiple": 1.0,
            "confidence_note": "fixture",
        },
        "observations": {"model_score": 60,
                         "model_rationale": "The fixture has neutral deal evidence."},
    }


def _comps(key, found=True):
    summary = {
        "condition": "U", "guide_type": "sold",
        "sold_window": "bricklink_sold_guide_last_6_months",
        "six_month_avg_sold_price": 500.0, "avg_price": 500.0,
        "price_detail_count": 10,
    }
    bricklink = ({"set_no": "75192-1", "lookup_status": "found",
                 "catalog": {"no": "75192-1", "name": "Millennium Falcon"},
                 "condition": "U", "purchase_price": None, "fee_rate": None,
                 "used": summary, "new": None, "selected_condition_summary": summary,
                 "selected_condition_priced": True, "potential_profit": None}
                if found else None)
    return {"listing_key": key, "mode": "set",
           "sets": [{"set_no": "75192-1", "bricklink": bricklink,
                    "ebay": {"available": False, "reason": "ebay_auth_required"}}]}


def test_set_candidate_with_matching_comps_batch_builds(tmp_path):
    candidate = _candidate(1)
    key = candidate["listing_key"]
    _write(tmp_path / "shopgoodwill.json", _source([candidate]))
    _write(tmp_path / "shopgoodwill.appraisal-1.json", [_appraisal(key)])
    _write(tmp_path / "shopgoodwill.comps-1.json", [_comps(key)])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    assert manifest["complete"] is True
    batch = manifest["sources"][0]["appraisal_batches"][0]
    assert batch["comps_count"] == 1
    assert batch["buildable_count"] == 1


def test_set_candidate_with_no_comps_batch_fails_that_candidate(tmp_path):
    """No comps-N.json at all: bulk still builds elsewhere, but a SET
    candidate surfaces a per-candidate build_errors entry, not a silent gap."""
    candidate = _candidate(1)
    key = candidate["listing_key"]
    _write(tmp_path / "shopgoodwill.json", _source([candidate]))
    _write(tmp_path / "shopgoodwill.appraisal-1.json", [_appraisal(key)])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    assert manifest["complete"] is False
    batch = manifest["sources"][0]["appraisal_batches"][0]
    assert batch["buildable_count"] == 0
    assert "SET candidate with no comps result" in batch["build_errors"][0]["error"]


def test_bulk_candidate_never_needed_a_comps_batch(tmp_path):
    candidate = _candidate(1)
    key = candidate["listing_key"]
    _write(tmp_path / "shopgoodwill.json", _source([candidate]))
    _write(tmp_path / "shopgoodwill.appraisal-1.json", [_appraisal(key, listing_category="bulk")])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    assert manifest["complete"] is True
    assert manifest["sources"][0]["appraisal_batches"][0]["comps_count"] is None


def test_comps_batch_key_mismatch_fails_the_whole_batch(tmp_path):
    candidate = _candidate(1)
    key = candidate["listing_key"]
    _write(tmp_path / "shopgoodwill.json", _source([candidate]))
    _write(tmp_path / "shopgoodwill.appraisal-1.json", [_appraisal(key)])
    _write(tmp_path / "shopgoodwill.comps-1.json", [_comps("shopgoodwill|wrong-key")])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    assert manifest["complete"] is False
    batch = manifest["sources"][0]["appraisal_batches"][0]
    assert "comps batch key mismatch" in batch["error"]


def test_comps_result_missing_sets_key_is_rejected(tmp_path):
    """A malformed comps shape is a per-candidate defect, not a batch-wide
    one: it surfaces as this candidate's own build_errors entry (so any
    OTHER candidate in the same batch still builds), not a batch-level
    error -- key coverage is still checked batch-wide; shape is not."""
    candidate = _candidate(1)
    key = candidate["listing_key"]
    _write(tmp_path / "shopgoodwill.json", _source([candidate]))
    _write(tmp_path / "shopgoodwill.appraisal-1.json", [_appraisal(key)])
    _write(tmp_path / "shopgoodwill.comps-1.json", [{"listing_key": key, "mode": "set"}])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    assert manifest["complete"] is False
    batch = manifest["sources"][0]["appraisal_batches"][0]
    assert batch["buildable_count"] == 0
    assert "'sets' is" in batch["build_errors"][0]["error"]


def test_bulk_comps_result_missing_bricklink_or_ebay_key_is_rejected(tmp_path):
    candidate = _candidate(1)
    key = candidate["listing_key"]
    _write(tmp_path / "shopgoodwill.json", _source([candidate]))
    _write(tmp_path / "shopgoodwill.appraisal-1.json", [_appraisal(key, listing_category="bulk")])
    _write(tmp_path / "shopgoodwill.comps-1.json",
          [{"listing_key": key, "mode": "bulk", "bricklink": None}])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    assert manifest["complete"] is False
    batch = manifest["sources"][0]["appraisal_batches"][0]
    assert batch["buildable_count"] == 0
    assert "missing ebay" in batch["build_errors"][0]["error"]


def test_one_malformed_comps_entry_does_not_block_a_sibling_candidate(tmp_path):
    """The bug a 2026-08-20 chaos review found: a single malformed comps
    shape used to fail validate_comps_batch for the WHOLE batch before the
    per-candidate build loop ever ran. Two candidates, one with a
    well-formed comps result and one malformed -- the good one must still
    build."""
    good = _candidate(1)
    bad = _candidate(2)
    good_key, bad_key = good["listing_key"], bad["listing_key"]
    _write(tmp_path / "shopgoodwill.json", _source([good, bad]))
    _write(tmp_path / "shopgoodwill.appraisal-1.json",
          [_appraisal(good_key), _appraisal(bad_key)])
    _write(tmp_path / "shopgoodwill.comps-1.json",
          [_comps(good_key), {"listing_key": bad_key, "mode": "set"}])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    batch = manifest["sources"][0]["appraisal_batches"][0]
    assert batch["buildable_count"] == 1
    assert len(batch["build_errors"]) == 1
    assert batch["build_errors"][0]["listing_key"] == bad_key


def test_comps_mode_mismatched_with_listing_category_is_rejected(tmp_path):
    """A bulk-shaped comps result handed to a SET candidate (or the
    reverse) previously passed validation cleanly and silently no-opped in
    _apply_comps instead of raising -- writing a wrong ebay_avg_sold_price
    onto a SET record with profit_incomplete left unset."""
    candidate = _candidate(1)
    key = candidate["listing_key"]
    _write(tmp_path / "shopgoodwill.json", _source([candidate]))
    _write(tmp_path / "shopgoodwill.appraisal-1.json", [_appraisal(key, listing_category="set")])
    _write(tmp_path / "shopgoodwill.comps-1.json",
          [{"listing_key": key, "mode": "bulk", "bricklink": None,
            "ebay": {"available": True, "avg_sold_price": 40.0}}])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    batch = manifest["sources"][0]["appraisal_batches"][0]
    assert batch["buildable_count"] == 0
    assert "listing_category" in batch["build_errors"][0]["error"]


def test_multi_set_comps_result_builds(tmp_path):
    candidate = _candidate(1)
    key = candidate["listing_key"]
    summary = {"condition": "U", "guide_type": "sold",
              "sold_window": "bricklink_sold_guide_last_6_months",
              "six_month_avg_sold_price": 500.0, "avg_price": 500.0, "price_detail_count": 10}

    def _entry(set_no):
        return {"set_no": set_no,
               "bricklink": {"set_no": set_no, "lookup_status": "found",
                             "catalog": {"no": set_no, "name": "Fixture Set"},
                             "condition": "U", "purchase_price": None, "fee_rate": None,
                             "used": summary, "new": None,
                             "selected_condition_summary": summary,
                             "selected_condition_priced": True, "potential_profit": None},
               "ebay": {"available": False, "reason": "ebay_auth_required"}}

    _write(tmp_path / "shopgoodwill.json", _source([candidate]))
    _write(tmp_path / "shopgoodwill.appraisal-1.json", [_appraisal(key)])
    _write(tmp_path / "shopgoodwill.comps-1.json",
          [{"listing_key": key, "mode": "set", "sets": [_entry("75192-1"), _entry("6868-1")]}])

    manifest = build_run_manifest(str(tmp_path), active_sources=["shopgoodwill"])

    assert manifest["complete"] is True
    assert manifest["sources"][0]["appraisal_batches"][0]["buildable_count"] == 1
