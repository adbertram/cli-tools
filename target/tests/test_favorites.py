"""Tests for the favorites (account "lists") read.

Covers the two pure/decidable layers so behavior is verifiable without a live
browser:

- ``normalize_favorites`` maps the ``favorites/v1/list_items`` envelope (captured
  live from the randafaith account) into flat favorite records.
- ``_hydrate_favorite`` enriches a favorite TCIN via the existing redsky
  ``get_item`` path plus a fulfillment read, and computes real purchasability:
  ``available`` (bool, true only when purchasable NOW), ``street_date``
  (str|None), and ``status`` (``available`` | ``coming_soon`` | ``out_of_stock``
  | ``delisted``). Critically, a delisted favorite (redsky raises
  ``ClientError``) degrades to ``available: False`` / ``status: "delisted"``
  instead of dropping the whole list.
- ``list_favorites`` orchestrates fetch -> normalize -> ``--limit`` slice ->
  hydrate.

The exact ``list_items`` shapes below are copied from the real favorites API
response for the randafaith account (see the migrated 2021 favorite, which omits
``item_note`` and is now delisted). The fulfillment shapes mirror
``product_fulfillment_v1`` bodies captured live: TCIN 94962117 (LoveShackFancy x
Target x Yoobi, street-dated 2026-07-05) returned ``pickup.availability_status:
"UNAVAILABLE"`` / ``shipping.availability_status: "OUT_OF_STOCK"``; an in-stock
control TCIN (87450164, Bounty paper towels) returned ``"IN_STOCK"`` for both.
"""
from datetime import date, timedelta

import pytest

from target_cli.client import ClientError, TargetClient
from target_cli.parsers import (
    is_orderable,
    normalize_favorites,
    normalize_fulfillment,
    normalize_product_detail,
)


# Real product_fulfillment_v1 bodies (via normalize_fulfillment) for the two
# live-observed cases; see the module docstring for how each was captured.
def _orderable_fulfillment(tcin: str = "87450164") -> dict:
    raw = {
        "data": {
            "product": {
                "fulfillment": {
                    "sold_out": False,
                    "is_out_of_stock_in_all_store_locations": False,
                    "store_options": [
                        {"location_id": "108", "location_name": "Evansville North",
                         "order_pickup": {"availability_status": "IN_STOCK"},
                         "location_available_to_promise_quantity": 10.0},
                    ],
                    "shipping_options": {"availability_status": "IN_STOCK",
                                          "available_to_promise_quantity": 10.0},
                }
            }
        }
    }
    return normalize_fulfillment(raw, tcin)


def _unavailable_fulfillment(tcin: str = "94962117") -> dict:
    # This is the real pre-launch item (TCIN 94962117): also carries the
    # future-selling-intent signals verified live (notify_me_eligible=true, both
    # dates populated for the 2026-07-05 street date, and a pre-order quantity of
    # 0.0 on the one observed store).
    raw = {
        "data": {
            "product": {
                "notify_me_eligible": True,
                "fulfillment": {
                    "sold_out": False,
                    "is_out_of_stock_in_all_store_locations": True,
                    "store_options": [
                        {"location_id": "108", "location_name": "Evansville North",
                         "order_pickup": {"availability_status": "UNAVAILABLE"},
                         "location_available_to_promise_quantity": 0.0,
                         "pre_order_location_available_to_promise_quantity": 0.0},
                    ],
                    "shipping_options": {"availability_status": "OUT_OF_STOCK",
                                          "available_to_promise_quantity": 0.0},
                    "future_selling_intent": {
                        "event_online_date_and_time": "2026-07-05T10:00:00.000Z",
                        "event_in_store_date_and_time": "2026-07-05T10:00:00.000Z",
                    },
                }
            }
        }
    }
    return normalize_fulfillment(raw, tcin)


_FUTURE_STREET_DATE = (date.today() + timedelta(days=1)).isoformat()
_PAST_STREET_DATE = (date.today() - timedelta(days=30)).isoformat()


# --- is_orderable: fulfillment channel -> purchasable-now? -----------------

def test_is_orderable_true_when_shipping_in_stock():
    assert is_orderable({"shipping": "IN_STOCK", "pickup": []}) is True


def test_is_orderable_true_when_any_pickup_store_in_stock():
    assert is_orderable({
        "shipping": "OUT_OF_STOCK",
        "pickup": [{"pickup": "UNAVAILABLE"}, {"pickup": "IN_STOCK"}],
    }) is True


def test_is_orderable_false_for_the_live_unavailable_case():
    # Verified live for TCIN 94962117 (LoveShackFancy x Target x Yoobi,
    # street-dated 2026-07-05): pickup UNAVAILABLE, shipping OUT_OF_STOCK.
    assert is_orderable(_unavailable_fulfillment()) is False


def test_is_orderable_true_for_the_live_in_stock_case():
    # Verified live for TCIN 87450164 (Bounty paper towels): both IN_STOCK.
    assert is_orderable(_orderable_fulfillment()) is True


def test_is_orderable_false_when_no_channels_present():
    assert is_orderable({"shipping": None, "pickup": []}) is False


# --- normalize_fulfillment: future-selling-intent / notify-me / pre-order --

def test_normalize_fulfillment_future_selling_intent_present_for_prelaunch_item():
    """Real pre-launch shape (TCIN 94962117): notify_me_eligible, both dates, and
    a pre-order quantity all populated."""
    record = _unavailable_fulfillment()
    assert record["notify_me_eligible"] is True
    assert record["available_online_date"] == "2026-07-05T10:00:00.000Z"
    assert record["available_instore_date"] == "2026-07-05T10:00:00.000Z"
    assert record["pre_order_quantity"] == 0.0


def test_normalize_fulfillment_future_selling_intent_absent_for_normal_item():
    """Real in-stock control (TCIN 87450164): no future_selling_intent key at all,
    no notify_me_eligible key at the product level -- all four new fields must
    normalize to None, not raise, and existing orderable behavior is unaffected."""
    record = _orderable_fulfillment()
    assert record["notify_me_eligible"] is None
    assert record["available_online_date"] is None
    assert record["available_instore_date"] is None
    assert record["pre_order_quantity"] is None
    assert record["orderable"] is True


def test_normalize_fulfillment_pre_order_quantity_takes_max_across_stores():
    raw = {
        "data": {
            "product": {
                "fulfillment": {
                    "store_options": [
                        {"location_id": "1", "pre_order_location_available_to_promise_quantity": 0.0},
                        {"location_id": "2", "pre_order_location_available_to_promise_quantity": 5.0},
                        {"location_id": "3", "pre_order_location_available_to_promise_quantity": 2.0},
                    ],
                }
            }
        }
    }
    assert normalize_fulfillment(raw, "999")["pre_order_quantity"] == 5.0


def test_normalize_fulfillment_notify_me_eligible_false_is_not_none():
    """notify_me_eligible: false is a real, present value -- must not be conflated
    with the field being absent (None)."""
    raw = {"data": {"product": {"notify_me_eligible": False, "fulfillment": {}}}}
    assert normalize_fulfillment(raw, "999")["notify_me_eligible"] is False


# --- normalize_product_detail: street_date passthrough ---------------------

def test_normalize_product_detail_reads_street_date_when_present():
    raw = {"data": {"product": {"tcin": "94962117", "item": {
        "mmbv_content": {"street_date": "2026-07-05"},
    }}}}
    assert normalize_product_detail(raw)["street_date"] == "2026-07-05"


def test_normalize_product_detail_street_date_none_when_absent():
    raw = {"data": {"product": {"tcin": "87450164", "item": {}}}}
    assert normalize_product_detail(raw)["street_date"] is None


# --- normalize_favorites: envelope -> records ------------------------------

# Real envelope excerpt: a current favorite (note == "None") + a migrated 2021
# favorite that omits item_note entirely.
FAVORITES_PAYLOAD = {
    "list_id": "158e66d0-1e00-11ec-a6fe-879ebecb6d22",
    "list_type": "FAVORITES",
    "list_title": "My Favorites",
    "list_items": [
        {
            "list_item_id": "95833240-7723-11f1-9d46-f9943cf91e27",
            "item_type": "TCIN",
            "tcin": "94962117",
            "item_note": "None",
            "added_ts": "2026-07-03T21:10:14Z",
        },
        {
            "list_item_id": "15f761d4-1e00-11ec-a6fe-879ebecb6d22",
            "item_type": "TCIN",
            "tcin": "78790319",
            "added_ts": "2021-09-25T12:57:05Z",
        },
    ],
    "items_count": 2,
}


def test_normalize_favorites_maps_tcin_added_note_and_list_item_id():
    rows = normalize_favorites(FAVORITES_PAYLOAD)
    assert rows == [
        {
            "tcin": "94962117",
            "list_item_id": "95833240-7723-11f1-9d46-f9943cf91e27",
            "added": "2026-07-03T21:10:14Z",
            "note": None,
        },
        {
            "tcin": "78790319",
            "list_item_id": "15f761d4-1e00-11ec-a6fe-879ebecb6d22",
            "added": "2021-09-25T12:57:05Z",
            "note": None,
        },
    ]


def test_normalize_favorites_keeps_a_real_note():
    payload = {"list_items": [{"tcin": "111", "list_item_id": "id-111", "item_note": "gift idea", "added_ts": "2026-01-01T00:00:00Z"}]}
    assert normalize_favorites(payload) == [
        {"tcin": "111", "list_item_id": "id-111", "added": "2026-01-01T00:00:00Z", "note": "gift idea"}
    ]


def test_normalize_favorites_empty_list_when_no_items():
    assert normalize_favorites({"items_count": 0}) == []
    assert normalize_favorites({"list_items": []}) == []


def test_normalize_favorites_missing_tcin_fails_loud():
    # tcin is a required identity field — a contract break must raise, not silently
    # drop the item.
    with pytest.raises(KeyError):
        normalize_favorites({"list_items": [{"item_note": "None"}]})


# --- _hydrate_favorite: enrich, or degrade a delisted favorite -------------

def _client_with_get_item(get_item, fulfillment=_orderable_fulfillment):
    client = TargetClient.__new__(TargetClient)
    client.get_item = get_item  # type: ignore[assignment]
    client._get_fulfillment_cached = lambda tcin: fulfillment()  # type: ignore[assignment]
    return client


def test_hydrate_favorite_available_when_orderable_now():
    """In-stock item: available=True, status="available", regardless of any
    street_date. The in-stock control fulfillment carries no
    future-selling-intent/notify-me keys at all, so those fields normalize to
    None on the favorite record too (not simply absent -- an available favorite
    is still a listed, non-delisted record)."""
    detail = {
        "id": "87450164",
        "title": "Bounty Select-A-Size Paper Towels",
        "price": "$22.49",
        "brand": "Bounty",
        "url": "https://www.target.com/p/-/A-87450164",
        "rating": 4.5,
        "street_date": _PAST_STREET_DATE,
    }
    client = _client_with_get_item(lambda tcin: detail, fulfillment=_orderable_fulfillment)
    row = client._hydrate_favorite({"tcin": "87450164", "added": "2026-07-03T21:10:14Z", "note": None})
    assert row == {
        "id": "87450164",
        "title": "Bounty Select-A-Size Paper Towels",
        "price": "$22.49",
        "available": True,
        "street_date": _PAST_STREET_DATE,
        "status": "available",
        "added": "2026-07-03T21:10:14Z",
        "note": None,
        "brand": "Bounty",
        "url": "https://www.target.com/p/-/A-87450164",
        "rating": 4.5,
        "notify_me_eligible": None,
        "available_online_date": None,
        "available_instore_date": None,
    }


def test_hydrate_favorite_coming_soon_when_not_orderable_with_future_street_date():
    """Pre-launch listing (e.g. LoveShackFancy x Target x Yoobi, street-dated
    2026-07-05): listed but not purchasable yet -> available=False,
    status="coming_soon", street_date carried through, and the
    future-selling-intent fields (notify_me_eligible + both drop dates) from the
    fulfillment read propagate onto the favorite record so it shows WHEN it
    drops, not just its street_date."""
    detail = {
        "id": "94962117",
        "title": "LoveShackFancy x Target - Yoobi Ribbon Rosa Quilted Tote Bag",
        "price": "$34.99",
        "brand": "LoveShackFancy x Target",
        "url": "https://www.target.com/p/-/A-94962117",
        "rating": 0.0,
        "street_date": _FUTURE_STREET_DATE,
    }
    client = _client_with_get_item(lambda tcin: detail, fulfillment=_unavailable_fulfillment)
    row = client._hydrate_favorite({"tcin": "94962117", "added": "2026-07-03T21:10:14Z", "note": None})
    assert row == {
        "id": "94962117",
        "title": "LoveShackFancy x Target - Yoobi Ribbon Rosa Quilted Tote Bag",
        "price": "$34.99",
        "available": False,
        "street_date": _FUTURE_STREET_DATE,
        "status": "coming_soon",
        "added": "2026-07-03T21:10:14Z",
        "note": None,
        "brand": "LoveShackFancy x Target",
        "url": "https://www.target.com/p/-/A-94962117",
        "rating": 0.0,
        "notify_me_eligible": True,
        "available_online_date": "2026-07-05T10:00:00.000Z",
        "available_instore_date": "2026-07-05T10:00:00.000Z",
    }


def test_hydrate_favorite_out_of_stock_when_not_orderable_with_no_future_street_date():
    """Not purchasable, and no future street_date (either none at all, or a past
    one left over from a prior launch) -> status="out_of_stock", not
    "coming_soon"."""
    detail = {
        "id": "11111111",
        "title": "Sold Out Widget",
        "price": "$9.99",
        "brand": "Acme",
        "url": "https://www.target.com/p/-/A-11111111",
        "rating": 3.0,
        "street_date": None,
    }
    client = _client_with_get_item(lambda tcin: detail, fulfillment=_unavailable_fulfillment)
    row = client._hydrate_favorite({"tcin": "11111111", "added": "2026-07-03T21:10:14Z", "note": None})
    assert row["available"] is False
    assert row["status"] == "out_of_stock"
    assert row["street_date"] is None


def test_hydrate_favorite_out_of_stock_when_street_date_is_in_the_past():
    """A leftover PAST street_date must not be misread as "coming soon" -- an
    item can be not-currently-orderable (e.g. temporarily out of stock) long
    after its original launch date."""
    detail = {
        "id": "22222222",
        "title": "Restocking Widget",
        "price": "$14.99",
        "brand": "Acme",
        "url": "https://www.target.com/p/-/A-22222222",
        "rating": 4.0,
        "street_date": _PAST_STREET_DATE,
    }
    client = _client_with_get_item(lambda tcin: detail, fulfillment=_unavailable_fulfillment)
    row = client._hydrate_favorite({"tcin": "22222222", "added": "2026-07-03T21:10:14Z", "note": None})
    assert row["available"] is False
    assert row["status"] == "out_of_stock"
    assert row["street_date"] == _PAST_STREET_DATE


def test_hydrate_favorite_degrades_when_product_delisted():
    def boom(tcin):
        raise ClientError(f"No product found for TCIN {tcin}.")

    client = _client_with_get_item(boom)
    row = client._hydrate_favorite({"tcin": "78790319", "added": "2021-09-25T12:57:05Z", "note": None})
    assert row == {
        "id": "78790319",
        "title": None,
        "price": None,
        "available": False,
        "street_date": None,
        "status": "delisted",
        "added": "2021-09-25T12:57:05Z",
        "note": None,
    }
    # A degraded record must NOT carry the enrichment-only fields.
    assert "brand" not in row and "url" not in row
    assert "notify_me_eligible" not in row
    assert "available_online_date" not in row and "available_instore_date" not in row


# --- list_favorites: fetch -> slice(limit) -> hydrate ----------------------

def _client_for_list(payload, get_item, fulfillment=_orderable_fulfillment):
    client = TargetClient.__new__(TargetClient)
    # Accept the optional page kwarg the real method takes (remove/get reuse it).
    client._fetch_favorites_payload = lambda *, page=None: payload  # type: ignore[assignment]
    client.get_item = get_item  # type: ignore[assignment]
    client._get_fulfillment_cached = lambda tcin: fulfillment()  # type: ignore[assignment]
    return client


def test_list_favorites_returns_one_record_per_favorite():
    seen = []

    def get_item(tcin):
        seen.append(tcin)
        return {"title": f"T{tcin}", "price": "$1.00"}

    client = _client_for_list(FAVORITES_PAYLOAD, get_item)
    rows = client.list_favorites(limit=24)
    assert [r["id"] for r in rows] == ["94962117", "78790319"]
    assert seen == ["94962117", "78790319"]


def test_list_favorites_respects_limit_before_hydration():
    # --limit must bound the number of (cached but real) product lookups, so only
    # the first `limit` TCINs are hydrated.
    hydrated = []

    def get_item(tcin):
        hydrated.append(tcin)
        return {"title": "x", "price": "$1.00"}

    client = _client_for_list(FAVORITES_PAYLOAD, get_item)
    rows = client.list_favorites(limit=1)
    assert len(rows) == 1
    assert rows[0]["id"] == "94962117"
    assert hydrated == ["94962117"]  # the second favorite was never looked up


def test_list_favorites_empty_when_account_has_no_favorites():
    client = _client_for_list({"list_items": [], "items_count": 0}, lambda tcin: {})
    assert client.list_favorites(limit=24) == []


# --- get_favorite: single lookup by TCIN -----------------------------------

def test_get_favorite_returns_the_hydrated_record_for_a_saved_tcin():
    client = _client_for_list(FAVORITES_PAYLOAD, lambda tcin: {"title": "Tote", "price": "$34.99"})
    row = client.get_favorite("94962117")
    assert row["id"] == "94962117"
    assert row["title"] == "Tote"
    assert row["available"] is True
    assert row["status"] == "available"


def test_get_favorite_raises_when_tcin_not_favorited():
    client = _client_for_list(FAVORITES_PAYLOAD, lambda tcin: {"title": "x", "price": "$1"})
    with pytest.raises(ClientError):
        client.get_favorite("00000000")


# --- remove_favorite: resolve TCIN -> list_item_id -> DELETE ---------------

def _client_for_remove(payload, delete_result):
    """Client whose favorites page + DELETE are stubbed; records the DELETE URL."""
    client = TargetClient.__new__(TargetClient)
    client._fetch_favorites_payload = lambda *, page=None: payload  # type: ignore[assignment]
    client._get_favorites_page = lambda: object()  # type: ignore[assignment]
    calls = {"urls": []}

    def fake_delete(page, url):
        calls["urls"].append(url)
        return delete_result

    client._delete_via_session = fake_delete  # type: ignore[assignment]
    return client, calls


def test_remove_favorite_deletes_using_the_resolved_list_item_id():
    client, calls = _client_for_remove(FAVORITES_PAYLOAD, {"ok": True, "status": 200, "body": ""})
    result = client.remove_favorite("78790319")
    # DELETE must target this favorite's list_item_id, not the raw TCIN.
    assert len(calls["urls"]) == 1
    assert "/favorites/v1/list_items/15f761d4-1e00-11ec-a6fe-879ebecb6d22" in calls["urls"][0]
    assert "78790319" not in calls["urls"][0]  # the TCIN is NOT the delete key
    assert result == {
        "removed": True,
        "tcin": "78790319",
        "list_item_id": "15f761d4-1e00-11ec-a6fe-879ebecb6d22",
        "remaining": 1,  # 2 favorites -> 1 after removing one
    }


def test_remove_favorite_raises_when_tcin_not_favorited():
    client, calls = _client_for_remove(FAVORITES_PAYLOAD, {"ok": True, "status": 200, "body": ""})
    with pytest.raises(ClientError):
        client.remove_favorite("00000000")
    assert calls["urls"] == []  # never issued a DELETE for a non-favorite


def test_remove_favorite_raises_loud_on_delete_failure():
    client, _calls = _client_for_remove(
        FAVORITES_PAYLOAD, {"ok": False, "status": 500, "body": "boom"}
    )
    with pytest.raises(ClientError):
        client.remove_favorite("94962117")


def test_remove_favorite_raises_when_delete_unauthorized():
    client, _calls = _client_for_remove(
        FAVORITES_PAYLOAD, {"ok": False, "status": 401, "body": "unauthorized"}
    )
    with pytest.raises(ClientError):
        client.remove_favorite("94962117")


def test_remove_favorite_raises_when_favorite_has_no_list_item_id():
    payload = {"list_items": [{"tcin": "555", "added_ts": "2026-01-01T00:00:00Z"}], "items_count": 1}
    client, calls = _client_for_remove(payload, {"ok": True, "status": 200, "body": ""})
    with pytest.raises(ClientError):
        client.remove_favorite("555")
    assert calls["urls"] == []  # can't DELETE without a membership id
