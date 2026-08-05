"""Contract tests for the OfferUp search/list/get command surface.

These cover the parts of the contract that are pure logic and therefore run
without a browser: the Source-CLI Sort Standard mapping, the fail-fast
validation of every filter value (OfferUp silently ignores unknown values, so
the CLI must reject them itself), listing-id extraction, and the search-param
list the client builds.
"""

import pytest
from typer.testing import CliRunner

from offerup_cli.client import (
    CONDITION_VALUES,
    DEFAULT_SORT,
    RADIUS_VALUES,
    SORT_VALUES,
    ClientError,
    OfferupClient,
    SortError,
    _iter_feed_listings,
    extract_listing_id,
    resolve_sort,
)
from offerup_cli.main import app
from offerup_cli.parsers import normalize_listing_detail, normalize_listings

runner = CliRunner()


def _params(client, **overrides):
    """Build a search-param list with every argument defaulted to None."""
    kwargs = {
        "query": None,
        "page_size": 50,
        "sort_token": None,
        "condition": None,
        "min_price": None,
        "max_price": None,
        "radius": None,
        "latitude": None,
        "longitude": None,
        "page_cursor": None,
    }
    kwargs.update(overrides)
    return {entry["key"]: entry["value"] for entry in client._build_params(**kwargs)}


@pytest.fixture
def client():
    return OfferupClient.__new__(OfferupClient)


# --- resolve_sort: canonical mapping -------------------------------------

def test_default_sort_is_relevance():
    assert DEFAULT_SORT == "relevance"


def test_sort_values_match_offerup_sort_filter():
    assert set(SORT_VALUES) == {"relevance", "newest", "distance", "price"}


def test_relevance_maps_to_best_match():
    assert resolve_sort("relevance") == "best_match"


def test_newest_maps_to_posted_descending():
    assert resolve_sort("newest") == "-posted"


def test_distance_maps_to_distance():
    assert resolve_sort("distance") == "distance"


def test_price_natural_maps_to_price_ascending():
    assert resolve_sort("price") == "price"


def test_price_desc_maps_to_price_descending():
    assert resolve_sort("price", desc=True) == "-price"


def test_sort_is_case_insensitive():
    assert resolve_sort("PRICE", desc=True) == "-price"


# --- resolve_sort: fail-fast ----------------------------------------------

def test_unknown_sort_raises():
    with pytest.raises(SortError) as excinfo:
        resolve_sort("bogus")
    assert "Valid values: relevance, newest, distance, price" in str(excinfo.value)


@pytest.mark.parametrize("field", ["relevance", "newest", "distance"])
def test_desc_rejected_for_undirected_sorts(field):
    with pytest.raises(SortError) as excinfo:
        resolve_sort(field, desc=True)
    assert "--sort price" in str(excinfo.value)


# --- extract_listing_id ---------------------------------------------------

def test_extract_listing_id_passes_through_bare_id():
    assert extract_listing_id("2a8b6eda-4b05-33a2-be75-2eb33966b8c1") == (
        "2a8b6eda-4b05-33a2-be75-2eb33966b8c1"
    )


def test_extract_listing_id_reads_item_url():
    url = "https://offerup.com/item/detail/2a8b6eda-4b05-33a2-be75-2eb33966b8c1"
    assert extract_listing_id(url) == "2a8b6eda-4b05-33a2-be75-2eb33966b8c1"


def test_extract_listing_id_ignores_trailing_slash():
    url = "https://offerup.com/item/detail/abc-123/"
    assert extract_listing_id(url) == "abc-123"


def test_extract_listing_id_rejects_empty():
    with pytest.raises(ClientError):
        extract_listing_id("")


# --- _build_params: server-side filtering ---------------------------------

def test_query_is_sent_as_q(client):
    assert _params(client, query="lego")["q"] == "lego"


def test_query_is_omitted_for_the_local_feed(client):
    assert "q" not in _params(client)


def test_page_size_is_sent_as_limit(client):
    assert _params(client, page_size=7)["limit"] == "7"


def test_prices_are_sent_as_price_min_and_price_max(client):
    params = _params(client, min_price=20, max_price=100)
    assert params["price_min"] == "20"
    assert params["price_max"] == "100"


def test_conditions_are_comma_joined(client):
    params = _params(client, condition=["NEW", "USED"])
    assert params["condition"] == "NEW,USED"


def test_coordinates_are_sent_as_lat_and_lon(client):
    params = _params(client, latitude=47.6062, longitude=-122.3321)
    assert params["lat"] == "47.6062"
    assert params["lon"] == "-122.3321"


def test_cursor_is_sent_as_page_cursor(client):
    assert _params(client, page_cursor="CURSOR")["page_cursor"] == "CURSOR"


def test_unknown_condition_raises(client):
    with pytest.raises(ClientError) as excinfo:
        _params(client, condition=["BRAND_NEW"])
    assert "Valid values: " + ", ".join(CONDITION_VALUES) in str(excinfo.value)


def test_unknown_radius_raises(client):
    with pytest.raises(ClientError) as excinfo:
        _params(client, radius="7")
    assert "Valid values: " + ", ".join(RADIUS_VALUES) in str(excinfo.value)


def test_known_radius_is_accepted(client):
    assert _params(client, radius="10")["radius"] == "10"


# --- _iter_feed_listings ---------------------------------------------------

def test_iter_feed_listings_reads_loose_tiles_and_modules():
    feed = {
        "looseTiles": [
            {},
            {"listing": {"listingId": "a"}},
        ],
        "modules": [
            {"grid": {"tiles": [{"listing": {"listingId": "b"}}, {}]}},
            {"grid": {"tiles": []}},
        ],
    }
    assert [item["listingId"] for item in _iter_feed_listings(feed)] == ["a", "b"]


def test_iter_feed_listings_handles_null_collections():
    assert list(_iter_feed_listings({"looseTiles": None, "modules": None})) == []


# --- parsers ---------------------------------------------------------------

def _item_url(listing_id):
    return f"https://offerup.com/item/detail/{listing_id}"


def test_normalize_listings_adds_id_and_url_without_dropping_fields():
    rows = normalize_listings([{"listingId": "abc", "title": "Legos", "price": "20"}], _item_url)
    assert rows == [{
        "listingId": "abc",
        "title": "Legos",
        "price": "20",
        "id": "abc",
        "url": "https://offerup.com/item/detail/abc",
    }]


def test_normalize_listing_detail_adds_id_and_url():
    row = normalize_listing_detail({"listingId": "abc", "id": "abc", "state": "LISTED"}, _item_url)
    assert row["id"] == "abc"
    assert row["url"] == "https://offerup.com/item/detail/abc"
    assert row["state"] == "LISTED"


def test_normalize_listings_rejects_a_record_without_a_listing_id():
    with pytest.raises(ValueError):
        normalize_listings([{"title": "no id"}], _item_url)


# --- CLI-level validation (runs before any browser work) ------------------

def test_cli_rejects_unknown_sort():
    result = runner.invoke(app, ["listings", "search", "lego", "--sort", "bogus"])
    assert result.exit_code == 1


def test_cli_rejects_unknown_condition():
    result = runner.invoke(
        app, ["listings", "search", "lego", "--condition", "BRAND_NEW"]
    )
    assert result.exit_code == 1


def test_cli_rejects_desc_with_relevance():
    result = runner.invoke(
        app, ["listings", "search", "lego", "--sort", "relevance", "--desc"]
    )
    assert result.exit_code == 1


def test_cli_rejects_malformed_filter():
    result = runner.invoke(app, ["listings", "list", "--filter", "not-a-filter"])
    assert result.exit_code == 1
