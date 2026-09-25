import tempfile
from pathlib import Path

from bricklink_cli.buy.include import attach_sellers, parse_include, seller_lot_summary
from bricklink_cli.buy.store import BuyStore


def test_parse_include_sellers_aliases():
    assert parse_include(None) == set()
    assert parse_include("") == set()
    assert parse_include("sellers") == {"sellers"}
    assert parse_include("seller,store,country") == {"sellers"}
    assert parse_include("feedback") == {"sellers"}


def test_parse_include_unknown():
    try:
        parse_include("sellers,shipping")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "shipping" in str(e)


def test_attach_sellers_joins_cheapest_lots():
    with tempfile.TemporaryDirectory() as tmp:
        store = BuyStore(Path(tmp) / "buy.sqlite3")
        store.replace_lots_for_item(
            item_type="MINIFIG",
            item_no="sw0001",
            id_item=1,
            lots=[
                {
                    "id_inv": 10,
                    "color_id": None,
                    "color_name": None,
                    "condition_code": "U",
                    "qty": 1,
                    "price_display": "US $5.00",
                    "price_value": 5.0,
                    "currency": "USD",
                    "store_name": "DearStore",
                    "seller_username": "alice",
                    "seller_country_code": "US",
                    "seller_feedback": 100,
                    "description": None,
                },
                {
                    "id_inv": 11,
                    "color_id": None,
                    "color_name": None,
                    "condition_code": "U",
                    "qty": 2,
                    "price_display": "US $2.00",
                    "price_value": 2.0,
                    "currency": "USD",
                    "store_name": "CheapShop",
                    "seller_username": "bob",
                    "seller_country_code": "DE",
                    "seller_feedback": 50,
                    "description": None,
                },
            ],
        )
        rows = attach_sellers(
            [{"item_type": "MINIFIG", "item_no": "sw0001", "gap_ratio": 0.5}],
            store,
            condition="U",
            max_lots=10,
        )
        assert len(rows) == 1
        assert rows[0]["live_lot_count"] == 2
        assert rows[0]["live_countries"] == {"DE": 1, "US": 1}
        assert rows[0]["cheap_lots"][0]["seller"] == "bob"
        assert rows[0]["cheap_lots"][0]["price_value"] == 2.0
        assert rows[0]["cheap_lots"][0]["store"] == "CheapShop"
        assert rows[0]["cheap_lots"][0]["country"] == "DE"
        assert rows[0]["cheap_lots"][0]["shipping_est"] == 5.5
        assert rows[0]["cheap_lots"][0]["landed_price"] == 2.0 + 5.5
        assert rows[0]["landed_buy"] == 2.0 + 5.5


def test_seller_lot_summary_aliases():
    s = seller_lot_summary({
        "idInv": 9,
        "price_display": "$1",
        "seller_username": "x",
        "store_name": "y",
        "seller_country_code": "CA",
        "seller_feedback": 3,
        "qty": 1,
        "condition_code": "N",
    })
    assert s["id_inv"] == 9
    assert s["seller"] == "x"
    assert s["store"] == "y"
    assert s["country"] == "CA"
    assert s["feedback"] == 3
    assert s["shipping_est"] == 5.5
    assert s["landed_price"] is None  # no price_value in this fixture
