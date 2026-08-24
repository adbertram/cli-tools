"""A marketplace quote distinguishes free shipping from missing freight."""
from __future__ import annotations

from legoscout_cli.ledger import shipping
from legoscout_cli.ledger import validate


def record(estimate):
    return {
        "listing_key": "mercari|test",
        "source": "mercari",
        "status": "active",
        "listing_type": "fixed",
        "price_basis": "static_price",
        "static_price": 10.0,
        "available_fulfillment": ["shipping"],
        "item_location": "Michigan",
        "pickup_miles": None,
        "shipping_estimate": estimate,
        "fee_breakdown": {
            "hammer": 10.0,
            "shipping_handling": 0.0,
        },
    }


def zero_shipping_warning(warnings):
    return [warning for warning in warnings
            if "priced at $0.00 shipping" in warning]


def test_quoted_zero_proves_free_shipping():
    _, _, warnings = validate.check(record(shipping.quoted(0.0)))
    assert zero_shipping_warning(warnings) == []


def test_unquoted_freight_does_not_prove_free_shipping():
    _, _, warnings = validate.check(
        record(shipping.unquoted("the source published no buyer rate")))
    assert len(zero_shipping_warning(warnings)) == 1
