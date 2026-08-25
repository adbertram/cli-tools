"""The three-plus-one classification universe: bulk, set, minifigure, excluded.

Every downstream layer reads the classifier's `listing_category`, so a new tag
must be accepted end to end -- comps dispatch, comps-result validation, record
building, scoring, and validation -- and an `excluded` tag must always build as
`status: rejected` with a reason, never as an active deal.
"""
from __future__ import annotations

import pytest

from legoscout_cli.ledger import build_record
from legoscout_cli.ledger import db as ledger_db
from legoscout_cli.ledger import validate as ledger_validate
from legoscout_cli.orchestrator import (
    _is_classifier_exclusion,
    synthesis_coverage,
    validate_comps_result,
)
from legoscout_cli.pricing import comps, comps_batch, ebay_comps
from legoscout_cli.scoring import score


# ---------------------------------------------------------------------------
# eBay minifigure comps
# ---------------------------------------------------------------------------


def test_minifig_count_parses_stated_forms():
    assert ebay_comps._minifig_count("LEGO Star Wars Minifigure Lot of 20") == 20
    assert ebay_comps._minifig_count("20x Minifigs Lego Lot") == 20
    assert ebay_comps._minifig_count("25 Minifigures Bundle") == 25
    assert ebay_comps._minifig_count("Boba Fett minifigure sw0711") == 1
    assert ebay_comps._minifig_count("LEGO minifigure lot") is None
    assert ebay_comps._minifig_count("lego minifigure set") is None


def test_search_minifigure_comps_prices_per_figure(monkeypatch):
    raw = [
        {"title": "LEGO Star Wars Minifigure Lot of 10", "price": "$50.00",
         "item_id": "1", "url": "http://x/1"},
        {"title": "LEGO 5 Minifigs", "price": "$20.00", "item_id": "2",
         "url": "http://x/2"},
        {"title": "LEGO minifigure lot", "price": "$30.00", "item_id": "3",
         "url": "http://x/3"},  # no stated count: excluded
    ]

    result = ebay_comps.search_minifigure_comps("star wars", runner=lambda args: raw)

    assert result["available"] is True
    assert result["matched_count"] == 2
    assert result["excluded_reasons"] == ["no parseable figure count"]
    # $5.00/fig and $4.00/fig -> $4.50/fig
    assert result["avg_price_per_fig"] == 4.5


def test_search_minifigure_comps_unavailable_on_auth_lapse(monkeypatch):
    def raise_auth(args):
        raise ebay_comps.LookupFailed("ebay browser session not authenticated")

    result = ebay_comps.search_minifigure_comps("star wars", runner=raise_auth)

    assert result["available"] is False
    assert result["reason"] == "ebay_auth_required"
    assert result["avg_price_per_fig"] is None


def test_minifigure_comps_mode_shape(monkeypatch):
    monkeypatch.setattr(ebay_comps, "search_minifigure_comps",
                        lambda description, limit=50:
                        {"available": True, "avg_price_per_fig": 3.0})

    result = comps.minifigure_comps("star wars lot")

    assert result["mode"] == "minifigure"
    assert result["bricklink"] is None
    assert result["ebay"]["avg_price_per_fig"] == 3.0


def test_excluded_comps_is_a_blocked_result():
    result = comps.excluded_comps("LEGO storage head -- no pieces")

    assert result["mode"] == "excluded"
    assert result["blocked"] is True
    assert result["blocker"] == "LEGO storage head -- no pieces"


# ---------------------------------------------------------------------------
# Batch dispatch
# ---------------------------------------------------------------------------


def test_price_one_dispatches_minifigure(monkeypatch):
    monkeypatch.setattr(comps_batch.comps_module, "minifigure_comps",
                        lambda description, limit=50:
                        {"mode": "minifigure", "bricklink": None,
                         "ebay": {"available": True}})

    result = comps_batch.price_one(
        {"listing_key": "ebay|1", "listing_category": "minifigure",
         "description": "star wars"}, limit=50)

    assert result["mode"] == "minifigure"
    assert result["listing_key"] == "ebay|1"


def test_price_one_minifigure_requires_description():
    result = comps_batch.price_one(
        {"listing_key": "ebay|1", "listing_category": "minifigure"}, limit=50)

    assert result["blocked"] is True
    assert "description" in result["blocker"]


def test_price_one_dispatches_excluded_with_reason():
    result = comps_batch.price_one(
        {"listing_key": "ebay|1", "listing_category": "excluded",
         "exclusion_reason": "LEGO book -- no pieces"}, limit=50)

    assert result["blocked"] is True
    assert result["blocker"] == "LEGO book -- no pieces"


def test_price_one_excluded_without_reason_is_blocked_with_that_defect():
    result = comps_batch.price_one(
        {"listing_key": "ebay|1", "listing_category": "excluded"}, limit=50)

    assert result["blocked"] is True
    assert "no exclusion_reason" in result["blocker"]


# ---------------------------------------------------------------------------
# Comps-result validation
# ---------------------------------------------------------------------------


def test_validate_comps_result_accepts_minifigure_mode():
    validate_comps_result(
        {"listing_key": "ebay|1", "mode": "minifigure",
         "bricklink": None, "ebay": {"available": True, "avg_price_per_fig": 4.0}},
        "minifigure result")


def test_validate_comps_result_rejects_minifigure_without_both_keys():
    with pytest.raises(Exception, match="missing bricklink"):
        validate_comps_result(
            {"listing_key": "ebay|1", "mode": "minifigure", "ebay": {}},
            "minifigure result")


def test_validate_comps_result_blocked_excluded_is_exempt_from_mode_check():
    # An excluded candidate's comps result is blocked: true -- no mode shape to
    # cross-check, same exemption the unpriceable-set path already has.
    validate_comps_result(
        {"listing_key": "ebay|1", "mode": "excluded", "blocked": True,
         "blocker": "LEGO book -- no pieces"},
        "excluded result", expected_category="excluded")


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------


def _candidate(key="ebay|1", **over):
    base = {
        "listing_key": key,
        "title": "test lot",
        "url": "https://example.com/lot",
        "direct_url": "https://example.com/lot",
        "buy_now_price": 40.0,
        "price_basis": "buy_now",
        "listing_type": "fixed",
        "available_fulfillment": ["shipping"],
        "item_location": "Evansville, IN",
        "weight_lbs": 5.0,
        "seller_id": "s1",
        "seller_name": "seller",
        "image_urls": [],
        "first_seen_at": "2026-08-01T00:00:00Z",
        "last_seen_at": "2026-08-01T00:00:00Z",
    }
    base.update(over)
    return base


def _appraisal(category, **over):
    base = {
        "listing_key": "ebay|1",
        "listing_category": category,
        "title": "test lot",
        "available_fulfillment": ["shipping"],
        "fee_breakdown": {
            "hammer": 40.0,
            "premium_pct": 0.0,
            "sales_tax_pct": 0.0,
            "shipping_handling": 0.0,
        },
        "weight_lbs": 5.0,
        "set_completeness": "unknown",
        "set_condition": "unknown",
        "cost_per_lb_note": "unknown",
        "per_lb_price_basis": "unknown",
        "zero_comp_note": "unknown",
        "observations": {
            "vision": {"status": "not_observed"},
            "description": "test",
            "model_score": 50,
            "model_rationale": "test",
        },
        "estimated_total": 40.0,
    }
    base.update(over)
    return base


def test_build_excluded_record_as_active_raises():
    with pytest.raises(ValueError, match="classified as excluded"):
        build_record.build_deal_record(
            _candidate(), _appraisal("excluded",
                                     exclusion_reason="LEGO book -- no pieces"),
            first_seen_at="2026-08-01T00:00:00Z",
            last_seen_at="2026-08-01T00:00:00Z",
            status="active")


def test_build_excluded_record_as_rejected_carries_reason():
    record = build_record.build_deal_record(
        _candidate(), _appraisal("excluded",
                                 exclusion_reason="LEGO book -- no pieces"),
        first_seen_at="2026-08-01T00:00:00Z",
        last_seen_at="2026-08-01T00:00:00Z",
        status="rejected")

    assert record["status"] == "rejected"
    assert record["listing_category"] == "excluded"
    assert "LEGO book" in record["notes"]
    assert record["score"] is None


def test_build_minifigure_record_prices_profit():
    comps_result = {
        "listing_key": "ebay|1", "mode": "minifigure", "bricklink": None,
        "ebay": {"available": True, "avg_price_per_fig": 5.0,
                 "avg_sold_price": 100.0, "matched_count": 8},
    }
    record = build_record.build_deal_record(
        _candidate(),
        _appraisal("minifigure", figure_count=20,
                   figure_count_source="stated"),
        first_seen_at="2026-08-01T00:00:00Z",
        last_seen_at="2026-08-01T00:00:00Z",
        comps=comps_result, fee_rate=0.13,
        status="active")

    # resale = 20 figs x $5 = $100; profit = 100*(1-0.13) - 40 = 47.0
    assert record["potential_profit"] == 47.0
    assert record["ebay_avg_price_per_fig"] == 5.0
    assert record["figure_count_source"] == "stated"
    assert record["scoring"]["category"] == "minifigure"
    assert record["score"] is not None


def test_build_minifigure_record_rejects_a_count_without_provenance():
    """A bare figure_count is exactly how an invented number reaches the money.

    `figure_count` without `figure_count_source` violates the ledger contract
    and the build refuses to persist it.
    """
    comps_result = {
        "listing_key": "ebay|1", "mode": "minifigure", "bricklink": None,
        "ebay": {"available": True, "avg_price_per_fig": 5.0,
                 "avg_sold_price": 100.0, "matched_count": 8},
    }
    with pytest.raises(ValueError, match="figure_count_source"):
        build_record.build_deal_record(
            _candidate(), _appraisal("minifigure", figure_count=20),
            first_seen_at="2026-08-01T00:00:00Z",
            last_seen_at="2026-08-01T00:00:00Z",
            comps=comps_result, fee_rate=0.13,
            status="active")


def test_build_minifigure_record_without_figure_count_stays_unpriced():
    comps_result = {
        "listing_key": "ebay|1", "mode": "minifigure", "bricklink": None,
        "ebay": {"available": True, "avg_price_per_fig": 5.0,
                 "avg_sold_price": 100.0, "matched_count": 8},
    }
    record = build_record.build_deal_record(
        _candidate(), _appraisal("minifigure"),
        first_seen_at="2026-08-01T00:00:00Z",
        last_seen_at="2026-08-01T00:00:00Z",
        comps=comps_result, fee_rate=0.13,
        status="active")

    assert record["potential_profit"] is None
    assert record["profit_incomplete"] is True
    assert "figure_count" in record["zero_comp_note"]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_score_record_accepts_minifigure():
    record = {
        "listing_key": "ebay|1", "listing_category": "minifigure",
        "figure_count": 20, "estimated_total": 40.0,
        "potential_profit": 47.0, "ebay_comp_count": 8,
        "observations": {}, "title": "star wars minifig lot",
    }
    result = score.score_record(record)

    assert result["scoring"]["category"] == "minifigure"
    assert result["scoring"]["score"] is not None
    assert result["scoring"]["max_price"] is not None


def test_score_record_excluded_is_unscorable_with_reason():
    record = {
        "listing_key": "ebay|1", "listing_category": "excluded",
        "exclusion_reason": "LEGO book -- no pieces",
        "observations": {}, "title": "book",
    }
    result = score.score_record(record)

    assert result["scoring"]["score"] is None
    assert "excluded at classification" in result["scoring"]["unscorable"]
    assert "LEGO book" in result["scoring"]["unscorable"]


def test_score_record_still_rejects_unknown_categories():
    record = {
        "listing_key": "ebay|1", "listing_category": "clothing",
        "observations": {}, "title": "shirt",
    }
    with pytest.raises(ValueError, match="listing_category"):
        score.score_record(record)


# ---------------------------------------------------------------------------
# Validation gates
# ---------------------------------------------------------------------------


def test_validate_excluded_requires_rejected_and_reason():
    _, errors, _ = ledger_validate.check({
        "listing_key": "ebay|1", "listing_category": "excluded",
        "exclusion_reason": "", "status": "active",
        "listing_type": "fixed", "price_basis": "buy_now",
        "buy_now_price": 10.0,
        "available_fulfillment": ["shipping"],
    })
    joined = "\n".join(errors)
    assert "status" in joined
    assert "exclusion_reason" in joined


def test_validate_rejects_unknown_category():
    _, errors, _ = ledger_validate.check({
        "listing_key": "ebay|1", "listing_category": "clothing",
        "listing_type": "fixed", "price_basis": "buy_now",
        "buy_now_price": 10.0,
        "available_fulfillment": ["shipping"],
    })
    assert any("listing_category" in e for e in errors)


# ---------------------------------------------------------------------------
# Synthesis coverage
# ---------------------------------------------------------------------------


def test_synthesis_coverage_accepts_excluded_pair_as_gate_rejected():
    report = synthesis_coverage(
        [_candidate()],
        [_appraisal("excluded", exclusion_reason="LEGO book -- no pieces")],
        comps_results=[{"listing_key": "ebay|1", "mode": "excluded",
                        "blocked": True, "blocker": "LEGO book -- no pieces"}],
        fee_rate=0.13,
    )

    assert report["complete"] is True
    assert report["buildable_count"] == 1
    assert report["gate_rejected_count"] == 1
    assert report["build_errors"] == []


def test_is_classifier_exclusion_matches_the_gate_message():
    assert _is_classifier_exclusion(
        ValueError("classified as excluded: 'LEGO book' -- ..."))
    assert not _is_classifier_exclusion(ValueError("some other error"))


# ---------------------------------------------------------------------------
# Storage affinity
# ---------------------------------------------------------------------------


def test_minifigure_numeric_columns_round_trip_integers(tmp_path):
    # figure_count and ebay_avg_price_per_fig are numeric columns; a TEXT-affinity
    # column stores integer 20 as '20' and the display row reads figCount: None
    # (isinstance(int) fails on the string). They must be in db._NUMERIC so they
    # get BLOB affinity and round-trip their storage class verbatim.
    path = str(tmp_path / "found_deals.db")
    ledger_db.init(path).close()

    deal = {
        "listing_key": "ebay|fig1", "source": "ebay",
        "title": "minifig lot", "url": "https://example.invalid/fig1",
        "buy_now_price": 40.0, "price_basis": "buy_now",
        "listing_category": "minifigure",
        "figure_count": 20,
        "ebay_avg_price_per_fig": 5.0,
        "status": "active",
    }
    ledger_db.upsert_deals([deal], path=path)
    loaded = ledger_db.get_deal("ebay|fig1", path=path)

    assert isinstance(loaded["figure_count"], int), repr(loaded["figure_count"])
    assert loaded["figure_count"] == 20
    assert isinstance(loaded["ebay_avg_price_per_fig"], float)
    assert loaded["ebay_avg_price_per_fig"] == 5.0
