#!/usr/bin/env python3
"""Nothing in the landed-cost path may substitute a number for missing data.

Three defects, one root: a value the pipeline could not read was quietly
replaced by a plausible-looking one, and every gate downstream then agreed with
the replacement.

  * `_resolve_shipping` rebuilt the landed total as
    `float(breakdown.get("hammer") or 0.0)`. A `fee_breakdown` with no `hammer`
    key -- or a null one -- dropped the ITEM PRICE. A $45.00 lot quoting $10.00
    of freight came back out as a $10.00 landed total, $1.00/lb instead of
    $5.50/lb, and the deals-page row read `score 93 | total 10 | perLb 1 |
    hammer 45` while `legoscout deals validate --strict` reported zero errors on
    it. `premium_amount` and `sales_tax_amount` carried the same `or 0.0`.
    A mirror-image path did the same thing without arithmetic: a `None`
    `fee_breakdown` beside a real quote made the function `return`, dropping the
    quote with no message at all.

  * `fee_breakdown` was typed `object` with NO `properties`, while
    `shipping_estimate` beside it carried a full `oneOf`. An appraiser writing
    `premium_pct: "18%"` cleared `build_deal_record` AND `--strict`, then threw
    `unsupported format character '%'` in the row builder -- which returns ZERO
    rows for the WHOLE ledger, so every good deal went with it.

  * `weight_lbs` had no range check anywhere: not in the schema, not in
    `build_deal_record`, not in the scorer, not in the validator. `1e300` on the
    same $45.00 lot scored 97 with `max_price` 4.88e+300 and rendered on the
    page at `perLb 5.5e-299`, and `--strict` reported no error.

Each case below is the reproduction, not a paraphrase of it.
"""
from __future__ import annotations

import copy

import pytest

from legoscout_cli.ledger import build_record as bdr
from legoscout_cli.ledger import schema as deal_schema

FIRST_SEEN = "2026-08-06T00:00:00+00:00"

# The reproduction lot: ShopGoodwill bulk, $45.00 buy-now, 10 lb stated, the
# source quoting $10.00 of freight to 47725. Landed $55.00, $5.50/lb.
CANDIDATE = {
    "listing_key": "shopgoodwill|999000001",
    "title": "Bulk LEGO lot 10 lbs",
    "url": "https://shopgoodwill.com/item/999000001",
    "direct_url": "https://shopgoodwill.com/item/999000001",
    "posted_date": "2026-08-01",
    "auction_start_date": "not-an-auction",
    "auction_end_date": "not-an-auction",
    "current_price": None,
    "buy_now_price": 45.00,
    "static_price": None,
    "price_basis": "buy_now",
    "listing_type": "fixed",
    "weight_lbs": 10.0,
    "item_location": "Evansville, IN",
    "origin_zip": "47725",
    "seller_id": "8",
    "seller_name": "Goodwill of Southern Indiana",
    "available_fulfillment": ["shipping"],
    "image_urls": [],
    "shipping_estimate": {"status": "quoted", "shipping_price": 10.0,
                          "handling_price": None, "service": "G"},
}

APPRAISAL = {
    "listing_category": "bulk",
    "estimated_total": 55.0,
    "handling_fee": 0.0,
    "per_lb_price": 5.5,
    "per_lb_price_basis": "landed",
    "confidence": "medium",
    "shipping_estimated": False,
    "pickup_miles": 5.0,
    "fee_breakdown": {"hammer": 45.0, "premium_amount": 0.0,
                      "sales_tax_amount": 0.0, "shipping_handling": 10.0,
                      "landed_total": 55.0},
    "observations": {
        "description": "",
        "vision": {"status": "no_images", "image_count": None,
                   "target_colors": "unknown", "color_families": [],
                   "themes": [], "minifigs": "not_visible",
                   "contamination": [], "retired_sets_visible": None,
                   "weight_estimate_lbs": None, "weight_confidence": None,
                   "notes": "seller posted no photos"},
        "model_score": 50,
        "model_rationale": "The fixture has neutral bulk lot evidence.",
    },
}


def build(*, candidate=None, fee_breakdown=..., observations=None):
    cand = copy.deepcopy(CANDIDATE)
    appr = copy.deepcopy(APPRAISAL)
    cand.update(candidate or {})
    if fee_breakdown is not ...:
        appr["fee_breakdown"] = fee_breakdown
    if observations is not None:
        appr["observations"] = observations
    return bdr.build_deal_record(cand, appr,
                                 first_seen_at=FIRST_SEEN, last_seen_at=FIRST_SEEN)


def test_the_reproduction_lot_prices_correctly():
    """The control. Every case below is this lot with one value broken."""
    record = build()
    assert record["estimated_total"] == 55.0
    assert record["per_lb_price"] == 5.5
    assert record["fee_breakdown"]["hammer"] == 45.0
    assert record["fee_breakdown"]["shipping_handling"] == 10.0


# ---------------------------------------------------------------------------
# CRITICAL -- `float(breakdown.get(<line>) or 0.0)` dropped the item price
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", ("hammer", "premium_amount", "sales_tax_amount"))
@pytest.mark.parametrize("broken", (None, "missing", "45.00", [45.0], True))
def test_a_non_numeric_fee_line_raises_instead_of_reading_as_zero(line, broken):
    """Every line the landed total is rebuilt from must be a real number.

    `hammer` is the one that cost the most -- a missing one turned $55.00 landed
    into $10.00 -- but `premium_amount` and `sales_tax_amount` understate the
    same total the same silent way, and all three carried the same `or 0.0`.
    """
    breakdown = copy.deepcopy(APPRAISAL["fee_breakdown"])
    if broken == "missing":
        del breakdown[line]
    else:
        breakdown[line] = broken

    with pytest.raises((ValueError, deal_schema.Invalid)) as exc:
        build(fee_breakdown=breakdown)
    assert line in str(exc.value)


def test_the_landed_total_still_carries_the_item_price():
    """The exact figure the fallback destroyed.

    Guards the arithmetic itself, not just the raise: a rebuild that reads every
    line and still forgets to add one would pass the test above.
    """
    breakdown = copy.deepcopy(APPRAISAL["fee_breakdown"])
    breakdown.update({"hammer": 45.0, "premium_amount": 8.10,
                      "sales_tax_amount": 3.72})
    record = build(fee_breakdown=breakdown)
    assert record["fee_breakdown"]["landed_total"] == 66.82
    assert record["estimated_total"] == 66.82
    assert record["per_lb_price"] == 6.682


def test_mercari_quote_requires_its_numeric_buyer_protection_fee():
    with pytest.raises(ValueError, match="buyer_protection_fee"):
        build(candidate={"listing_key": "mercari|999000001"})


def test_mercari_buyer_protection_fee_survives_shipping_rebuild():
    breakdown = copy.deepcopy(APPRAISAL["fee_breakdown"])
    breakdown["buyer_protection_fee"] = 4.32

    record = build(
        candidate={"listing_key": "mercari|999000001"},
        fee_breakdown=breakdown)

    assert record["fee_breakdown"]["buyer_protection_fee"] == 4.32
    assert record["estimated_total"] == 59.32


def test_a_quote_with_no_fee_breakdown_raises_rather_than_returning():
    """The mirror-image silent path: `None` breakdown, quote dropped, no message.

    `validate.shipping_errors` calls this exact state an ERROR when it finds it
    in the ledger, and could not see it here because the assembled record never
    carried a freight line to disagree with.
    """
    with pytest.raises(ValueError) as exc:
        build(fee_breakdown=None)
    message = str(exc.value)
    assert "shopgoodwill|999000001" in message
    assert "fee_breakdown" in message


def test_an_unpriced_lot_with_no_quote_is_still_a_legitimate_null_breakdown():
    """The state that must NOT raise, or 164 stored rows become unassemblable.

    `fee_breakdown: null` is legitimate -- it is a lot nobody priced. What is
    not legitimate is a published rate with nowhere to put it.
    """
    record = build(candidate={"shipping_estimate": None}, fee_breakdown=None)
    assert record["fee_breakdown"] is None


# ---------------------------------------------------------------------------
# HIGH -- an untyped `fee_breakdown` took the whole deals page down
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ("18%", "0.18", [0.18], {"pct": 0.18},
                                   float("inf"), float("nan"), True))
def test_a_non_numeric_premium_pct_never_reaches_the_ledger(value):
    """`premium_pct: "18%"` cleared assembly AND `--strict`, then threw in the
    row builder with `unsupported format character '%'` and returned ZERO rows
    for the whole ledger -- the three clean deals beside it were lost too.

    `inf` and `nan` are in here because both pass a bare JSON-Schema `number`.
    """
    breakdown = copy.deepcopy(APPRAISAL["fee_breakdown"])
    breakdown["premium_pct"] = value
    with pytest.raises(deal_schema.Invalid):
        build(fee_breakdown=breakdown)


@pytest.mark.parametrize("field", ("hammer", "premium_amount", "sales_tax_amount",
                                   "sales_tax_pct", "landed_total",
                                   "shipping_handling", "fee_multiple"))
def test_every_numeric_fee_field_is_bounded_not_merely_typed(field):
    """A bare `number` accepts `inf`. The `maximum` is what rejects it."""
    breakdown = copy.deepcopy(APPRAISAL["fee_breakdown"])
    breakdown[field] = float("inf")
    with pytest.raises(deal_schema.Invalid):
        deal_schema.validate_field("fee_breakdown", breakdown)

    breakdown[field] = 1e300
    with pytest.raises(deal_schema.Invalid):
        deal_schema.validate_field("fee_breakdown", breakdown)


def test_an_invented_fee_key_is_refused():
    """`shipping_estimate` has carried `additionalProperties: false` all along;
    `fee_breakdown` had no rule at all, and 26 invented spellings reached the
    ledger before anyone looked."""
    breakdown = copy.deepcopy(APPRAISAL["fee_breakdown"])
    breakdown["buyers_premium_percentage"] = 0.18
    with pytest.raises(deal_schema.Invalid):
        deal_schema.validate_field("fee_breakdown", breakdown)


def test_a_priced_breakdown_must_name_its_hammer():
    with pytest.raises(deal_schema.Invalid):
        deal_schema.validate_field("fee_breakdown", {"premium_amount": 0.0})


def test_the_canonical_breakdown_fees_landed_cost_emits_still_validates():
    """The bound must not reject the shape the pricing module actually writes."""
    from legoscout_cli.pricing import fees

    breakdown = fees.landed_cost("shopgoodwill", 45.0, 10.0)
    deal_schema.validate_field("fee_breakdown", breakdown)
    assert breakdown["hammer"] == 45.0


# ---------------------------------------------------------------------------
# MEDIUM -- an unbounded `weight_lbs` is a free score multiplier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("weight", (1e300, 1e-9, -5.0, 2001.0,
                                    float("inf"), float("nan")))
def test_an_implausible_weight_raises(weight):
    """$/lb is landed/weight, so a big enough divisor makes any price look free
    (`1e300` -> score 97, `max_price` 4.88e+300) and a small enough one deletes
    the row from the table ($/lb 5.5e+10, `max_price` $0.00). Neither raised."""
    with pytest.raises(deal_schema.Invalid):
        build(candidate={"weight_lbs": weight})


@pytest.mark.parametrize("weight", (0, 0.0, None, 0.01, 0.084, 10.0, 100.0, 2000.0))
def test_a_plausible_weight_is_untouched(weight):
    """0 is grandfathered -- nine stored rows use it as 'no weight published' --
    and 100 lb is the heaviest the ledger has ever held."""
    deal_schema.validate_field("weight_lbs", weight)


@pytest.mark.parametrize("weight", (1e300, 1e-9, -5.0, 2001.0, float("inf")))
def test_the_model_authored_weight_estimate_carries_the_same_bound(weight):
    """`observations.vision.weight_estimate_lbs` is the divisor the scorer falls
    back to when the listing states no weight, so an absurd value there inflates
    the score exactly the same way."""
    observations = copy.deepcopy(APPRAISAL["observations"])
    observations["vision"]["weight_estimate_lbs"] = weight
    with pytest.raises(deal_schema.Invalid):
        deal_schema.validate_field("observations", observations)
