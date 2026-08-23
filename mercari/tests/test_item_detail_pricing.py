"""Regression tests for Mercari detail buyer-cost fields."""

import pytest

from mercari_cli.client import MercariClient
from mercari_cli.parsers import normalize_item_detail


def test_detail_exposes_fee_and_total_for_seller_paid_shipping():
    item = normalize_item_detail(
        {
            "itemId": "m1",
            "price": 12000,
            "priceSummary": {"totalPrice": 12432},
            "shippingPayer": {"code": "seller"},
        }
    )

    assert item["buyer_protection_fee_cents"] == 432
    assert item["landed_total_cents"] == 12432


def test_detail_subtracts_buyer_shipping_from_fee():
    item = normalize_item_detail(
        {
            "itemId": "m2",
            "price": 28500,
            "priceSummary": {"totalPrice": 30351},
            "shippingPayer": {"code": "buyer"},
            "shippingClass": {"fee": 797},
        }
    )

    assert item["buyer_protection_fee_cents"] == 1054
    assert item["landed_total_cents"] == 30351


def test_client_normalizes_each_cached_raw_item(monkeypatch):
    client = MercariClient.__new__(MercariClient)
    raw_item = {
        "itemId": "m2",
        "price": 28500,
        "priceSummary": {"totalPrice": 30351},
        "shippingPayer": {"code": "buyer"},
        "shippingClass": {"fee": 797},
    }
    monkeypatch.setattr(client, "_fetch_item", lambda _item_id: raw_item)

    item = client.get_item("m2")

    assert item["buyer_protection_fee_cents"] == 1054
    assert item["landed_total_cents"] == 30351


@pytest.mark.parametrize(
    "raw, message",
    [
        (
            {"itemId": "m3", "priceSummary": {"totalPrice": 100}},
            "no integer price",
        ),
        (
            {"itemId": "m4", "price": 100, "priceSummary": {}},
            "priceSummary.totalPrice",
        ),
        (
            {
                "itemId": "m5",
                "price": 100,
                "priceSummary": {"totalPrice": 110},
                "shippingPayer": {"code": "buyer"},
                "shippingClass": {},
            },
            "shippingClass.fee",
        ),
    ],
)
def test_detail_fails_when_structured_cost_fields_are_missing(raw, message):
    with pytest.raises(ValueError, match=message):
        normalize_item_detail(raw)
