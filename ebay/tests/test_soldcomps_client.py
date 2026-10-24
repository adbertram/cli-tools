"""Contract tests for the SoldComps-backed marketplace search client.

These lock the parts of the integration a caller can observe: the query string
sent to ``/v1/scrape``, the item -> ``SearchResult`` mapping every downstream
script reads, the sort translation (including the two orders SoldComps cannot
produce), the pagination/quota accounting, and one actionable message per
documented error status.
"""

import json

import pytest

from ebay_cli import soldcomps_client as soldcomps_module
from ebay_cli.soldcomps_client import (
    API_KEY_SECRET_NAME,
    MAX_COUNT_PER_REQUEST,
    SEARCH_MAX_RESULTS,
    SoldCompsClient,
    SoldCompsError,
    map_item,
    raise_for_status,
    resolve_sort_order,
)


# ---------------------------------------------------------------- test doubles


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, status_code=200, payload=None, headers=None, text=None, url=""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.headers = headers or {}
        self.url = url
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Records every request and replays queued responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        if not self._responses:
            raise AssertionError(f"unexpected extra request: {params}")
        return self._responses.pop(0)

    def close(self):
        self.closed = True


class FakeConfig:
    """Config surface the client touches: a storage dir and credential types."""

    CREDENTIAL_TYPES = []

    def __init__(self, storage_dir):
        self.storage_dir = storage_dir


def sold_item(**overrides):
    item = {
        "itemId": 226554128899,
        "title": "LEGO Star Wars 75192 Millennium Falcon UCS",
        "url": "https://www.ebay.com/itm/226554128899",
        "thumbnailUrl": "https://i.ebayimg.com/thumbs/abc.jpg",
        "condition": "Used",
        "buyingFormat": "buyItNow",
        "bidCount": None,
        "listingType": "sold",
        "shippingPrice": 24.5,
        "sellerUsername": "brickseller99",
        "endedAt": "2026-08-30",
        "soldPrice": 612,
        "soldCurrency": "USD",
    }
    item.update(overrides)
    return item


def active_item(**overrides):
    item = {
        "itemId": "127992747834",
        "title": "LEGO bulk lot 5 lbs",
        "url": "https://www.ebay.com/itm/127992747834",
        "thumbnailUrl": None,
        "condition": "Used",
        "buyingFormat": "auction",
        "bidCount": 7,
        "listingType": "active",
        "shippingPrice": 0,
        "sellerUsername": "bulkbricks",
        "timeLeft": "6d 4h left",
        "currentPrice": 41.25,
        "currentCurrency": "USD",
    }
    item.update(overrides)
    return item


def envelope(items, has_next_page=False, page=1):
    return {
        "keyword": "LEGO 75192",
        "page": page,
        "totalItems": len(items),
        "totalResults": str(len(items)),
        "hasNextPage": has_next_page,
        "autoSelectedCategory": None,
        "items": items,
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client with a stubbed API key and no real HTTP session."""
    monkeypatch.setattr(
        soldcomps_module, "read_cli_tool_secret", lambda name: "sc_test_key"
    )
    return SoldCompsClient(config=FakeConfig(tmp_path))


def install_session(client, *responses):
    session = FakeSession(responses)
    client._session = session
    return session


# ---------------------------------------------------------------- sort mapping


@pytest.mark.parametrize(
    "sort,desc,active,expected",
    [
        ("newest", False, False, "endedRecently"),
        ("newest", False, True, "timeNewlyListed"),
        ("price", False, False, "pricePlusPostageLowest"),
        ("price", False, True, "pricePlusPostageLowest"),
        ("price", True, False, "pricePlusPostageHighest"),
        ("price", True, True, "pricePlusPostageHighest"),
    ],
)
def test_resolve_sort_order_maps_every_supported_combination(sort, desc, active, expected):
    assert resolve_sort_order(sort, desc, active=active) == expected


def test_sort_ending_on_sold_comps_names_the_removed_capability():
    with pytest.raises(ValueError) as exc:
        resolve_sort_order("ending", False, active=False)
    assert "ending soonest" in str(exc.value)
    assert "--sort newest" in str(exc.value)


def test_sort_ending_on_active_listings_names_the_removed_capability():
    """The active-listing case is a real capability loss, not a typo."""
    with pytest.raises(ValueError) as exc:
        resolve_sort_order("ending", False, active=True)
    assert "ending soonest" in str(exc.value)


def test_unknown_sort_field_lists_the_valid_values():
    with pytest.raises(ValueError) as exc:
        resolve_sort_order("popularity", False)
    assert "newest" in str(exc.value) and "price" in str(exc.value)


def test_desc_is_rejected_for_newest():
    with pytest.raises(ValueError) as exc:
        resolve_sort_order("newest", True)
    assert "--sort price" in str(exc.value)


# ------------------------------------------------------------ parameter building


def test_build_params_sends_the_documented_defaults(client):
    params = client.build_params(keywords="LEGO 75192", sold=True, page=1, count=50)
    assert params == {
        "keyword": "LEGO 75192",
        "count": "50",
        "page": "1",
        "categoryId": "0",
        "sortOrder": "endedRecently",
        "sold": "true",
        "exactMatch": "true",
    }


def test_build_params_maps_every_cli_option(client):
    params = client.build_params(
        keywords="LEGO bulk lot",
        sold=False,
        page=3,
        count=200,
        listing_format="bin",
        min_price=10.0,
        max_price=99.5,
        category="19006",
        condition="used",
        us_only=True,
        sort_order="timeNewlyListed",
    )
    assert params["sold"] == "false"
    assert params["page"] == "3"
    assert params["count"] == "200"
    assert params["buyingFormat"] == "buyItNow"
    assert params["minPrice"] == "10.0"
    assert params["maxPrice"] == "99.5"
    assert params["categoryId"] == "19006"
    assert params["conditionId"] == "3000"
    assert params["itemLocation"] == "domestic"
    assert params["sortOrder"] == "timeNewlyListed"


def test_build_params_passes_a_raw_condition_id_through(client):
    params = client.build_params(
        keywords="x", sold=True, page=1, count=10, condition="2750"
    )
    assert params["conditionId"] == "2750"


def test_build_params_omits_item_location_when_not_us_only(client):
    params = client.build_params(keywords="x", sold=True, page=1, count=10)
    assert "itemLocation" not in params


def test_build_params_rejects_an_unknown_listing_format(client):
    with pytest.raises(SoldCompsError) as exc:
        client.build_params(
            keywords="x", sold=False, page=1, count=10, listing_format="classified"
        )
    assert "bin, auction, all" in str(exc.value)


def test_search_sends_the_bearer_key(client):
    session = install_session(client, FakeResponse(payload=envelope([sold_item()])))
    client.search_sold(keywords="LEGO 75192", limit=5)
    assert session.calls[0]["headers"]["Authorization"] == "Bearer sc_test_key"


# ----------------------------------------------------------------- field mapping


def test_map_item_maps_every_sold_field():
    result = map_item(sold_item())
    assert result.to_dict() == {
        "item_id": "226554128899",
        "title": "LEGO Star Wars 75192 Millennium Falcon UCS",
        "price": "612.00",
        "currency": "USD",
        "shipping_price": "24.50",
        "status": "sold",
        "date_sold": "2026-08-30",
        "condition": "Used",
        "format": "Buy It Now",
        "url": "https://www.ebay.com/itm/226554128899",
        "image_url": "https://i.ebayimg.com/thumbs/abc.jpg",
        "seller": "brickseller99",
    }


def test_map_item_maps_every_active_field():
    result = map_item(active_item())
    data = result.to_dict()
    assert data["status"] == "active"
    assert data["price"] == "41.25"
    assert data["currency"] == "USD"
    assert data["time_left"] == "6d 4h left"
    assert data["bids"] == 7
    assert data["format"] == "Auction"
    assert data["shipping_price"] == "0.00"
    assert "date_sold" not in data


def test_map_item_translates_buying_format_to_the_cli_vocabulary():
    """Callers filter on these exact labels (e.g. format == "Auction")."""
    assert map_item(sold_item(buyingFormat="auction")).format == "Auction"
    assert map_item(sold_item(buyingFormat="auctionWithBIN")).format == "Auction"
    assert map_item(sold_item(buyingFormat="buyItNow")).format == "Buy It Now"
    assert map_item(sold_item(buyingFormat="acceptsOffers")).format == "Best Offer"


def test_map_item_rejects_an_unknown_buying_format():
    with pytest.raises(SoldCompsError) as exc:
        map_item(sold_item(buyingFormat="lottery"))
    assert "buyingFormat" in str(exc.value)


def test_map_item_rejects_an_unknown_listing_type():
    with pytest.raises(SoldCompsError) as exc:
        map_item(sold_item(listingType="pending"))
    assert "listingType" in str(exc.value)


@pytest.mark.parametrize("field", ["itemId", "title", "url", "soldPrice", "soldCurrency"])
def test_map_item_fails_loudly_on_a_missing_required_field(field):
    item = sold_item()
    item[field] = None
    with pytest.raises(SoldCompsError) as exc:
        map_item(item)
    assert field in str(exc.value)


def test_map_item_keeps_optional_fields_absent_rather_than_guessing():
    item = sold_item(shippingPrice=None, condition=None, buyingFormat=None, sellerUsername=None)
    result = map_item(item)
    assert result.shipping_price is None
    assert result.condition is None
    assert result.format is None
    assert result.seller is None


def test_map_item_rejects_a_non_numeric_price():
    with pytest.raises(SoldCompsError) as exc:
        map_item(sold_item(soldPrice="six hundred"))
    assert "soldPrice" in str(exc.value)


# -------------------------------------------------------------------- pagination


def test_search_stops_at_one_request_when_the_limit_fits_one_page(client):
    session = install_session(
        client, FakeResponse(payload=envelope([sold_item()], has_next_page=True))
    )
    results = client.search_sold(keywords="LEGO 75192", limit=50)
    assert len(session.calls) == 1
    assert session.calls[0]["params"]["count"] == "50"
    assert len(results) == 1


def test_search_pages_until_the_limit_is_filled(client):
    first = [sold_item(itemId=i) for i in range(MAX_COUNT_PER_REQUEST)]
    second = [sold_item(itemId=1000 + i) for i in range(MAX_COUNT_PER_REQUEST)]
    session = install_session(
        client,
        FakeResponse(payload=envelope(first, has_next_page=True, page=1)),
        FakeResponse(payload=envelope(second, has_next_page=True, page=2)),
    )
    results = client.search_sold(keywords="LEGO 75192", limit=250)

    assert [call["params"]["page"] for call in session.calls] == ["1", "2"]
    # One page size for the whole search: `page` indexes windows of `count`.
    assert {call["params"]["count"] for call in session.calls} == {"200"}
    assert len(results) == 250


def test_search_stops_early_when_the_api_reports_no_next_page(client):
    session = install_session(
        client,
        FakeResponse(
            payload=envelope([sold_item()], has_next_page=False, page=1)
        ),
    )
    results = client.search_sold(keywords="LEGO 75192", limit=400)
    assert len(session.calls) == 1
    assert len(results) == 1


def test_search_warns_what_a_multi_page_limit_will_cost(client, monkeypatch):
    notes = []
    monkeypatch.setattr(soldcomps_module, "print_info", notes.append)
    install_session(
        client,
        FakeResponse(payload=envelope([sold_item()], has_next_page=False)),
    )
    client.search_sold(keywords="LEGO 75192", limit=400)

    assert len(notes) == 1
    assert "2 SoldComps requests" in notes[0]
    assert "monthly quota" in notes[0]


def test_search_says_nothing_when_one_request_covers_the_limit(client, monkeypatch):
    notes = []
    monkeypatch.setattr(soldcomps_module, "print_info", notes.append)
    install_session(client, FakeResponse(payload=envelope([sold_item()])))
    client.search_sold(keywords="LEGO 75192", limit=50)
    assert notes == []


def test_search_rejects_a_limit_above_the_result_ceiling(client):
    with pytest.raises(SoldCompsError) as exc:
        client.search_sold(keywords="LEGO 75192", limit=SEARCH_MAX_RESULTS + 1)
    assert str(SEARCH_MAX_RESULTS) in str(exc.value)


def test_search_rejects_a_limit_below_one(client):
    with pytest.raises(SoldCompsError):
        client.search_sold(keywords="LEGO 75192", limit=0)


def test_search_rejects_a_response_without_an_items_array(client):
    install_session(client, FakeResponse(payload={"keyword": "x", "page": 1}))
    with pytest.raises(SoldCompsError) as exc:
        client.search_sold(keywords="LEGO 75192", limit=5)
    assert "items array" in str(exc.value)


# ------------------------------------------------------------------- quota state


def test_every_response_records_the_plan_usage_headers(client):
    install_session(
        client,
        FakeResponse(
            payload=envelope([sold_item()]),
            headers={
                "X-Usage-Limit": "2000",
                "X-Usage-Remaining": "1873",
                "X-Usage-Reset": "1790000000",
                "X-RateLimit-Limit": "60",
                "X-RateLimit-Remaining": "59",
                "X-RateLimit-Reset": "1789000060",
            },
        ),
    )
    client.search_sold(keywords="LEGO 75192", limit=5)

    usage = client.read_usage()
    assert usage["quota_limit"] == "2000"
    assert usage["quota_remaining"] == "1873"
    assert usage["rate_limit_remaining"] == "59"
    assert "recorded_at" in usage


def test_reading_usage_before_any_search_says_so(client):
    with pytest.raises(SoldCompsError) as exc:
        client.read_usage()
    assert "run a search" in str(exc.value)


def test_usage_is_recorded_even_when_the_request_fails(client):
    """A 429 is exactly when the recorded quota matters most."""
    install_session(
        client,
        FakeResponse(
            status_code=429,
            payload={"code": "quota_exceeded", "message": "gone"},
            headers={"X-Usage-Remaining": "0", "Retry-After": "3600"},
        ),
    )
    with pytest.raises(SoldCompsError):
        client.search_sold(keywords="LEGO 75192", limit=5)
    assert client.read_usage()["quota_remaining"] == "0"


# ------------------------------------------------------------------ error status


def test_missing_api_key_points_at_the_secret_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(soldcomps_module, "read_cli_tool_secret", lambda name: None)
    bare = SoldCompsClient(config=FakeConfig(tmp_path))
    with pytest.raises(SoldCompsError) as exc:
        bare.search_sold(keywords="LEGO 75192", limit=5)
    message = str(exc.value)
    assert API_KEY_SECRET_NAME in message
    assert "secrets.sh set" in message


def test_401_points_at_the_secret_manager():
    with pytest.raises(SoldCompsError) as exc:
        raise_for_status(FakeResponse(status_code=401, payload={"message": "bad key"}))
    assert "secrets.sh set" in str(exc.value)
    assert API_KEY_SECRET_NAME in str(exc.value)


def test_400_surfaces_the_rejected_parameters():
    with pytest.raises(SoldCompsError) as exc:
        raise_for_status(
            FakeResponse(status_code=400, payload={"message": "count must be 1-200"})
        )
    assert "count must be 1-200" in str(exc.value)


def test_429_quota_exceeded_is_distinct_from_rate_limited():
    with pytest.raises(SoldCompsError) as exc:
        raise_for_status(
            FakeResponse(
                status_code=429,
                payload={"code": "quota_exceeded", "message": "monthly quota gone"},
                headers={"Retry-After": "3600", "X-RateLimit-Reset": "1790000000"},
            )
        )
    message = str(exc.value)
    assert "monthly quota is exhausted" in message
    assert "Retry-After=3600s" in message
    assert "ebay quota" in message


def test_429_rate_limited_says_the_monthly_quota_is_unaffected():
    with pytest.raises(SoldCompsError) as exc:
        raise_for_status(
            FakeResponse(
                status_code=429,
                payload={"code": "rate_limited", "message": "slow down"},
                headers={"Retry-After": "12"},
            )
        )
    message = str(exc.value)
    assert "per-minute rate limit" in message
    assert "monthly quota is unaffected" in message


def test_502_names_the_upstream_ebay_block():
    with pytest.raises(SoldCompsError) as exc:
        raise_for_status(
            FakeResponse(status_code=502, payload={"message": "upstream blocked"})
        )
    assert "eBay blocked the upstream fetch" in str(exc.value)


def test_503_names_the_concurrency_limit():
    with pytest.raises(SoldCompsError) as exc:
        raise_for_status(FakeResponse(status_code=503, payload={"message": "busy"}))
    assert "concurrency limit" in str(exc.value)


def test_500_is_reported_as_a_server_error():
    with pytest.raises(SoldCompsError) as exc:
        raise_for_status(FakeResponse(status_code=500, payload={"message": "boom"}))
    assert "server error" in str(exc.value)


def test_an_unexpected_status_still_reports_its_code_and_body():
    with pytest.raises(SoldCompsError) as exc:
        raise_for_status(
            FakeResponse(status_code=418, payload=None, text="I am a teapot")
        )
    assert "418" in str(exc.value)
    assert "teapot" in str(exc.value)


def test_a_non_json_success_body_is_an_error_not_an_empty_result(client):
    install_session(client, FakeResponse(payload=None, text="<html>nope</html>"))
    with pytest.raises(SoldCompsError) as exc:
        client.search_sold(keywords="LEGO 75192", limit=5)
    assert "non-JSON" in str(exc.value)
