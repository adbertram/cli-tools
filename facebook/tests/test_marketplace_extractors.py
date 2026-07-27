"""Hermetic Marketplace extractor tests against real Facebook DOM captured live.

Fixtures under ``tests/fixtures/`` are verbatim DOM captured on 2026-07-25 from
an authenticated Facebook session:

  - ``marketplace_item_price_drop.html`` -- the ``[role="main"]`` subtree of
    listing 2088943005027414, a price-dropped listing rendering ``$15`` with a
    struck-through ``$20``. Reading the price element's text yielded ``$15$20``,
    which the price normalizer turned into ``1520.0``.
  - ``marketplace_list_tiles.html`` -- five verbatim search/browse tile anchors
    covering every rendered variant: aria-labelled, content-derived, a
    "Just listed" badge tile, a discounted tile (``$100`` / ``$350``), and (added
    2026-07-26) a "commerce_interesting_product" notification/prose tile whose
    title and price are rendered as ``<b>`` elements inside a sentence
    ("Huge Lot ... listed for $50.00.") instead of dedicated spans.
  - ``marketplace_search_no_results.html`` -- the ``[role="main"]`` subtree of a
    genuinely empty search, carrying Facebook's own "No listings found for ...
    within 10 miles" heading.

The extractors under test are browser-evaluated JavaScript, so each fixture is
loaded into a real headless Chromium page via ``set_content`` and the exact
production JS constant is evaluated against it.
"""

from pathlib import Path

import pytest
from cli_tools_shared.exceptions import ClientError
from playwright.sync_api import sync_playwright

from facebook_cli.client import (
    DETAIL_PAGE_PRICE_JS,
    LIST_PAGE_LISTINGS_JS,
    MARKETPLACE_PAGE_STATE_JS,
    MARKETPLACE_RESULTS_CONTAINER_SELECTOR,
    FacebookClient,
)
from facebook_cli.models import MarketplaceListing

FIXTURES = Path(__file__).parent / "fixtures"


def _evaluate(html: str, js: str, arg=None):
    """Evaluate a production extractor against fixture DOM in real Chromium."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        result = page.evaluate(js, arg) if arg is not None else page.evaluate(js)
        browser.close()
    return result


@pytest.fixture(scope="module")
def price_drop_html() -> str:
    return (FIXTURES / "marketplace_item_price_drop.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def list_tiles_html() -> str:
    return (FIXTURES / "marketplace_list_tiles.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def no_results_html() -> str:
    return (FIXTURES / "marketplace_search_no_results.html").read_text(encoding="utf-8")


# --- Detail-page price extraction -------------------------------------------


def test_detail_price_extractor_returns_current_price_on_price_drop(price_drop_html):
    """The struck-through original price must not be concatenated into the
    current price. Regression for `get` returning 1520.0 for a $15 listing."""
    result = _evaluate(price_drop_html, DETAIL_PAGE_PRICE_JS)

    assert result == {"price": "$15", "originalPrice": "$20"}


def test_detail_price_extractor_survives_model_normalization(price_drop_html):
    """End-to-end for the reported defect: the extracted strings become the
    listing's current price and its pre-drop price, not 1520.0."""
    result = _evaluate(price_drop_html, DETAIL_PAGE_PRICE_JS)

    listing = MarketplaceListing(
        item_id="2088943005027414",
        title="LEGO Dobby Harry Potter build",
        price=result["price"],
        original_price=result["originalPrice"],
        url="/marketplace/item/2088943005027414/",
    )

    assert listing.price == 15.0
    assert listing.original_price == 20.0
    assert listing.price_currency == "$"


def test_detail_price_extractor_returns_empty_without_a_listing_page():
    """A page with no listing title yields no price rather than a wrong one."""
    result = _evaluate('<div role="main"><span>$42</span></div>', DETAIL_PAGE_PRICE_JS)

    assert result == {"price": "", "originalPrice": ""}


# --- Price normalization ----------------------------------------------------


def test_currency_prefixed_price_is_not_reported_as_local_currency():
    """Facebook renders 'CA$75' for foreign-currency listings; the symbol must
    survive so 75 CAD is not reported as if it were 75 USD."""
    listing = MarketplaceListing(
        item_id="1535445751373288",
        title="LEGO Star Wars Instruction Manuals Lot",
        price="CA$75",
        original_price="CA$90",
        url="/marketplace/item/1535445751373288/",
    )

    assert listing.price == 75.0
    assert listing.original_price == 90.0
    assert listing.price_currency == "CA$"


def test_non_dollar_currency_symbol_is_preserved():
    """Facebook Marketplace shop listings render other currencies outright
    (a live '£1,600' Lego Marketplace tile, 2026-07-25)."""
    listing = MarketplaceListing(
        item_id="3247564075445631",
        title="***JOB LOT*** 31 Retired used and played with Lego sets",
        price="£1,600",
        url="/marketplace/item/3247564075445631/",
    )

    assert listing.price == 1600.0
    assert listing.price_currency == "£"


def test_list_tile_extractor_reads_a_pound_sterling_tile():
    """The tile extractor must accept any Unicode currency symbol, not just '$'.

    Synthetic tile markup mirroring the live '£1,600' Lego Marketplace tile.
    """
    html = (
        '<a href="https://www.facebook.com/marketplace/item/3247564075445631/">'
        "<span>Just listed</span><span>£1,600</span>"
        "<span>***JOB LOT*** 31 Retired Lego sets</span><span>Lego Marketplace</span></a>"
    )

    result = _evaluate(html, LIST_PAGE_LISTINGS_JS)

    assert result["unparsed"] == []
    assert result["rows"][0]["price"] == "£1,600"
    assert result["rows"][0]["title"] == "***JOB LOT*** 31 Retired Lego sets"
    assert result["rows"][0]["location"] == "Lego Marketplace"


def test_free_listing_normalizes_to_zero():
    listing = MarketplaceListing(
        item_id="1",
        title="Free bricks",
        price="Free",
        url="/marketplace/item/1/",
    )

    assert listing.price == 0.0
    assert listing.price_currency is None


def test_unrecognized_price_string_fails_loudly():
    """A price shape the CLI does not understand must not silently become None."""
    with pytest.raises(ValueError, match="Unrecognized Facebook price string"):
        MarketplaceListing(
            item_id="1",
            title="Mystery",
            price="15 euros",
            url="/marketplace/item/1/",
        )


# --- List/search tile extraction --------------------------------------------


def test_list_tile_extractor_reads_every_rendered_tile_variant(list_tiles_html):
    """Facebook serves aria-labelled AND content-derived tiles. The
    content-derived variant previously parsed to nothing, which is what made a
    healthy search return []."""
    result = _evaluate(list_tiles_html, LIST_PAGE_LISTINGS_JS)

    assert result["unparsed"] == []
    rows = {row["item_id"]: row for row in result["rows"]}
    assert len(rows) == 5

    # "Just listed" badge tile: the badge precedes the price and is not a field.
    assert rows["27627584550238930"]["title"] == "Moving Sale"
    assert rows["27627584550238930"]["price"] == "$123"
    assert rows["27627584550238930"]["location"] == "Newburgh, IN"

    # aria-labelled variant
    assert rows["1345185447811982"]["title"] == "17lbs of legos"
    assert rows["1345185447811982"]["price"] == "$100"

    # content-derived variant
    assert rows["1615488030295895"]["title"] == "Vintage Legos"
    assert rows["1615488030295895"]["price"] == "$30"


def test_list_tile_extractor_reads_a_notification_prose_tile(list_tiles_html):
    """A 'commerce_interesting_product' notification tile (captured live
    2026-07-26, item 27542838245367180) renders its title and price as <b>
    elements inside a sentence -- "<b>Title</b> listed for <b>$50.00</b>." --
    instead of dedicated spans, with an unrelated "Unread" badge <div>
    immediately before the title. Regression for `list` raising
    'listing tile(s) still rendered without a recognizable price and title'."""
    result = _evaluate(list_tiles_html, LIST_PAGE_LISTINGS_JS)
    row = next(r for r in result["rows"] if r["item_id"] == "27542838245367180")

    assert row["title"] == "Huge Lot thousands crayons,colored pencils..."
    assert row["price"] == "$50.00"
    assert row["original_price"] is None
    # This tile shape carries no location field -- it must not be invented
    # from the badge/relative-time text ("Unread" or "9h").
    assert row["location"] is None

    listing = MarketplaceListing(**row)
    assert listing.price == 50.0
    assert listing.price_currency == "$"


def test_list_tile_extractor_ignores_unrelated_bold_pairs_without_listed_for():
    """The notification/prose fallback must not fire on any two <b> elements --
    only ones connected by the literal "listed for" wording Facebook renders
    for this tile shape. A tile with two unrelated bold elements (no such
    wording, no shared parent) must still report unparsed rather than
    inventing a price/title pairing.
    """
    html = (
        '<a href="https://www.facebook.com/marketplace/item/999/?ref=x">'
        "<div><b>Bold heading</b></div><div><b>$99</b> deposit required</div></a>"
    )

    result = _evaluate(html, LIST_PAGE_LISTINGS_JS)

    assert result["rows"] == []
    assert result["unparsed"] != []


def test_list_tile_extractor_splits_a_discounted_tile(list_tiles_html):
    """A discounted tile flattens to '$100$350' in text; the DOM split keeps the
    current price separate from the struck-through original."""
    result = _evaluate(list_tiles_html, LIST_PAGE_LISTINGS_JS)
    row = next(r for r in result["rows"] if r["item_id"] == "2087131391898720")

    assert row["price"] == "$100"
    assert row["original_price"] == "$350"

    listing = MarketplaceListing(**row)
    assert listing.price == 100.0
    assert listing.original_price == 350.0


def test_list_tile_extractor_reports_a_tile_it_cannot_read():
    """A rendered tile with text but no price must be reported as unparsed so
    the caller fails loudly instead of under-reporting results.

    The markup is synthetic: it is a listing anchor stripped of its price span,
    standing in for a future Facebook markup change.
    """
    html = (
        '<a href="https://www.facebook.com/marketplace/item/999/?ref=x">'
        "<span>Some listing title</span><span>Evansville, IN</span></a>"
    )

    result = _evaluate(html, LIST_PAGE_LISTINGS_JS)

    assert result["rows"] == []
    assert result["unparsed"] == [
        {"item_id": "999", "text": "Some listing titleEvansville, IN"}
    ]


def test_list_tile_extractor_ignores_unpainted_scroll_skeletons():
    """A tile anchor that has not painted any text yet is not a parse failure."""
    html = '<a href="https://www.facebook.com/marketplace/item/999/"><div></div></a>'

    result = _evaluate(html, LIST_PAGE_LISTINGS_JS)

    assert result == {"rows": [], "unparsed": []}


# --- Empty-result page state ------------------------------------------------


def test_page_state_recognizes_a_genuine_zero_result_search(no_results_html):
    """Facebook's own results container plus its 'No listings found' heading is
    the ONLY empty outcome the CLI is allowed to report as zero results."""
    state = _evaluate(
        no_results_html, MARKETPLACE_PAGE_STATE_JS, MARKETPLACE_RESULTS_CONTAINER_SELECTOR
    )

    assert state["container_exists"] is True
    assert state["item_link_count"] == 0
    assert state["no_results"] is True
    assert state["empty_heading"].startswith("No listings found for ")


def test_page_state_without_the_results_container_is_not_zero_results():
    """A page body that never rendered the results container must not look like
    a legitimate empty search.

    Synthetic markup standing in for an unsettled/blocked render.
    """
    state = _evaluate(
        '<div role="main"><h2>Marketplace</h2></div>',
        MARKETPLACE_PAGE_STATE_JS,
        MARKETPLACE_RESULTS_CONTAINER_SELECTOR,
    )

    assert state["main_exists"] is True
    assert state["container_exists"] is False
    assert state["no_results"] is False


# --- Empty-result decision --------------------------------------------------


def _state(**overrides):
    state = {
        "url": "https://www.facebook.com/marketplace/evansville/search/?query=lego",
        "title": "Facebook",
        "main_exists": True,
        "container_exists": True,
        "item_link_count": 0,
        "headings": [],
        "empty_heading": None,
        "no_results": False,
    }
    state.update(overrides)
    return state


def test_genuine_zero_result_search_does_not_raise():
    FacebookClient._raise_for_empty_marketplace_results(
        _state(no_results=True, empty_heading='No listings found for "zzz" within 10 miles'),
        "Marketplace (search)",
    )


def test_missing_results_container_raises():
    with pytest.raises(ClientError, match="did not report a zero-result search"):
        FacebookClient._raise_for_empty_marketplace_results(
            _state(container_exists=False), "Marketplace (search)"
        )


def test_settled_container_with_no_listings_and_no_message_raises():
    with pytest.raises(ClientError, match="did not report a zero-result search"):
        FacebookClient._raise_for_empty_marketplace_results(
            _state(), "Marketplace (search)"
        )


def test_missing_page_body_raises():
    with pytest.raises(ClientError, match="never rendered a Marketplace page body"):
        FacebookClient._raise_for_empty_marketplace_results(
            _state(main_exists=False, container_exists=False), "Marketplace (search)"
        )


def test_rendered_tiles_that_extract_to_nothing_raise_as_a_markup_change():
    with pytest.raises(ClientError, match="changed its listing markup"):
        FacebookClient._raise_for_empty_marketplace_results(
            _state(item_link_count=24), "Marketplace (search)"
        )
