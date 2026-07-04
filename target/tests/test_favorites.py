"""Tests for the favorites (account "lists") read.

Covers the two pure/decidable layers so behavior is verifiable without a live
browser:

- ``normalize_favorites`` maps the ``favorites/v1/list_items`` envelope (captured
  live from the randafaith account) into flat favorite records.
- ``_hydrate_favorite`` enriches a favorite TCIN via the existing redsky
  ``get_item`` path and — critically — degrades a delisted favorite (redsky
  raises ``ClientError``) to an ``available: False`` record instead of dropping
  the whole list.
- ``list_favorites`` orchestrates fetch -> normalize -> ``--limit`` slice ->
  hydrate.

The exact ``list_items`` shapes below are copied from the real favorites API
response for the randafaith account (see the migrated 2021 favorite, which omits
``item_note`` and is now delisted).
"""
import pytest

from target_cli.client import ClientError, TargetClient
from target_cli.parsers import normalize_favorites


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

def _client_with_get_item(get_item):
    client = TargetClient.__new__(TargetClient)
    client.get_item = get_item  # type: ignore[assignment]
    return client


def test_hydrate_favorite_enriches_from_get_item():
    detail = {
        "id": "94962117",
        "title": "LoveShackFancy Tote Bag",
        "price": "$34.99",
        "brand": "LoveShackFancy",
        "url": "https://www.target.com/p/-/A-94962117",
        "rating": 4.5,
    }
    client = _client_with_get_item(lambda tcin: detail)
    row = client._hydrate_favorite({"tcin": "94962117", "added": "2026-07-03T21:10:14Z", "note": None})
    assert row == {
        "id": "94962117",
        "title": "LoveShackFancy Tote Bag",
        "price": "$34.99",
        "available": True,
        "added": "2026-07-03T21:10:14Z",
        "note": None,
        "brand": "LoveShackFancy",
        "url": "https://www.target.com/p/-/A-94962117",
        "rating": 4.5,
    }


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
        "added": "2021-09-25T12:57:05Z",
        "note": None,
    }
    # A degraded record must NOT carry the enrichment-only fields.
    assert "brand" not in row and "url" not in row


# --- list_favorites: fetch -> slice(limit) -> hydrate ----------------------

def _client_for_list(payload, get_item):
    client = TargetClient.__new__(TargetClient)
    # Accept the optional page kwarg the real method takes (remove/get reuse it).
    client._fetch_favorites_payload = lambda *, page=None: payload  # type: ignore[assignment]
    client.get_item = get_item  # type: ignore[assignment]
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
