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
        [{
            "__typename": "Product",
            "id": "abc",
            "urlKey": "nike-dunk-low",
            "title": "Nike Dunk Low",
        }],
        _product_url,
    )
    assert rows == [{
        "__typename": "Product",
        "id": "abc",
        "urlKey": "nike-dunk-low",
        "title": "Nike Dunk Low",
        "url": "https://stockx.com/nike-dunk-low",
    }]


# --- browse union: Variant nodes ------------------------------------------
# Verified live: a `lego` search returned 40 Product nodes and 4 Variant nodes
# on one page. A Variant has no top-level urlKey/title/brand.

def _variant_node():
    return {
        "__typename": "Variant",
        "id": "variant-1",
        "market": {"state": {"lowestAsk": {"amount": 400}}},
        "sizeChart": {"baseType": "us"},
        "product": {
            "id": "product-1",
            "urlKey": "lego-technic-mobile-crane-mk-ii-set-42009",
            "title": "LEGO Technic Mobile Crane MK II Set 42009",
            "brand": "LEGO",
            "productCategory": "collectibles",
        },
    }


def test_variant_node_promotes_its_product_identity():
    row = normalize_products([_variant_node()], _product_url)[0]
    assert row["urlKey"] == "lego-technic-mobile-crane-mk-ii-set-42009"
    assert row["title"] == "LEGO Technic Mobile Crane MK II Set 42009"
    assert row["brand"] == "LEGO"
    assert row["id"] == "product-1"
    assert row["url"] == (
        "https://stockx.com/lego-technic-mobile-crane-mk-ii-set-42009"
    )


def test_variant_node_keeps_its_own_id_and_size_level_data():
    row = normalize_products([_variant_node()], _product_url)[0]
    assert row["variantId"] == "variant-1"
    assert row["sizeChart"] == {"baseType": "us"}
    assert row["market"] == {"state": {"lowestAsk": {"amount": 400}}}
    assert row["product"] == _variant_node()["product"]


def test_variant_node_keeps_its_typename():
    row = normalize_products([_variant_node()], _product_url)[0]
    assert row["__typename"] == "Variant"


def test_mixed_product_and_variant_nodes_share_one_row_shape():
    product = {
        "__typename": "Product",
        "id": "abc",
        "urlKey": "nike-dunk-low",
        "title": "Nike Dunk Low",
        "brand": "Nike",
    }
    rows = normalize_products([product, _variant_node()], _product_url)
    for row in rows:
        assert {"id", "urlKey", "title", "brand", "url"} <= set(row)


def test_variant_without_a_nested_product_raises():
    with pytest.raises(ValueError) as excinfo:
        normalize_products([{"__typename": "Variant", "id": "v"}], _product_url)
    assert "no nested product" in str(excinfo.value)


def test_unknown_node_type_raises():
    with pytest.raises(ValueError) as excinfo:
        normalize_products([{"__typename": "MysteryBox", "id": "m"}], _product_url)
    assert "Unsupported StockX browse node type" in str(excinfo.value)


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


# --- pagination -----------------------------------------------------------
# StockX offsets by index * limit, so a shrinking last page shifts the window
# and returns rows already seen (verified: a 100-row request yielded 98).

def _paging_client(monkeypatch, total_pages=5, page_size=40):
    """A client whose _graphql returns distinct products per page index."""
    client = StockxClient.__new__(StockxClient)
    calls = []

    def fake_graphql(operation, variables):
        calls.append(variables["page"])
        index = variables["page"]["index"]
        if index > total_pages:
            return {"browse": {"results": {"edges": []}}}
        start = (index - 1) * page_size
        return {"browse": {"results": {"edges": [
            {"node": {
                "__typename": "Product",
                "id": f"p{start + offset}",
                "urlKey": f"key-{start + offset}",
                "title": f"Product {start + offset}",
            }}
            for offset in range(page_size)
        ]}}}

    monkeypatch.setattr(client, "_graphql", fake_graphql)
    monkeypatch.setattr(client, "product_url", lambda key: f"https://stockx.com/{key}")
    return client, calls


def test_every_page_requests_the_same_page_size(monkeypatch):
    client, calls = _paging_client(monkeypatch)
    client.search_products.__wrapped__(client, query="lego", limit=100)
    assert [page["limit"] for page in calls] == [40] * len(calls)


def test_page_index_increments_by_one(monkeypatch):
    client, calls = _paging_client(monkeypatch)
    client.search_products.__wrapped__(client, query="lego", limit=100)
    assert [page["index"] for page in calls] == list(range(1, len(calls) + 1))


def test_results_are_trimmed_to_the_requested_limit(monkeypatch):
    client, _ = _paging_client(monkeypatch)
    rows = client.search_products.__wrapped__(client, query="lego", limit=100)
    assert len(rows) == 100
    assert len({row["urlKey"] for row in rows}) == 100


def test_paging_stops_when_a_page_returns_no_edges(monkeypatch):
    client, calls = _paging_client(monkeypatch, total_pages=2)
    rows = client.search_products.__wrapped__(client, query="lego", limit=1000)
    assert len(rows) == 80
    assert len(calls) == 3


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
