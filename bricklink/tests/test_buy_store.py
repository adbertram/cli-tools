"""SQLite buy store tests."""

from bricklink_cli.buy.store import BuyStore


def test_id_item_ttl(tmp_path):
    store = BuyStore(tmp_path / "buy.sqlite3")
    store.put_id_item("PART", "3001", 264, now=1000.0)
    assert store.get_id_item("PART", "3001", now=1000.0 + 10) == 264
    assert store.get_id_item("PART", "3001", now=1000.0 + 10, ttl=5) is None


def test_replace_and_query_lots(tmp_path):
    store = BuyStore(tmp_path / "buy.sqlite3")
    lots = [
        {
            "id_inv": 1,
            "price_display": "US $1.50",
            "qty": 5,
            "color_id": 11,
            "color_name": "Black",
            "condition_code": "N",
            "store_name": "StoreA",
            "seller_username": "seller1",
            "seller_country_code": "US",
            "seller_feedback": 10,
            "description": "",
        },
        {
            "id_inv": 2,
            "price_display": "US $0.50",
            "qty": 2,
            "color_id": 11,
            "color_name": "Black",
            "condition_code": "U",
            "store_name": "StoreB",
            "seller_username": "seller2",
            "seller_country_code": "DE",
            "seller_feedback": 20,
            "description": "",
        },
    ]
    store.replace_lots_for_item(
        item_type="PART", item_no="3001", id_item=264, lots=lots, now=1000.0
    )
    assert store.lots_fresh("PART", "3001", now=1000.0 + 10, ttl=100)
    rows = store.query_lots(item_type="PART", item_no="3001", max_price=1.0)
    assert len(rows) == 1
    assert rows[0].id_inv == 2
    assert rows[0].price_value == 0.5
