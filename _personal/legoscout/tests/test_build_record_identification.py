from __future__ import annotations

import copy

import pytest

from legoscout_cli.ledger import build_record
from legoscout_cli.ledger import minifig_analysis as mfa
from legoscout_cli.scoring import score


def _candidate(key="k-bid|1"):
    return {
        "listing_key": key,
        "source": "k-bid",
        "title": "Star Wars minifigure lot",
        "url": "https://example.invalid/1",
        "direct_url": "https://example.invalid/1",
        "current_price": 40.0,
        "price_basis": "current_price",
        "listing_type": "fixed",
        "available_fulfillment": ["shipping"],
        "item_location": "Evansville, IN 47725",
        "seller_id": "seller",
        "seller_name": "Seller",
        "image_urls": [],
    }


def _appraisal(category="minifigure", key="k-bid|1"):
    return {
        "listing_key": key,
        "listing_category": category,
        "estimated_total": 40.0,
        "figure_count": 99 if category == "minifigure" else None,
        "figure_count_source": (
            "stated" if category == "minifigure" else None),
        "fee_breakdown": {
            "hammer": 40.0,
            "premium_pct": 0.0,
            "sales_tax_pct": 0.0,
            "shipping_handling": 0.0,
        },
        "observations": {
            "vision": {
                "stated_figure_count": 99,
                "photo_figure_count": 98,
                "status": "observed",
            },
            "description": "seller says 99 figures",
            "model_score": 50,
            "model_rationale": "fixture",
        },
    }


def _detection(crop_id):
    return {
        "crop_id": crop_id,
        "source_photo_sha256": "a" * 64,
        "photo_relative_id": "photo-0001",
        "box": [.1, .1, .4, .8],
        "detector_name": "grounding-dino-tiny",
        "detector_version": "v1",
        "detector_confidence": .9,
        "crop_ref": f"aa/{crop_id}.jpg",
    }


def _entry(
    group_id,
    *,
    quantity=1,
    unit: float | None = 10.0,
    status="verified",
    sold_count=5,
    error=None,
    null_reason=None,
):
    verified = status == "verified"
    fig_no = f"sw{group_id[-1]}" if verified else None
    if not verified:
        unit = None
    extended = round(unit * quantity, 2) if unit is not None else None
    if null_reason is None and not verified:
        null_reason = "unknown_identity" if status == "unknown" else "unverifiable"
    return {
        "match_group_id": group_id,
        "detections": [_detection("figcrop-v1-" + group_id)],
        "representative_crop_ref": f"aa/figcrop-v1-{group_id}.jpg",
        "brickognize_candidates": [],
        "verification": {
            "status": status,
            "reason": "fixture",
            "compared_candidate_ids": [fig_no] if fig_no else [],
            "catalog_checked_at": "2026-08-25T00:00:00Z",
        },
        "fig_no": fig_no,
        "catalog": {"no": fig_no, "name": fig_no} if fig_no else None,
        "quantity": quantity,
        "condition_notes": None,
        "used": ({
            "avg_price": unit,
            "price_detail_count": sold_count,
        } if verified and unit is not None else None),
        "unit_value": unit,
        "extended_value": extended,
        "null_value_reason": null_reason,
        "errors": [error] if error else [],
    }


def _identification(entries, key="k-bid|1", blocked=False):
    if blocked:
        return {
            "listing_key": key,
            "blocked": True,
            "blocker": "no usable figure groups",
            "minifig_analysis": None,
            "figure_count": None,
            "figure_count_source": None,
            "identified_count": 0,
            "unknown_count": 0,
            "priced_subtotal": 0.0,
            "sold_count": None,
            "pricing_complete": False,
            "status": "blocked",
        }
    figure_count = mfa.figure_count(entries)
    unknown_count = sum(entry["quantity"] for entry in entries
                        if entry["verification"]["status"] != "verified")
    complete = unknown_count == 0 and all(
        entry["unit_value"] is not None and not entry["errors"]
        for entry in entries)
    return {
        "listing_key": key,
        "minifig_analysis": entries,
        "figure_count": figure_count,
        "figure_count_source": "detection",
        "identified_count": sum(
            entry["quantity"] for entry in entries
            if entry["verification"]["status"] == "verified"),
        "unknown_count": unknown_count,
        "priced_subtotal": mfa.priced_subtotal(entries),
        "sold_count": mfa.sold_count(entries),
        "pricing_complete": complete,
        "status": "success" if complete else "partial",
    }


def _build(
    identification,
    *,
    category="minifigure",
    fee_rate: float | None = .13,
    comps=None,
):
    return build_record.build_deal_record(
        _candidate(),
        _appraisal(category),
        first_seen_at="2026-08-25T00:00:00Z",
        last_seen_at="2026-08-25T00:00:00Z",
        identification=identification,
        comps=comps,
        fee_rate=fee_rate,
    )


def test_should_require_identification_for_new_minifigure_and_validate_kwarg():
    with pytest.raises(ValueError, match="no identification result"):
        _build(None)
    with pytest.raises((TypeError, ValueError), match="identification"):
        _build("bad")
    with pytest.raises(ValueError, match="listing_key"):
        _build(_identification([_entry("g1")], key="other|1"))
    with pytest.raises(ValueError, match="blocked"):
        _build(_identification([], blocked=True))


def test_should_forbid_identification_on_non_minifigure_rows():
    with pytest.raises(ValueError, match="non-minifigure"):
        _build(_identification([_entry("g1")]), category="bulk")


def test_should_leave_non_minifigure_builds_without_identification_unchanged():
    record = _build(None, category="bulk", fee_rate=None)
    assert record["listing_category"] == "bulk"
    assert record.get("minifig_analysis") is None


def test_should_reject_retired_minifigure_comps_input():
    with pytest.raises(Exception, match="minifigure"):
        _build(
            _identification([_entry("g1")]),
            comps={
                "listing_key": "k-bid|1",
                "mode": "minifigure",
                "bricklink": None,
                "ebay": {"available": True},
            },
        )


def test_should_fold_before_type_checks_and_call_scorer_once(monkeypatch):
    entries = [_entry("g1", quantity=2, unit=20.0)]
    seen = []

    def fake_score(record, vision=None, is_favorite_seller=False):
        seen.append(copy.deepcopy(record))
        return {
            "scoring": {"score": 77, "category": "minifigure"},
            "observations": record["observations"],
        }

    monkeypatch.setattr(build_record.score_deal, "score_record", fake_score)
    record = _build(_identification(entries))

    assert len(seen) == 1
    at_score = seen[0]
    assert at_score["minifig_analysis"] == entries
    assert at_score["figure_count"] == 2
    assert at_score["figure_count_source"] == "detection"
    assert at_score["potential_profit"] == -5.2
    assert record["score"] == 77


def test_should_derive_detection_count_and_preserve_classifier_mismatch():
    entries = [_entry("g1", quantity=2), _entry("g2", quantity=3)]
    record = _build(_identification(entries))

    assert record["figure_count"] == 5
    assert record["figure_count_source"] == "detection"
    assert record["observations"]["vision"]["stated_figure_count"] == 99
    assert record["observations"]["vision"]["photo_figure_count"] == 98
    assert record["observations"]["vision"]["detection_figure_count"] == 5
    assert record["observations"]["vision"]["figure_count_mismatch"] == {
        "stated": 99,
        "photo": 98,
        "detection": 5,
    }


def test_should_compute_complete_profit_from_subtotal_fee_and_full_cost_once():
    entries = [_entry("g1", quantity=2, unit=30.0),
               _entry("g2", quantity=1, unit=40.0)]
    record = _build(_identification(entries), fee_rate=.13)

    assert record["minifig_analysis"] == entries
    assert record["potential_profit"] == 47.0
    assert record["profit_incomplete"] is False
    assert record["zero_comp_note"] == "unknown"
    assert record.get("ebay_avg_price_per_fig") is None
    assert record["scoring"]["category"] == "minifigure"
    assert record["score"] is not None


def test_should_keep_conservative_floor_but_make_partial_lot_unscorable():
    entries = [
        _entry("g1", quantity=2, unit=30.0),
        _entry("g2", quantity=1, status="unknown"),
    ]
    record = _build(_identification(entries), fee_rate=.13)

    assert record["potential_profit"] == 12.2
    assert record["profit_incomplete"] is True
    assert record["scoring"]["score"] is None
    assert "incomplete" in record["scoring"]["unscorable"]


def test_should_carry_mixed_pricing_failures_as_floor_and_unscorable():
    entries = [
        _entry("g1", unit=20.0),
        _entry("g2", unit=None, null_reason="zero_sales"),
        _entry("g3", unit=None, error="LookupNotFound: absent",
               null_reason="price_lookup_failed"),
        _entry("g4", unit=None, error="LookupFailed: timeout",
               null_reason="price_lookup_failed"),
    ]
    identification = _identification(entries)
    identification["pricing_complete"] = False
    identification["status"] = "partial"
    record = _build(identification, fee_rate=.13)

    assert record["potential_profit"] == -22.6
    assert record["profit_incomplete"] is True
    assert record["scoring"]["score"] is None
    assert len(record["minifig_analysis"]) == 4


def test_minifigure_score_uses_max_bricklink_depth_not_sum():
    entries = [_entry("g1", unit=80.0, sold_count=4),
               _entry("g2", unit=80.0, sold_count=31)]
    record = _build(_identification(entries), fee_rate=.13)
    assert record["scoring"]["signals"]["comp_depth"]["sales_6mo"] == 31


def test_score_minifigure_complete_and_incomplete_switch():
    complete = {
        "listing_key": "k-bid|1",
        "listing_category": "minifigure",
        "estimated_total": 40.0,
        "potential_profit": 47.0,
        "profit_incomplete": False,
        "figure_count": 2,
        "minifig_analysis": [_entry("g1", quantity=2, unit=50.0,
                                     sold_count=10)],
        "observations": {},
        "title": "star wars minifigures",
    }
    scored = score.score_record(complete)
    assert scored["scoring"]["score"] is not None
    assert scored["scoring"]["signals"]["comp_depth"]["sales_6mo"] == 10

    incomplete = copy.deepcopy(complete)
    incomplete["profit_incomplete"] = True
    blocked = score.score_record(incomplete)
    assert blocked["scoring"]["score"] is None
    assert "incomplete" in blocked["scoring"]["unscorable"]
