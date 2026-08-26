"""The 3 eBay comp fields must round-trip through the ledger, not just the schema.

`deal_schema.json`'s `properties`/`required` are what `build_deal_record` validates
against, but they are NOT what actually gets written to SQLite -- `db.py` hand-
maintains a separate `SCALAR_FIELDS` tuple, and `_deal_to_params` writes only
`_COLUMNS` (`SCALAR_FIELDS + JSON_FIELDS`). A field present in the schema but
absent from `SCALAR_FIELDS` passes every validation check and is silently
dropped at write time. This test proves the three new eBay fields are in both
places, the way it should have been proven for every prior schema addition.
"""
from __future__ import annotations

from legoscout_cli.ledger import db as ledger_db

_NEW_FIELDS = ("ebay_avg_sold_price", "ebay_comp_count", "ebay_avg_price_per_lb")


def test_new_ebay_fields_are_scalar_columns_not_silently_dropped():
    for field in _NEW_FIELDS:
        assert field in ledger_db.SCALAR_FIELDS, (
            "%r is not in db.SCALAR_FIELDS -- it will validate against "
            "deal_schema.json and then vanish at write time" % field)


def _seed_deal(key):
    return {
        "listing_key": key,
        "source": key.split("|")[0],
        "title": "LEGO 75192-1",
        "url": "https://example.invalid/%s" % key.split("|")[1],
        "current_price": 500.0,
        "price_basis": "current_price",
        "status": "active",
        "ebay_avg_sold_price": 812.34,
        "ebay_comp_count": 7,
        "ebay_avg_price_per_lb": None,
    }


def test_new_ebay_fields_round_trip_through_upsert_and_load(tmp_path):
    path = str(tmp_path / "found_deals.db")
    ledger_db.init(path).close()
    ledger_db.upsert_deals([_seed_deal("shopgoodwill|1001")], path=path)

    (deal,) = ledger_db.load_deals(path=path)
    assert deal["ebay_avg_sold_price"] == 812.34
    assert deal["ebay_comp_count"] == 7
    assert deal["ebay_avg_price_per_lb"] is None
