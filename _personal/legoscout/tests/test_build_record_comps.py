"""`build_deal_record`'s comps merge: the one place a classifier's landed cost
and an appraiser's comps result become `potential_profit`, not a hand-merge
anywhere else. Covers single-set, multi-set (allocated cost, summed comps),
and bulk."""
from __future__ import annotations

import pytest

from legoscout_cli.ledger import build_record


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


def _appraisal(key, listing_category, **changes):
    record = {
        "listing_key": key,
        "observations": {
            "model_score": 50,
            "model_rationale": "The fixture has neutral deal evidence.",
        },
        "listing_category": listing_category,
        "estimated_total": 300.0,
    }
    record.update(changes)
    return record


def _summary(condition, avg_price, count):
    return {
        "condition": condition, "guide_type": "sold",
        "sold_window": "bricklink_sold_guide_last_6_months",
        "six_month_avg_sold_price": avg_price, "avg_price": avg_price,
        "price_detail_count": count,
    }


def _bricklink_found(set_no="75192-1", condition="U", avg_price=500.0, count=10):
    summary = _summary(condition, avg_price, count)
    return {
        "set_no": set_no, "lookup_status": "found",
        "catalog": {"no": set_no, "name": "Millennium Falcon"},
        "condition": condition, "purchase_price": None, "fee_rate": None,
        "used": summary if condition == "U" else None,
        "new": summary if condition == "N" else None,
        "selected_condition_summary": summary,
        "selected_condition_priced": True, "potential_profit": None,
    }


def _bricklink_not_found(set_no):
    return {
        "set_no": set_no, "lookup_status": "not_found", "catalog": None,
        "condition": "U", "purchase_price": None, "fee_rate": None,
        "used": None, "new": None, "selected_condition_summary": None,
        "potential_profit": None,
        "error": {"source": "bricklink catalog lookup", "message": "RESOURCE_NOT_FOUND"},
    }


_EBAY_UNAVAILABLE = {"available": False, "reason": "ebay_auth_required"}


def _one_set(set_no="75192-1", avg_price=500.0, count=10, condition="U", ebay=None):
    return {"set_no": set_no,
           "bricklink": _bricklink_found(set_no, condition, avg_price, count),
           "ebay": ebay or dict(_EBAY_UNAVAILABLE)}


def _set_comps(*set_entries):
    """Mirrors `comps.py`'s real `set_comps()` output shape: no top-level
    `ebay` key for set mode -- each `sets[]` entry carries its own."""
    return {"mode": "set", "condition": "U", "sets": list(set_entries)}


def _build(key, listing_category, comps=None, fee_rate=None, **appraisal_changes):
    return build_record.build_deal_record(
        _record(key), _appraisal(key, listing_category, **appraisal_changes),
        first_seen_at="2026-08-20T00:00:00Z", last_seen_at="2026-08-20T00:00:00Z",
        comps=comps, fee_rate=fee_rate)


# --- bulk -------------------------------------------------------------------

def test_bulk_candidate_with_no_comps_does_not_raise():
    rec = _build("ebay|1", "bulk")
    assert rec["ebay_avg_sold_price"] is None


def test_bulk_candidate_folds_in_ebay_informational_fields():
    comps = {"mode": "bulk", "bricklink": None,
             "ebay": {"available": True, "avg_sold_price": 40.0,
                      "matched_count": 6, "avg_price_per_lb": 4.5}}

    rec = _build("ebay|1", "bulk", comps=comps)

    assert rec["ebay_avg_sold_price"] == 40.0
    assert rec["ebay_comp_count"] == 6
    assert rec["ebay_avg_price_per_lb"] == 4.5
    # Bulk never feeds eBay into potential_profit -- Decision A.
    assert rec["potential_profit"] is None


# --- single set (sets: [one entry]) ------------------------------------------

def test_set_candidate_with_no_comps_raises():
    with pytest.raises(ValueError, match="ebay\\|1.*SET candidate with no comps"):
        _build("ebay|1", "set", comps=None)


def test_set_candidate_with_blocked_comps_stays_unpriced_not_raised():
    # legoscout-classifier omits `set_numbers` entirely when text and vision
    # both exhaust with no set number ever identified; legoscout-appraiser
    # then writes a `blocked: true` comps result rather than calling
    # `legoscout pricing comps` with zero --set-no. This is a real,
    # scoreable "stays unpriced" outcome, not the defect `comps=None` raises
    # on above.
    comps = {"mode": "set", "blocked": True, "blocker": "no set # in listing"}

    rec = _build("ebay|1", "set", comps=comps)

    assert rec["potential_profit"] is None
    assert rec["profit_incomplete"] is True
    assert rec["zero_comp_note"] == "no set # in listing"


def test_bulk_candidate_with_blocked_comps_stays_unpriced():
    comps = {"mode": "bulk", "blocked": True, "blocker": "eBay auth required, BrickLink N/A"}

    rec = _build("ebay|1", "bulk", comps=comps)

    assert rec["ebay_avg_sold_price"] is None
    assert rec["potential_profit"] is None


def test_single_set_computes_profit_from_bricklink_avg_and_landed_cost():
    comps = _set_comps(_one_set(avg_price=500.0, count=10))

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13)

    assert rec["used_avg_6mo"] == 500.0
    assert rec["new_avg_6mo"] is None
    assert rec["potential_profit"] == round(500.0 * 0.87 - 300.0, 2)
    assert rec["profit_incomplete"] is False
    assert rec["set_analysis"][0]["set_no"] == "75192-1"
    # set_analysis.purchase_price must equal the (single-set) allocated cost.
    assert rec["set_analysis"][0]["purchase_price"] == 300.0
    assert rec["set_analysis"][0]["fee_rate"] == 0.13


def test_single_set_blends_bricklink_and_ebay_by_comp_count():
    comps = _set_comps(_one_set(avg_price=500.0, count=10,
                                ebay={"available": True, "avg_sold_price": 540.0, "matched_count": 4}))

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13)

    assert rec["used_avg_6mo"] == 500.0          # unchanged: pure BrickLink lot sum
    assert rec["ebay_avg_sold_price"] == 540.0    # unchanged: pure eBay lot sum
    assert rec["ebay_comp_count"] == 4
    # potential_profit is now a comp-count-weighted blend, not BrickLink alone.
    blended_avg = round((500.0 * 10 + 540.0 * 4) / 14, 2)
    assert rec["set_analysis"][0]["blended_avg_sold_price"] == blended_avg
    assert "bricklink (10 sold)" in rec["set_analysis"][0]["comp_basis"]
    assert "ebay (4 sold)" in rec["set_analysis"][0]["comp_basis"]
    assert rec["potential_profit"] == round(blended_avg * 0.87 - 300.0, 2)
    assert rec["potential_profit"] == 144.94


def test_single_set_without_fee_rate_gets_comps_but_no_profit():
    """The synthesis_coverage dry-build path: proves the shape builds without
    needing the run's configured fee rate."""
    comps = _set_comps(_one_set(avg_price=500.0, count=10))

    rec = _build("ebay|1", "set", comps=comps, fee_rate=None)

    assert rec["used_avg_6mo"] == 500.0
    assert rec["potential_profit"] is None


def test_single_set_bricklink_not_found_keeps_entry_with_null_fields():
    comps = _set_comps({"set_no": "99999999-1", "bricklink": _bricklink_not_found("99999999-1"),
                        "ebay": dict(_EBAY_UNAVAILABLE)})

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13)

    assert len(rec["set_analysis"]) == 1
    entry = rec["set_analysis"][0]
    assert entry["set_no"] == "99999999-1"
    assert entry["lookup_status"] == "not_found"
    assert entry["potential_profit"] is None
    assert rec["used_avg_6mo"] is None
    assert rec["potential_profit"] is None
    assert rec["profit_incomplete"] is True


def test_single_set_zero_avg_with_backing_listings_is_a_real_priced_zero():
    """A real $0 sold average, BACKED by actual sold listings -- distinct from
    the zero-in-both-conditions "no evidence at all" case below."""
    comps = _set_comps(_one_set(avg_price=0.0, count=3))

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13)

    assert rec["potential_profit"] == -300.0
    assert rec["profit_incomplete"] is False


def test_incomplete_set_gets_comps_for_reference_but_never_a_profit_number():
    """BrickLink prices a COMPLETE set -- an incomplete listing's comps are
    shown for reference only. `potential_profit` must stay null even though
    real comps and a real landed cost are both in hand."""
    comps = _set_comps(_one_set(avg_price=500.0, count=10))

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13, set_completeness="incomplete")

    assert rec["used_avg_6mo"] == 500.0
    assert rec["potential_profit"] is None
    assert rec["profit_incomplete"] is True
    assert rec["set_analysis"][0]["potential_profit"] is None


def test_zero_comps_in_both_conditions_is_a_real_loss_not_left_unpriced():
    """BrickLink confirms the set exists but has NO sold comps in either
    condition -- legoscout-pricing's <pricing_basis> rule: price resale at $0
    (a real, scoreable loss) rather than leaving potential_profit null."""
    bricklink = {
        "set_no": "75192-1", "lookup_status": "found",
        "catalog": {"no": "75192-1", "name": "Millennium Falcon"},
        "condition": "U", "purchase_price": None, "fee_rate": None,
        "used": _summary("U", None, 0), "new": _summary("N", None, 0),
        "selected_condition_summary": _summary("U", None, 0),
        "selected_condition_priced": False, "potential_profit": None,
    }
    comps = _set_comps({"set_no": "75192-1", "bricklink": bricklink, "ebay": dict(_EBAY_UNAVAILABLE)})

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13)

    assert rec["potential_profit"] == -300.0
    assert rec["profit_incomplete"] is True
    assert "zero sold comps in both conditions" in rec["zero_comp_note"]


def test_zero_comps_in_selected_condition_only_stays_unpriced_not_a_loss():
    """Only ONE condition is empty -- the other has real comps, just not the
    one this listing's condition selected. Must NOT get the $0-loss treatment."""
    bricklink = {
        "set_no": "75192-1", "lookup_status": "found",
        "catalog": {"no": "75192-1", "name": "Millennium Falcon"},
        "condition": "U", "purchase_price": None, "fee_rate": None,
        "used": _summary("U", None, 0), "new": _summary("N", 700.0, 12),
        "selected_condition_summary": _summary("U", None, 0),
        "selected_condition_priced": False, "potential_profit": None,
    }
    comps = _set_comps({"set_no": "75192-1", "bricklink": bricklink, "ebay": dict(_EBAY_UNAVAILABLE)})

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13)

    assert rec["potential_profit"] is None
    assert rec["profit_incomplete"] is True
    # zero_comp_note is a non-nullable schema string -- "unknown" is its unset
    # default, not None; _apply_comps only sets a real note for the
    # zero-in-BOTH-conditions case.
    assert rec["zero_comp_note"] == "unknown"


def test_bricklink_zero_in_both_but_ebay_has_comps_prices_off_ebay_not_zero():
    """The bug fix: BrickLink confirms the set but has zero sold comps in
    EITHER condition (its own no-sales shape); eBay has real comps and prices
    the set alone, rather than the old behavior of forcing a fabricated $0
    loss just because BrickLink alone had nothing."""
    bricklink = {
        "set_no": "75192-1", "lookup_status": "found",
        "catalog": {"no": "75192-1", "name": "Millennium Falcon"},
        "condition": "U", "purchase_price": None, "fee_rate": None,
        "used": _summary("U", None, 0), "new": _summary("N", None, 0),
        "selected_condition_summary": _summary("U", None, 0),
        "selected_condition_priced": False, "potential_profit": None,
    }
    ebay = {"available": True, "avg_sold_price": 45.0, "matched_count": 6}
    comps = _set_comps({"set_no": "75192-1", "bricklink": bricklink, "ebay": ebay})

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13)

    assert rec["set_analysis"][0]["blended_avg_sold_price"] == 45.0
    assert rec["potential_profit"] == round(45.0 * 0.87 - 300.0, 2)
    assert rec["profit_incomplete"] is False   # priced normally, not the $0-loss branch
    assert "ebay" in rec["set_analysis"][0]["comp_basis"]


# --- multi-set listing --------------------------------------------------------

def test_multi_set_allocates_landed_cost_evenly_and_sums_profit():
    comps = _set_comps(
        _one_set(set_no="75192-1", avg_price=500.0, count=10),
        _one_set(set_no="6868-1", avg_price=200.0, count=5),
    )

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13)

    # estimated_total=300 split evenly across 2 sets -> $150 each.
    expected = round((500.0 * 0.87 - 150.0) + (200.0 * 0.87 - 150.0), 2)
    assert rec["potential_profit"] == expected
    assert rec["profit_incomplete"] is False
    assert rec["used_avg_6mo"] == 700.0  # summed across both sets
    assert len(rec["set_analysis"]) == 2
    assert {e["purchase_price"] for e in rec["set_analysis"]} == {150.0}


def test_multi_set_one_unfound_set_does_not_block_the_others():
    comps = _set_comps(
        {"set_no": "99999999-1", "bricklink": _bricklink_not_found("99999999-1"),
         "ebay": dict(_EBAY_UNAVAILABLE)},
        _one_set(set_no="75192-1", avg_price=500.0, count=10),
    )

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13)

    assert len(rec["set_analysis"]) == 2
    by_no = {e["set_no"]: e for e in rec["set_analysis"]}
    assert by_no["99999999-1"]["lookup_status"] == "not_found"
    assert by_no["99999999-1"]["potential_profit"] is None
    # Allocated cost still splits by the full detected-set count (2), not 1.
    assert by_no["75192-1"]["purchase_price"] == 150.0
    assert by_no["75192-1"]["potential_profit"] == round(500.0 * 0.87 - 150.0, 2)
    # Only the priced set's profit is summed; the lot is marked incomplete.
    assert rec["potential_profit"] == round(500.0 * 0.87 - 150.0, 2)
    assert rec["profit_incomplete"] is True


def test_multi_set_ebay_sums_across_sets():
    comps = _set_comps(
        _one_set(set_no="75192-1", avg_price=500.0, count=10,
                 ebay={"available": True, "avg_sold_price": 520.0, "matched_count": 3}),
        _one_set(set_no="6868-1", avg_price=200.0, count=5,
                 ebay={"available": True, "avg_sold_price": 210.0, "matched_count": 2}),
    )

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13)

    assert rec["ebay_avg_sold_price"] == 730.0
    assert rec["ebay_comp_count"] == 5


def test_multi_set_incomplete_never_gets_a_profit_number():
    comps = _set_comps(
        _one_set(set_no="75192-1", avg_price=500.0, count=10),
        _one_set(set_no="6868-1", avg_price=200.0, count=5),
    )

    rec = _build("ebay|1", "set", comps=comps, fee_rate=0.13, set_completeness="incomplete")

    assert rec["potential_profit"] is None
    assert rec["profit_incomplete"] is True
    assert all(e["potential_profit"] is None for e in rec["set_analysis"])
