"""The classifier's description-price override: a listing's own text can
contradict the crawl price, and when it does, every downstream number must be
denominated in the stated ask -- never in the placeholder the text contradicts.

Born from facebook|1024732190360342: static_price $5, body "NOT 5 DOLLARS" and
five sealed sets priced $60/$35/$35/$30/$40 ($200). Priced off the phantom $5,
the row scored 100 with +$112.52 of fictional profit.
"""
from __future__ import annotations

import pytest

from legoscout_cli.ledger import build_record
from legoscout_cli.ledger import validate as ledger_validate


def _candidate(**changes):
    record = {
        "listing_key": "facebook|1024732190360342",
        "source": "facebook",
        "title": "New Star Wars Lego For Sale!!!",
        "url": "https://www.facebook.com/marketplace/item/1024732190360342/",
        "direct_url": "https://www.facebook.com/marketplace/item/1024732190360342/",
        "posted_date": "unknown",
        "auction_start_date": "not-an-auction",
        "auction_end_date": "not-an-auction",
        "current_price": None,
        "buy_now_price": None,
        "static_price": 5.0,
        "price_basis": "static_price",
        "listing_type": "fixed",
        "weight_lbs": None,
        "item_location": "Hampshire, IL",
        "origin_zip": None,
        "seller_id": "634686350",
        "seller_name": "Jeremy Thomsen",
        "available_fulfillment": ["local_pickup", "shipping"],
        "image_urls": ["https://example.com/img.jpg"],
        "shipping_estimate": None,
        "winning_bid": None,
    }
    record.update(changes)
    return record


EVIDENCE = (
    'NOT 5 DOLLARS; per-set asks: "40917 - Darksaber - 60", '
    '"40547 - vader and obi wan - 35", "41602 - brickheadz rey - 35", '
    '"41603 - brickheadz kylo - 30", "40765 - kamino training - 40" '
    "(sums to $200)"
)


def _appraisal(**changes):
    record = {
        "listing_key": "facebook|1024732190360342",
        "observations": {
            "model_score": 20,
            "model_rationale": "Stored ask is a placeholder; the body prices "
                               "five sets individually.",
        },
        "listing_category": "set",
        "set_numbers": ["40917-1", "40547-1", "41602-1", "41603-1", "40765-1"],
        "condition": "N",
        "description": "five sealed Star Wars sets",
        "set_completeness": "complete",
        "set_condition": "N",
        "estimated_total": 200.0,
        "per_lb_price": None,
        "per_lb_price_basis": "unknown",
        "cost_per_lb_note": "unknown",
        "handling_fee": None,
        "confidence": "high",
        "risks_unknowns": "multi-item listing; seller ask is the sum of the "
                          "stated per-set prices",
        "fee_breakdown": {
            "hammer": 200.0,
            "premium_pct": 0.0,
            "premium_amount": 0.0,
            "sales_tax_pct": 0.0,
            "sales_tax_amount": 0.0,
            "shipping_handling": None,
            "landed_total": 200.0,
            "shipping_unknown": True,
            "landed_is_floor": True,
        },
        "price_override": {
            "price": 200.0,
            "evidence": EVIDENCE,
        },
    }
    record.update(changes)
    return record


def _stub_comps():
    return {
        "mode": "set",
        "sets": [
            {"set_no": f"40917-{n}", "bricklink": None, "ebay":
             {"available": False, "reason": "dry-build stub"}}
            for n in (1,)
        ],
    }


# The real comps shape for five sets; each entry needs bricklink+ebay keys.
def _real_stub_comps():
    sets = []
    for no in ("40917-1", "40547-1", "41602-1", "41603-1", "40765-1"):
        sets.append({
            "set_no": no,
            "bricklink": None,
            "ebay": {"available": False, "reason": "dry-build stub"},
        })
    return {"mode": "set", "sets": sets}


def test_override_moves_static_price_and_hammer():
    record = build_record.build_deal_record(
        _candidate(), _appraisal(),
        first_seen_at="2026-08-24T00:00:00+00:00",
        last_seen_at="2026-08-24T00:00:00+00:00",
        status="rejected",  # out-of-radius pickup rows build as rejected
        comps=_real_stub_comps(),
    )
    assert record["static_price"] == 200.0
    assert record["price_basis"] == "static_price"
    assert record["fee_breakdown"]["hammer"] == 200.0
    # The override survives on the record so the evidence stays auditable.
    assert record["price_override"] == {"price": 200.0, "evidence": EVIDENCE}


def test_validator_requires_applied_override():
    rec = {
        "listing_key": "facebook|x",
        "status": "active",
        "listing_type": "fixed",
        "available_fulfillment": ["shipping"],
        "item_location": "Hampshire, IL",
        "price_basis": "static_price",
        "static_price": 5.0,
        "buy_now_price": None,
        "current_price": None,
        "fee_breakdown": {"hammer": 5.0},
        "price_override": {"price": 200.0, "evidence": "NOT 5 DOLLARS ... 200"},
    }
    key, errors, _warns = ledger_validate.check(rec)
    assert key == "facebook|x"
    assert any("never applied" in e for e in errors), errors

    applied = dict(rec, static_price=200.0, fee_breakdown={"hammer": 200.0})
    _, errors_applied, _ = ledger_validate.check(applied)
    assert not any("price_override" in e for e in errors_applied)


def test_validator_rejects_unevidenced_override():
    rec = {
        "listing_key": "facebook|y",
        "status": "active",
        "listing_type": "fixed",
        "available_fulfillment": ["shipping"],
        "item_location": "Somewhere, IN",
        "price_basis": "static_price",
        "static_price": 200.0,
        "buy_now_price": None,
        "current_price": None,
        "fee_breakdown": {"hammer": 200.0},
        "price_override": {"price": 200.0, "evidence": "seller said so"},
    }
    _, errors, _ = ledger_validate.check(rec)
    assert any("evidence" in e for e in errors), errors


def test_builder_refuses_unevidenced_override():
    with pytest.raises(ValueError, match="unevidenced correction"):
        build_record.build_deal_record(
            _candidate(), _appraisal(price_override={"price": 200.0,
                                                     "evidence": "trust me"}),
            first_seen_at="2026-08-24T00:00:00+00:00",
            last_seen_at="2026-08-24T00:00:00+00:00",
        )


def test_builder_refuses_auction_basis_override():
    with pytest.raises(ValueError, match="fixed-price asks"):
        build_record.build_deal_record(
            _candidate(price_basis="current_price", current_price=5.0),
            _appraisal(),
            first_seen_at="2026-08-24T00:00:00+00:00",
            last_seen_at="2026-08-24T00:00:00+00:00",
        )


def test_builder_refuses_phantom_authored_fee_breakdown():
    with pytest.raises(ValueError, match="contradicted crawl price"):
        build_record.build_deal_record(
            _candidate(),
            _appraisal(fee_breakdown={
                "hammer": 5.0,
                "premium_pct": 0.0,
                "premium_amount": 0.0,
                "sales_tax_pct": 0.0,
                "sales_tax_amount": 0.0,
                "shipping_handling": None,
                "landed_total": 5.0,
                "shipping_unknown": True,
                "landed_is_floor": True,
            }),
            first_seen_at="2026-08-24T00:00:00+00:00",
            last_seen_at="2026-08-24T00:00:00+00:00",
        )


def test_null_ask_raises_instead_of_writing_a_priceless_row():
    with pytest.raises(ValueError, match="no cost basis"):
        build_record.build_deal_record(
            _candidate(),
            _appraisal(price_override={"price": None, "evidence": EVIDENCE}),
            first_seen_at="2026-08-24T00:00:00+00:00",
            last_seen_at="2026-08-24T00:00:00+00:00",
        )


def test_no_override_changes_nothing():
    appraisal = _appraisal()
    del appraisal["price_override"]
    appraisal["estimated_total"] = 5.0
    appraisal["fee_breakdown"] = {
        "hammer": 5.0,
        "premium_pct": 0.0,
        "premium_amount": 0.0,
        "sales_tax_pct": 0.0,
        "sales_tax_amount": 0.0,
        "shipping_handling": None,
        "landed_total": 5.0,
        "shipping_unknown": True,
        "landed_is_floor": True,
    }
    record = build_record.build_deal_record(
        _candidate(), appraisal,
        first_seen_at="2026-08-24T00:00:00+00:00",
        last_seen_at="2026-08-24T00:00:00+00:00",
        status="rejected",
        comps=_real_stub_comps(),
    )
    assert record["static_price"] == 5.0
