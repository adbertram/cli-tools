"""Contract tests for the StockX search/list/get/market command surface.

These cover the parts of the contract that are pure logic and therefore run
without a browser: the Source-CLI Sort Standard mapping, the fail-fast
validation of every filter value (StockX silently ignores unknown ids and
values, so the CLI must reject them itself), url-key extraction, and the
filter list the client builds.
"""

import pytest
from typer.testing import CliRunner

from stockx_cli.client import (
    CATEGORY_VALUES,
    COLOR_VALUES,
    DEFAULT_SORT,
    GENDER_VALUES,
    SORT_VALUES,
    ClientError,
    SortError,
    StockxClient,
    extract_url_key,
    resolve_sort,
)
from stockx_cli.main import app
from stockx_cli.parsers import normalize_market, normalize_product, normalize_products

runner = CliRunner()


def _filters(client, **overrides):
    """Build a filter list with every argument defaulted to unset."""
    kwargs = {
        "brand": None,
        "gender": None,
        "category": None,
        "color": None,
        "activity": None,
        "below_retail": False,
        "xpress_ship": False,
        "min_price": None,
        "max_price": None,
    }
    kwargs.update(overrides)
    return {entry["id"]: entry["selectedValues"] for entry in client._build_filters(**kwargs)}


@pytest.fixture
def client():
    return StockxClient.__new__(StockxClient)


# --- resolve_sort: canonical mapping -------------------------------------

def test_default_sort_is_featured():
    assert DEFAULT_SORT == "featured"


def test_sort_values_match_stockx_sort_ids():
    assert set(SORT_VALUES) == {"featured", "lowest-ask", "highest-bid", "release-date"}


@pytest.mark.parametrize(
    ("field", "token"),
    [
        ("featured", "featured"),
        ("lowest-ask", "lowest_ask"),
        ("highest-bid", "highest_bid"),
        ("release-date", "release_date"),
    ],
)
def test_sort_fields_map_to_stockx_ids(field, token):
    assert resolve_sort(field) == token


def test_sort_is_case_insensitive():
    assert resolve_sort("Lowest-Ask") == "lowest_ask"


# --- resolve_sort: fail-fast ----------------------------------------------

def test_unknown_sort_raises():
    with pytest.raises(SortError) as excinfo:
        resolve_sort("price_low_to_high")
    assert "Valid values: featured, lowest-ask, highest-bid, release-date" in str(
        excinfo.value
    )


@pytest.mark.parametrize("field", list(SORT_VALUES))
def test_desc_is_rejected_for_every_sort(field):
    # StockX publishes no reverse order; `sort.order` silently reverts the
    # applied sort to `featured`, so --desc must fail instead of no-op.
    with pytest.raises(SortError) as excinfo:
        resolve_sort(field, desc=True)
    assert "--sort highest-bid" in str(excinfo.value)


# --- extract_url_key ------------------------------------------------------

def test_extract_url_key_passes_through_bare_key():
    assert extract_url_key("air-jordan-1-retro-high-og-shadow-brown") == (
        "air-jordan-1-retro-high-og-shadow-brown"
    )


def test_extract_url_key_reads_product_url():
    url = "https://stockx.com/air-jordan-1-retro-high-og-shadow-brown"
    assert extract_url_key(url) == "air-jordan-1-retro-high-og-shadow-brown"


def test_extract_url_key_ignores_trailing_slash():
    assert extract_url_key("https://stockx.com/nike-dunk-low/") == "nike-dunk-low"


def test_extract_url_key_rejects_empty():
    with pytest.raises(ClientError):
        extract_url_key("   ")


def test_extract_url_key_rejects_a_bare_host():
    with pytest.raises(ClientError):
        extract_url_key("https://stockx.com/")


# --- _build_filters: server-side filtering --------------------------------

def test_no_options_produce_no_filters(client):
    assert _filters(client) == {}


def test_brand_is_slugified_to_lowercase(client):
    # StockX silently ignores the display-case name "Nike".
    assert _filters(client, brand=["Nike", " adidas "]) == {"brand": ["nike", "adidas"]}


def test_gender_category_and_color_pass_through(client):
    filters = _filters(client, gender=["men"], category=["sneakers"], color=["black"])
    assert filters == {"gender": ["men"], "category": ["sneakers"], "color": ["black"]}


def test_activity_is_slugified(client):
    assert _filters(client, activity=["Basketball"]) == {"activity": ["basketball"]}


def test_boolean_filters_use_hyphenated_ids(client):
    filters = _filters(client, below_retail=True, xpress_ship=True)
    assert filters == {"below-retail": ["true"], "xpress-ship": ["true"]}


def test_price_range_sends_two_separate_values(client):
    # Verified live: a single "100-300" string returns HTTP 400.
    assert _filters(client, min_price=100, max_price=300) == {
        "lowest-ask-range": ["100", "300"]
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("min_price", 100), ("max_price", 300)],
)
def test_half_a_price_range_raises(client, field, value):
    with pytest.raises(ClientError) as excinfo:
        _filters(client, **{field: value})
    assert "--min-price" in str(excinfo.value)


def test_unknown_gender_raises(client):
    with pytest.raises(ClientError) as excinfo:
        _filters(client, gender=["male"])
    assert "Valid values: " + ", ".join(GENDER_VALUES) in str(excinfo.value)


def test_unknown_category_raises(client):
    with pytest.raises(ClientError) as excinfo:
        _filters(client, category=["shoez"])
    assert "Valid values: " + ", ".join(CATEGORY_VALUES) in str(excinfo.value)


def test_unknown_color_raises(client):
    with pytest.raises(ClientError) as excinfo:
        _filters(client, color=["chartreuse"])
    assert "Valid values: " + ", ".join(COLOR_VALUES) in str(excinfo.value)


# --- parsers ---------------------------------------------------------------

def _product_url(url_key):
    return f"https://stockx.com/{url_key}"


def test_normalize_products_adds_url_without_dropping_fields():
    rows = normalize_products(
        [{"id": "abc", "urlKey": "nike-dunk-low", "title": "Nike Dunk Low"}], _product_url
    )
    assert rows == [{
        "id": "abc",
        "urlKey": "nike-dunk-low",
        "title": "Nike Dunk Low",
        "url": "https://stockx.com/nike-dunk-low",
    }]


def test_normalize_product_adds_url():
    row = normalize_product({"urlKey": "nike-dunk-low", "styleId": "DD1391"}, _product_url)
    assert row["url"] == "https://stockx.com/nike-dunk-low"
    assert row["styleId"] == "DD1391"


def test_normalize_market_preserves_the_market_block():
    market = {"state": {"lowestAsk": {"amount": 290}}}
    row = normalize_market({"urlKey": "nike-dunk-low", "market": market}, _product_url)
    assert row["market"] == market
    assert row["url"] == "https://stockx.com/nike-dunk-low"


def test_normalize_products_rejects_a_record_without_a_url_key():
    with pytest.raises(ValueError):
        normalize_products([{"id": "abc"}], _product_url)


# --- CLI-level validation (runs before any browser work) ------------------

def test_cli_rejects_unknown_sort():
    result = runner.invoke(app, ["products", "search", "dunk", "--sort", "bogus"])
    assert result.exit_code == 1


def test_cli_rejects_desc():
    result = runner.invoke(
        app, ["products", "search", "dunk", "--sort", "lowest-ask", "--desc"]
    )
    assert result.exit_code == 1


def test_cli_rejects_unknown_gender():
    result = runner.invoke(app, ["products", "search", "dunk", "--gender", "male"])
    assert result.exit_code == 1


def test_cli_rejects_half_a_price_range():
    result = runner.invoke(app, ["products", "list", "--min-price", "100"])
    assert result.exit_code == 1


def test_cli_rejects_malformed_filter():
    result = runner.invoke(app, ["products", "list", "--filter", "not-a-filter"])
    assert result.exit_code == 1
