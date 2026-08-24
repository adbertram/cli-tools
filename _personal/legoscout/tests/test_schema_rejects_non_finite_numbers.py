#!/usr/bin/env python3
"""`inf` and `nan` are floats, so `"type": "number"` alone lets them into the ledger.

They are not quantities. An `inf` weight passes `validate_field`, survives the
save, and then poisons every figure derived from it -- `per_lb_price` goes
`nan`, and the rescore aborts the WHOLE ledger with `curve lookup fell through
for x=nan`, a message that names neither the field nor the listing.

`schema.validate_field` is the one gate every stored value passes through on the
way into `deal_schema.json`-checked storage, so the check belongs there rather
than at each of the dozen places that later divide by one of these numbers.
"""
from __future__ import annotations

import math

import pytest

from legoscout_cli.ledger import schema as deal_schema

NUMERIC_FIELDS = ("buy_now_price", "current_price", "static_price",
                  "weight_lbs", "estimated_total", "per_lb_price")

NOT_A_QUANTITY = (float("inf"), float("-inf"), float("nan"))


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
@pytest.mark.parametrize("value", NOT_A_QUANTITY)
def test_a_non_finite_number_never_reaches_storage(field, value):
    """Rejected, and the message names the field.

    A bounded field such as `weight_lbs` may be rejected by its own
    `minimum`/`maximum` before the finiteness check runs. Either refusal is the
    right outcome; the test asserts the refusal, not which rule got there first.
    """
    with pytest.raises(deal_schema.Invalid) as exc:
        deal_schema.validate_field(field, value)
    assert field in str(exc.value)


@pytest.mark.parametrize("value", NOT_A_QUANTITY)
def test_an_unbounded_numeric_field_is_caught_by_the_finiteness_check(value):
    """Prices carry no `minimum`/`maximum`, so only this check stops them."""
    with pytest.raises(deal_schema.Invalid) as exc:
        deal_schema.validate_field("buy_now_price", value)
    assert "not a finite number" in str(exc.value)


def test_bounds_alone_do_not_catch_nan_even_on_a_bounded_field():
    """Why the check is needed on `weight_lbs` too.

    `nan < 0` and `nan > 2000` are both False, so JSON Schema's `minimum` and
    `maximum` pass it straight through. `nan` is what aborts the rescore.
    """
    with pytest.raises(deal_schema.Invalid) as exc:
        deal_schema.validate_field("weight_lbs", float("nan"))
    assert "not a finite number" in str(exc.value)


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
def test_real_numbers_and_null_still_pass(field):
    """The check must not cost a legal value. `0` is a real price on a zero-bid
    auction, and `None` is the schema's own answer for an unread number."""
    deal_schema.validate_field(field, 0)
    deal_schema.validate_field(field, 12.5)
    deal_schema.validate_field(field, None)


def test_a_non_finite_number_nested_in_an_object_is_rejected():
    """`fee_breakdown.hammer` reaches the same arithmetic a top-level price does.

    `nan` rather than `inf`, because the subschema's own `maximum` already stops
    `inf` -- and no bound can stop `nan`. The message names the PATH, not just
    the top-level field.
    """
    with pytest.raises(deal_schema.Invalid) as exc:
        deal_schema.validate_field(
            "fee_breakdown",
            {"hammer": float("nan"), "premium_pct": 0.05, "source": "depop"})
    assert "fee_breakdown.hammer" in str(exc.value)


def test_a_non_finite_number_nested_in_an_array_is_rejected():
    with pytest.raises(deal_schema.Invalid) as exc:
        deal_schema.validate_field(
            "set_analysis",
            [{"set_number": "40460-1", "comp_price": float("nan")}])
    assert "set_analysis[0].comp_price" in str(exc.value)


def test_a_whole_record_carrying_one_non_finite_number_is_rejected():
    """`validate()` names the LISTING and the field, which is what the
    `curve lookup fell through for x=nan` abort never did."""
    record = {"listing_key": "ebay|infinite-weight", "weight_lbs": float("inf")}
    with pytest.raises(deal_schema.Invalid) as exc:
        deal_schema.validate(record)
    assert "ebay|infinite-weight" in str(exc.value)
    assert "weight_lbs" in str(exc.value)


def test_the_stored_ledger_holds_no_non_finite_number():
    """A live check, not a fixture: nothing already saved carries one."""
    from legoscout_cli.ledger import db as ledger_db

    bad = []
    for deal in ledger_db.load_deals():
        for field, value in deal.items():
            if isinstance(value, float) and not math.isfinite(value):
                bad.append("%s.%s=%r" % (deal["listing_key"], field, value))
    assert bad == [], bad
