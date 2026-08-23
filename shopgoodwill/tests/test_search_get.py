import json

import pytest
import typer
from typer.testing import CliRunner

from shopgoodwill_cli.client import ClientError, ShopGoodwillClient
from shopgoodwill_cli.commands import search


runner = CliRunner()


# --- Source-CLI Sort Standard --------------------------------------------------


def test_sort_fields_use_verified_integer_columns():
    """SORT_FIELDS maps the canonical vocab to the integer sortColumn values
    verified from the live ShopGoodwill sort dropdown (col, natural descending)."""
    assert search.SORT_FIELDS == {
        "newest": (1, True),    # "Newly Listed" = EndingDate (1) descending
        "price": (4, False),    # BidPrice (4) ascending = low -> high
        "ending": (1, False),   # EndingDate (1) ascending = ending soonest
        "bids": (3, False),     # NumberofBids (3) ascending = fewest first
    }


def test_resolve_sort_default_newest_is_ending_date_descending():
    """Default --sort (newest, no --desc) -> sortColumn 1, descending True."""
    assert search._resolve_sort("newest", False) == (1, True)


def test_resolve_sort_desc_flips_each_field_natural_direction():
    """--desc reverses each field's natural direction (sortDescending boolean)."""
    assert search._resolve_sort("newest", True) == (1, False)
    assert search._resolve_sort("price", False) == (4, False)
    assert search._resolve_sort("price", True) == (4, True)
    assert search._resolve_sort("ending", False) == (1, False)
    assert search._resolve_sort("ending", True) == (1, True)
    assert search._resolve_sort("bids", False) == (3, False)
    assert search._resolve_sort("bids", True) == (3, True)


def test_resolve_sort_is_case_insensitive():
    assert search._resolve_sort("NEWEST", False) == (1, True)


def test_resolve_sort_rejects_unknown_field():
    """Unknown --sort value fails fast with valid values listed (no fallback)."""
    with pytest.raises(typer.BadParameter) as exc:
        search._resolve_sort("bogus", False)
    message = str(exc.value)
    assert "bogus" in message
    for field in ("newest", "price", "ending", "bids"):
        assert field in message


def test_search_query_unknown_sort_exits_nonzero():
    """`search query ... --sort bogus` exits non-zero before any network call."""
    result = runner.invoke(search.app, ["query", "lego", "--sort", "bogus"])
    assert result.exit_code != 0


class _RecencyClient:
    """Fake client whose recency window returns items with scrambled startTimes."""

    LATEST = "2026-07-24T10:00:00"
    MIDDLE = "2026-07-22T10:00:00"
    OLDEST = "2026-07-20T10:00:00"

    def __init__(self, require_auth=False):
        self.calls = []

    def search_recency_window(self, query, limit, offset=0, sort_descending=True, **kwargs):
        self.calls.append({"limit": limit, "offset": offset, "sort_descending": sort_descending})
        # Client is responsible for ordering by startTime; mirror real client.
        items = [
            {"itemId": 3, "startTime": self.OLDEST, "currentPrice": 3.0, "title": "c",
             "numBids": 0, "endTime": "", "sellerCity": "", "sellerState": ""},
            {"itemId": 1, "startTime": self.LATEST, "currentPrice": 1.0, "title": "a",
             "numBids": 0, "endTime": "", "sellerCity": "", "sellerState": ""},
            {"itemId": 2, "startTime": self.MIDDLE, "currentPrice": 2.0, "title": "b",
             "numBids": 0, "endTime": "", "sellerCity": "", "sellerState": ""},
        ]
        items.sort(key=lambda it: it["startTime"], reverse=sort_descending)
        return items, 3


def test_search_query_newest_refines_by_start_time_descending(monkeypatch):
    """--sort newest returns items in descending startTime (real listing date)."""
    monkeypatch.setattr(search, "ShopGoodwillClient", _RecencyClient)

    result = runner.invoke(search.app, ["query", "lego", "--sort", "newest"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    starts = [i["startTime"] for i in data["items"]]
    assert starts == sorted(starts, reverse=True)
    # newest listed (2026-07-24) first, oldest (2026-07-20) last
    assert [i["itemId"] for i in data["items"]] == [1, 2, 3]


# --- Pagination regression (--page/-p was silently ignored for --sort newest) --


class _LargeRecencyClient:
    """Fake client whose recency window returns a large, already-sorted set of
    items so --page slicing can be exercised without a live API call."""

    TOTAL_ITEMS = 120

    def __init__(self, require_auth=False):
        self.calls = []

    def search_recency_window(self, query, limit, offset=0, sort_descending=True, **kwargs):
        self.calls.append({"limit": limit, "offset": offset})
        # itemId N has the Nth-newest startTime; index 0 is newest.
        items = [
            {"itemId": i, "startTime": f"2026-07-{24 - (i % 20):02d}T00:00:00",
             "currentPrice": 1.0, "title": f"item-{i}", "numBids": 0,
             "endTime": "", "sellerCity": "", "sellerState": ""}
            for i in range(self.TOTAL_ITEMS)
        ]
        return items, self.TOTAL_ITEMS


def test_search_query_newest_page_2_returns_different_items_than_page_1(monkeypatch):
    """Regression: --sort newest --page 2 must return a materially different
    item set than --page 1 (previously --page was silently ignored and both
    pages, and the response's own "page" field, always reflected page 1)."""
    monkeypatch.setattr(search, "ShopGoodwillClient", _LargeRecencyClient)

    result_p1 = runner.invoke(
        search.app, ["query", "lego", "--sort", "newest", "--limit", "40", "--page", "1"]
    )
    result_p2 = runner.invoke(
        search.app, ["query", "lego", "--sort", "newest", "--limit", "40", "--page", "2"]
    )

    assert result_p1.exit_code == 0
    assert result_p2.exit_code == 0
    data_p1 = json.loads(result_p1.stdout)
    data_p2 = json.loads(result_p2.stdout)

    ids_p1 = [i["itemId"] for i in data_p1["items"]]
    ids_p2 = [i["itemId"] for i in data_p2["items"]]

    assert ids_p1 != ids_p2
    assert set(ids_p1).isdisjoint(set(ids_p2))
    assert ids_p1 == list(range(0, 40))
    assert ids_p2 == list(range(40, 80))

    # The response's own "page" field must reflect the actually requested page.
    assert data_p1["page"] == 1
    assert data_p2["page"] == 2


def test_search_query_newest_passes_page_offset_to_recency_window(monkeypatch):
    """--page N must translate to offset (N - 1) * limit passed to the client."""
    client_holder = {}

    class _CapturingClient(_LargeRecencyClient):
        def __init__(self, require_auth=False):
            super().__init__(require_auth)
            client_holder["client"] = self

    monkeypatch.setattr(search, "ShopGoodwillClient", _CapturingClient)

    result = runner.invoke(
        search.app, ["query", "lego", "--sort", "newest", "--limit", "25", "--page", "3"]
    )

    assert result.exit_code == 0
    assert client_holder["client"].calls == [{"limit": 25, "offset": 50}]


def test_client_recency_window_sorts_by_start_time(monkeypatch):
    """client.search_recency_window sorts the fetched window by startTime."""
    client = ShopGoodwillClient(require_auth=False)

    def fake_search(query, page, page_size, sort_column, sort_descending, **kwargs):
        assert sort_column == 1  # always the EndingDate/"Newly Listed" column
        if page > 1:
            return {"searchResults": {"itemCount": 3, "items": []}}
        return {"searchResults": {"itemCount": 3, "items": [
            {"itemId": 3, "startTime": "2026-07-20T00:00:00"},
            {"itemId": 1, "startTime": "2026-07-24T00:00:00"},
            {"itemId": 2, "startTime": "2026-07-22T00:00:00"},
        ]}}

    monkeypatch.setattr(client, "search", fake_search)
    items, total = client.search_recency_window(query="lego", limit=10, sort_descending=True)

    assert total == 3
    assert [i["itemId"] for i in items] == [1, 2, 3]  # startTime descending


def test_client_recency_window_fetches_enough_pages_to_cover_offset(monkeypatch):
    """A requested offset beyond one API page must pull additional pages so the
    window actually contains items at that offset (regression for --page)."""
    client = ShopGoodwillClient(require_auth=False)
    pages_fetched = []

    def fake_search(query, page, page_size, sort_column, sort_descending, **kwargs):
        pages_fetched.append(page)
        start = (page - 1) * page_size
        items = [
            {"itemId": i, "startTime": f"2026-07-{(200 - i):03d}T00:00:00"}
            for i in range(start, start + page_size)
        ]
        return {"searchResults": {"itemCount": 500, "items": items}}

    monkeypatch.setattr(client, "search", fake_search)
    # page 3 at limit 40 -> offset 80; needs items[80:120] to exist.
    items, total = client.search_recency_window(
        query="lego", limit=40, offset=80, sort_descending=True
    )

    assert total == 500
    assert len(items) >= 120
    assert max(pages_fetched) >= 3


def test_client_recency_window_caps_at_max_items_ceiling(monkeypatch):
    """The recency window never exceeds _RECENCY_MAX_ITEMS (200) fetched items,
    even when offset + limit requests far more (verified live: --limit 500
    against a 506-result query still returned exactly 200 unique items)."""
    client = ShopGoodwillClient(require_auth=False)

    def fake_search(query, page, page_size, sort_column, sort_descending, **kwargs):
        start = (page - 1) * page_size
        items = [{"itemId": i, "startTime": f"item-{i}"} for i in range(start, start + page_size)]
        return {"searchResults": {"itemCount": 5000, "items": items}}

    monkeypatch.setattr(client, "search", fake_search)
    items, total = client.search_recency_window(
        query="lego", limit=500, offset=0, sort_descending=True
    )

    assert total == 5000
    assert len(items) == client._RECENCY_MAX_ITEMS == 200


class _FakeClient:
    def __init__(self, require_auth=False):
        self.require_auth = require_auth

    def get_item(self, item_id):
        return {
            "itemId": item_id,
            "title": "Bulk LEGO Assorted Building Bricks 25.8 lbs",
            "currentPrice": 14.99,
            "buyNowPrice": 49.99,
            "numBids": 0,
            "endTime": "2026-06-17T16:05:00",
            "sellerName": "Goodwill",
            "sellerCity": "Rockville",
            "sellerState": "MD",
            "sellerId": 43,
            "allowShippingCalculation": True,
            "displayWeight": 25.8,
        }

    def calculate_shipping(self, item):
        return {
            "destinationZip": "47725",
            "shippingPrice": 19.67,
            "handlingPrice": 3.00,
            "total": 22.67,
            "serviceDescription": "GROUND_HOME_DELIVERY",
        }


class _NoBuyNowClient(_FakeClient):
    def get_item(self, item_id):
        item = super().get_item(item_id)
        item["buyNowPrice"] = 0
        return item


class _ExpiredAuctionClient(_FakeClient):
    def get_item(self, item_id):
        item = super().get_item(item_id)
        item["buyNowPrice"] = 0
        item["isItemEndTimeExpire"] = True
        item["remainingTime"] = "Auction Ended"
        return item


class _ExpiredAuctionWithBinClient(_FakeClient):
    def get_item(self, item_id):
        item = super().get_item(item_id)
        item["isItemEndTimeExpire"] = True
        item["remainingTime"] = "Auction Ended"
        return item


class _NoShippingCalculationClient(_FakeClient):
    def get_item(self, item_id):
        item = super().get_item(item_id)
        item["allowShippingCalculation"] = False
        return item

    def calculate_shipping(self, item):
        raise AssertionError("shipping should not be calculated")


class _ShippingCalculationFailureClient(_FakeClient):
    def calculate_shipping(self, item):
        raise ClientError("Shipping calculation failed: PACKAGE.WEIGHT.INVALID")


def test_search_get_table_shows_buy_now_price_when_available(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _FakeClient)

    result = runner.invoke(search.app, ["get", "267415400", "--table"])

    assert result.exit_code == 0
    assert "Current Price" in result.stdout
    assert "$14.99" in result.stdout
    assert "Buy Now Price" in result.stdout
    assert "$49.99" in result.stdout


def test_search_get_table_keeps_current_price_without_buy_now(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _NoBuyNowClient)

    result = runner.invoke(search.app, ["get", "267415400", "--table"])

    assert result.exit_code == 0
    assert "Current Price" in result.stdout
    assert "$14.99" in result.stdout
    assert "Buy Now Price" not in result.stdout


def test_search_get_table_shows_destination_shipping_when_available(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _FakeClient)

    result = runner.invoke(search.app, ["get", "267415400", "--table"])

    assert result.exit_code == 0
    assert "Destination ZIP" in result.stdout
    assert "47725" in result.stdout
    assert "Destination Shipping" in result.stdout
    assert "$19.67" in result.stdout
    assert "Shipping + Handling" in result.stdout
    assert "$22.67" in result.stdout


def test_search_get_json_adds_destination_shipping_when_available(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _FakeClient)

    result = runner.invoke(search.app, ["get", "267415400"])

    assert result.exit_code == 0
    assert '"destinationZip": "47725"' in result.stdout
    assert '"shippingPrice": 19.67' in result.stdout
    assert '"total": 22.67' in result.stdout


def test_search_get_marks_expired_auction_unavailable_without_bin(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _ExpiredAuctionClient)

    result = runner.invoke(search.app, ["get", "267415400"])

    assert result.exit_code == 0
    assert '"available": false' in result.stdout


def test_search_get_marks_expired_auction_unavailable_even_with_bin(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _ExpiredAuctionWithBinClient)

    result = runner.invoke(search.app, ["get", "267415400"])

    assert result.exit_code == 0
    assert '"available": false' in result.stdout


def test_search_get_does_not_calculate_shipping_when_unavailable(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _NoShippingCalculationClient)

    result = runner.invoke(search.app, ["get", "267415400"])

    assert result.exit_code == 0
    assert "shippingEstimate" not in result.stdout


def test_search_get_returns_item_when_shipping_calculation_fails(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _ShippingCalculationFailureClient)

    result = runner.invoke(search.app, ["get", "267415400"])

    assert result.exit_code == 0
    assert '"itemId": 267415400' in result.stdout
    assert '"shippingEstimate": null' in result.stdout
    assert '"shippingEstimateUnavailable": true' in result.stdout
    assert "PACKAGE.WEIGHT.INVALID" in result.stdout


def test_calculate_shipping_parses_shopgoodwill_estimate_response(monkeypatch):
    class _Response:
        status_code = 200
        text = (
            "<p>Estimated Shipping and Handling:</p>"
            "<p>Shipping: <span id='shipping-span'>$19.67 (GROUND_HOME_DELIVERY)</span></p>"
            "<p>Handling: $3.00</p>"
            "<p><b>Total Shipping and Handling: $22.67</b></p>"
        )

    captured = {}

    def post(url, json):
        captured["url"] = url
        captured["json"] = json
        return _Response()

    client = ShopGoodwillClient(require_auth=False)
    monkeypatch.setattr(client.session, "post", post)

    result = client.calculate_shipping({
        "itemId": 267415400,
        "sellerId": 43,
        "displayWeight": 25.8,
        "handlingPrice": 3.0,
    })

    assert captured["url"].endswith("/ItemDetail/CalculateShipping")
    assert captured["json"] == {
        "itemId": 267415400,
        "sellerId": 43,
        "zipCode": "47725",
        "country": "US",
        "packageWeight": 25.8,
        "quantity": 1,
    }
    assert result == {
        "destinationZip": "47725",
        "country": "US",
        "shippingPrice": 19.67,
        "handlingPrice": 3.0,
        "total": 22.67,
        "serviceDescription": "GROUND_HOME_DELIVERY",
    }
