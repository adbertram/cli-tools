"""Sort, condition, validation, and pagination contract tests."""

import tempfile
from pathlib import Path

import pytest
from cli_tools_shared.http_session import RequestsRetryPolicy

from vinted_cli.client import (
    BARREN_PAGE_LIMIT,
    MAX_LIMIT,
    MAX_PAGES,
    MAX_PER_PAGE,
    VintedClient,
    resolve_condition_ids,
    resolve_item_id,
    resolve_order,
    resolve_price_range,
    sort_newest_first,
)

# The empty-result path calls data_cache.invalidate, which needs a storage dir.
_STORAGE_DIR = Path(tempfile.mkdtemp(prefix="vinted-tests-"))


class _StubConfig:
    CREDENTIAL_TYPES = []
    storage_dir = _STORAGE_DIR


class _RecordingClient(VintedClient):
    """Client that records request parameters instead of calling Vinted.

    The `@cached` decorator is bypassed so the tests exercise the real paging
    logic without touching the on-disk cache.
    """

    def __init__(self, pages):
        self.config = _StubConfig()
        self.base_url = "https://www.vinted.com"
        self.retry_policy = RequestsRetryPolicy(max_retries=0)
        self._session = None
        self._pages = pages
        self.calls = []

    def _search_pages(self, marketplace, params, limit):
        return VintedClient._search_pages.__wrapped__(self, marketplace, params, limit)

    def _json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self._pages[len(self.calls) - 1]


def _page(count, page, total_pages, start=0):
    return {
        "items": [{"id": start + index} for index in range(count)],
        "pagination": {"current_page": page, "total_pages": total_pages},
    }


# --- sort vocabulary -------------------------------------------------------

def test_resolve_order_maps_the_canonical_vocabulary():
    assert resolve_order("newest", False) == "newest_first"
    assert resolve_order("price", False) == "price_low_to_high"
    assert resolve_order("price", True) == "price_high_to_low"
    assert resolve_order("relevance", False) == "relevance"


def test_resolve_order_is_case_insensitive():
    assert resolve_order("NEWEST", False) == "newest_first"


def test_resolve_order_rejects_an_unknown_field():
    with pytest.raises(ValueError, match="Invalid --sort 'bogus'"):
        resolve_order("bogus", False)


@pytest.mark.parametrize("field", ["newest", "relevance"])
def test_resolve_order_rejects_desc_where_vinted_has_no_reverse(field):
    with pytest.raises(ValueError, match="--desc is not available"):
        resolve_order(field, True)


# --- condition vocabulary --------------------------------------------------

def test_resolve_condition_ids_maps_names_to_status_ids():
    assert resolve_condition_ids(["new-with-tags"]) == "6"
    assert resolve_condition_ids(["good", "very-good"]) == "3,2"


def test_resolve_condition_ids_returns_none_without_conditions():
    assert resolve_condition_ids(None) is None
    assert resolve_condition_ids([]) is None


def test_resolve_condition_ids_rejects_an_unknown_condition():
    with pytest.raises(ValueError, match="Invalid --condition 'mint'"):
        resolve_condition_ids(["mint"])


# --- listing ID validation -------------------------------------------------

def test_resolve_item_id_accepts_a_numeric_id():
    assert resolve_item_id("9571854910") == "9571854910"


@pytest.mark.parametrize(
    "bad_id",
    [
        "../../../etc/passwd",
        "9571854910/../../members",
        "9571854910?x=1",
        "https://evil.example.com/x",
        "",
        "  9571854910  ",
        "9571854910\n",
        "abc",
        "-1",
        "12.5",
    ],
)
def test_resolve_item_id_rejects_anything_that_could_rewrite_the_path(bad_id):
    with pytest.raises(ValueError, match="Invalid listing ID"):
        resolve_item_id(bad_id)


def test_resolve_item_id_rejects_a_non_string():
    with pytest.raises(ValueError, match="Invalid listing ID"):
        resolve_item_id(None)


# --- price range validation ------------------------------------------------

def test_resolve_price_range_accepts_a_valid_range():
    assert resolve_price_range(5, 25) is None
    assert resolve_price_range(None, None) is None
    assert resolve_price_range(0, 0) is None


def test_resolve_price_range_rejects_a_negative_minimum():
    with pytest.raises(ValueError, match=r"--min-price must be 0 or more"):
        resolve_price_range(-1, None)


def test_resolve_price_range_rejects_a_negative_maximum():
    with pytest.raises(ValueError, match=r"--max-price must be 0 or more"):
        resolve_price_range(None, -1)


def test_resolve_price_range_rejects_an_inverted_range():
    with pytest.raises(ValueError, match="is greater than"):
        resolve_price_range(100, 5)


# --- newest-first default order --------------------------------------------

def _row(item_id, listed_at):
    return {"id": item_id, "listed_at": listed_at}


def test_sort_newest_first_orders_by_listing_time():
    rows = [
        _row(1, "2026-08-04T13:32:06+00:00"),
        _row(2, "2026-08-04T13:25:52+00:00"),
        _row(3, "2026-08-04T13:32:51+00:00"),
    ]

    assert [row["id"] for row in sort_newest_first(rows)] == [3, 1, 2]


def test_sort_newest_first_puts_undated_listings_last_in_vinted_order():
    rows = [
        _row(1, None),
        _row(2, "2026-08-04T13:25:52+00:00"),
        _row(3, None),
    ]

    assert [row["id"] for row in sort_newest_first(rows)] == [2, 1, 3]


def test_sort_newest_first_handles_an_empty_list():
    assert sort_newest_first([]) == []


def test_the_default_search_returns_strictly_newest_first():
    """Vinted injects listings out of order, so the CLI sorts the result.

    Verified live: the newest listing arrived sixth in Vinted's own order.
    """
    client = _RecordingClient([{
        "items": [
            {"id": 1, "photo": {"high_resolution": {"timestamp": 1785850326}}},
            {"id": 2, "photo": {"high_resolution": {"timestamp": 1785849952}}},
            {"id": 3, "photo": {"high_resolution": {"timestamp": 1785850371}}},
        ],
        "pagination": {"total_pages": 1},
    }])

    rows = client.search_listings(query="lego", limit=10)

    assert [row["id"] for row in rows] == [3, 1, 2]
    assert client.calls[0][1]["order"] == "newest_first"


def test_a_price_sorted_search_keeps_the_order_vinted_returned():
    """Only the newest default is re-sorted. Price order comes from the API."""
    client = _RecordingClient([{
        "items": [
            {"id": 1, "photo": {"high_resolution": {"timestamp": 1785850326}}},
            {"id": 2, "photo": {"high_resolution": {"timestamp": 1785849952}}},
            {"id": 3, "photo": {"high_resolution": {"timestamp": 1785850371}}},
        ],
        "pagination": {"total_pages": 1},
    }])

    rows = client.search_listings(query="lego", limit=10, order="price_low_to_high")

    assert [row["id"] for row in rows] == [1, 2, 3]


# --- search parameters -----------------------------------------------------

def test_search_sends_every_filter_to_the_api():
    client = _RecordingClient([_page(1, 1, 1)])

    client.search_listings(
        query="lego",
        limit=1,
        order="price_low_to_high",
        min_price=5,
        max_price=25,
        currency="USD",
        status_ids="6",
        catalog_ids="1920",
        brand_ids="12",
        size_ids="7",
        color_ids="3",
    )

    url, params = client.calls[0]
    assert url == "https://www.vinted.com/api/v2/catalog/items"
    assert params["search_text"] == "lego"
    assert params["order"] == "price_low_to_high"
    assert params["price_from"] == 5
    assert params["price_to"] == 25
    assert params["currency"] == "USD"
    assert params["status_ids"] == "6"
    assert params["catalog_ids"] == "1920"
    assert params["brand_ids"] == "12"
    assert params["size_ids"] == "7"
    assert params["color_ids"] == "3"


def test_search_omits_filters_that_were_not_supplied():
    client = _RecordingClient([_page(1, 1, 1)])

    client.search_listings(query="lego", limit=1)

    _, params = client.calls[0]
    for absent in ("price_from", "price_to", "currency", "status_ids", "catalog_ids"):
        assert absent not in params


def test_search_rejects_a_limit_below_one():
    client = _RecordingClient([])

    with pytest.raises(ValueError, match="--limit must be 1 or more"):
        client.search_listings(query="lego", limit=0)


def test_search_rejects_an_inverted_price_range_before_any_request():
    client = _RecordingClient([])

    with pytest.raises(ValueError, match="is greater than"):
        client.search_listings(query="lego", limit=5, min_price=100, max_price=5)

    assert client.calls == []


# --- cache isolation between marketplaces ----------------------------------

def test_search_passes_the_marketplace_into_the_cached_call():
    """The marketplace must be an argument so the cache key includes it.

    Without this, a cached search on vinted.com is served for vinted.co.uk.
    """
    recorded = {}

    class _MarketplaceClient(_RecordingClient):
        def _search_pages(self, marketplace, params, limit):
            recorded["marketplace"] = marketplace
            return []

    client = _MarketplaceClient([])
    client.base_url = "https://www.vinted.co.uk"
    client.search_listings(query="lego", limit=1)

    assert recorded["marketplace"] == "https://www.vinted.co.uk"


def test_get_listing_passes_the_marketplace_into_the_cached_call():
    recorded = {}

    class _MarketplaceClient(_RecordingClient):
        def _get_listing(self, marketplace, item_id):
            recorded["marketplace"] = marketplace
            recorded["item_id"] = item_id
            return {}

    client = _MarketplaceClient([])
    client.base_url = "https://www.vinted.fr"
    client.get_listing("9571854910")

    assert recorded == {"marketplace": "https://www.vinted.fr", "item_id": "9571854910"}


def test_get_listing_rejects_a_bad_id_before_any_request():
    client = _RecordingClient([])

    with pytest.raises(ValueError, match="Invalid listing ID"):
        client.get_listing("../../../etc/passwd")

    assert client.calls == []


# --- pagination ------------------------------------------------------------

def test_the_page_size_ceiling_is_the_value_vinted_enforces():
    """Verified live: Vinted returns 96 items however large per_page is."""
    assert MAX_PER_PAGE == 96


def test_search_caps_the_page_size_at_the_vinted_ceiling():
    client = _RecordingClient([_page(96, 1, 2), _page(96, 2, 2, start=100)])

    client.search_listings(query="lego", limit=150)

    assert client.calls[0][1]["per_page"] == 96


def test_search_requests_only_the_page_size_it_needs():
    client = _RecordingClient([_page(10, 1, 1)])

    client.search_listings(query="lego", limit=10)

    assert client.calls[0][1]["per_page"] == 10


def test_search_sends_exactly_the_expected_parameter_set():
    client = _RecordingClient([_page(1, 1, 1)])

    client.search_listings(query="lego", limit=5)

    _, params = client.calls[0]
    assert set(params) == {"search_text", "order", "per_page", "page"}
    assert params["page"] == 1


def test_search_pages_until_the_limit_is_reached():
    client = _RecordingClient([_page(MAX_PER_PAGE, 1, 3), _page(MAX_PER_PAGE, 2, 3, start=100)])

    rows = client.search_listings(query="lego", limit=150)

    assert len(rows) == 150
    assert [call[1]["page"] for call in client.calls] == [1, 2]


def test_search_returns_exactly_one_page_when_the_limit_matches_it():
    client = _RecordingClient([_page(MAX_PER_PAGE, 1, 5)])

    rows = client.search_listings(query="lego", limit=MAX_PER_PAGE)

    assert len(rows) == MAX_PER_PAGE
    assert len(client.calls) == 1


def test_search_stops_on_the_last_page():
    client = _RecordingClient([_page(10, 1, 1)])

    rows = client.search_listings(query="lego", limit=150)

    assert len(rows) == 10
    assert len(client.calls) == 1


def test_search_stops_on_an_empty_page():
    client = _RecordingClient([_page(0, 1, 9)])

    rows = client.search_listings(query="lego", limit=50)

    assert rows == []
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"items": [{"id": 1}, {"id": 2}]},
        {"items": [{"id": 1}, {"id": 2}], "pagination": {}},
        {"items": [{"id": 1}, {"id": 2}], "pagination": {"current_page": 1}},
        {"items": [{"id": 1}, {"id": 2}], "pagination": {"total_pages": None}},
        {"items": [{"id": 1}, {"id": 2}], "pagination": {"total_pages": 0}},
        {"items": [{"id": 1}, {"id": 2}], "pagination": {"total_pages": "3"}},
    ],
    ids=["absent", "empty", "no-total", "null-total", "zero-total", "string-total"],
)
def test_search_stops_when_total_pages_is_unusable(body):
    """An unusable total_pages must end the loop, not raise a TypeError."""
    client = _RecordingClient([body])

    rows = client.search_listings(query="lego", limit=50)

    assert len(rows) == 2
    assert len(client.calls) == 1


def test_search_returns_nothing_when_the_items_key_is_absent():
    client = _RecordingClient([{"pagination": {"total_pages": 9}}])

    rows = client.search_listings(query="lego", limit=50)

    assert rows == []
    assert len(client.calls) == 1


def test_search_keeps_paging_when_a_page_is_shorter_than_the_page_size():
    client = _RecordingClient([
        _page(10, 1, 3),
        _page(10, 2, 3, start=100),
        _page(10, 3, 3, start=200),
    ])

    rows = client.search_listings(query="lego", limit=50)

    assert len(rows) == 30
    assert len(client.calls) == 3


def test_search_stops_at_exactly_one_page_when_the_limit_is_97():
    client = _RecordingClient([_page(96, 1, 5), _page(96, 2, 5, start=100)])

    rows = client.search_listings(query="lego", limit=97)

    assert len(rows) == 97
    assert [call[1]["page"] for call in client.calls] == [1, 2]


def test_search_drops_listings_that_repeat_across_pages():
    """A listing added between two page requests shifts the offset window.

    Page 2 then repeats a listing from page 1. The result must stay unique.
    """
    client = _RecordingClient([
        {"items": [{"id": 1}, {"id": 2}, {"id": 3}], "pagination": {"total_pages": 2}},
        {"items": [{"id": 3}, {"id": 4}, {"id": 5}], "pagination": {"total_pages": 2}},
    ])

    rows = client.search_listings(query="lego", limit=10)

    assert [row["id"] for row in rows] == [1, 2, 3, 4, 5]


def test_search_keeps_paging_when_a_page_is_all_duplicates():
    client = _RecordingClient([
        {"items": [{"id": 1}, {"id": 2}], "pagination": {"total_pages": 3}},
        {"items": [{"id": 1}, {"id": 2}], "pagination": {"total_pages": 3}},
        {"items": [{"id": 3}], "pagination": {"total_pages": 3}},
    ])

    rows = client.search_listings(query="lego", limit=3)

    assert [row["id"] for row in rows] == [1, 2, 3]
    assert len(client.calls) == 3


# --- request amplification bounds ------------------------------------------

def test_search_stops_when_pages_keep_repeating_the_same_listings():
    """A catalog that repeats itself must not drive thousands of requests.

    Vinted reports a large total_pages while serving the same listings, so the
    unique-ID filter alone would never satisfy the limit.
    """
    repeated = {"items": [{"id": 1}, {"id": 2}], "pagination": {"total_pages": 10000}}
    client = _RecordingClient([repeated] * 10000)

    rows = client.search_listings(query="lego", limit=5)

    assert [row["id"] for row in rows] == [1, 2]
    assert len(client.calls) == 1 + BARREN_PAGE_LIMIT


def test_search_never_reads_more_than_the_page_ceiling():
    pages = [
        {"items": [{"id": n * 100 + i} for i in range(96)], "pagination": {"total_pages": 10000}}
        for n in range(MAX_PAGES + 5)
    ]
    client = _RecordingClient(pages)

    client.search_listings(query="lego", limit=MAX_LIMIT)

    assert len(client.calls) == MAX_PAGES


def test_search_rejects_a_limit_above_the_ceiling():
    client = _RecordingClient([])

    with pytest.raises(ValueError, match=f"--limit must be {MAX_LIMIT} or less"):
        client.search_listings(query="lego", limit=MAX_LIMIT + 1)

    assert client.calls == []


def test_search_accepts_a_limit_at_the_ceiling():
    client = _RecordingClient([_page(1, 1, 1)])

    rows = client.search_listings(query="lego", limit=MAX_LIMIT)

    assert [row["id"] for row in rows] == [0]


# --- an empty result must not be cached ------------------------------------

def test_an_empty_result_leaves_no_cache_entry():
    """Vinted answers a soft block with HTTP 200 and an empty item list.

    Caching that would return "no results" for an hour after Vinted recovered.
    """
    for stale in (_STORAGE_DIR / "cache").glob("_search_pages_*.json"):
        stale.unlink()

    client = _RecordingClient([_page(0, 1, 9)])
    assert client.search_listings(query="soft-blocked", limit=10) == []

    assert list((_STORAGE_DIR / "cache").glob("_search_pages_*.json")) == []
