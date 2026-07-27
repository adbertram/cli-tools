"""Hermetic tests for the Marketplace delivery-type (fulfillment) capture.

Facebook models fulfillment per listing as a ``delivery_types`` array and never
renders it as text, so the capture reads Facebook's own Relay payload. Fixtures
under ``tests/fixtures/`` are verbatim live data captured 2026-07-26 from an
authenticated session:

  - ``marketplace_item_delivery_in_person.html`` -- the verbatim
    ``<script type="application/json">`` element from listing 26999388286428618's
    detail page carrying that listing's node (``delivery_types: ["IN_PERSON"]``,
    ``location_text: {"text": "Evansville, IN"}``). This is the listing that
    reported ``location: null`` and no delivery type at all.
  - ``marketplace_item_delivery_shipping.html`` -- the same element from listing
    1716979012677494, a shipping-capable listing
    (``["IN_PERSON", "SHIPPING_ONSITE"]``, Williamsburg, VA).
  - ``marketplace_search_pagination_response.txt`` -- the verbatim body of a
    Relay pagination response served while scrolling a Marketplace search. This
    is the ONLY transport that carries fulfillment for scroll-loaded tiles, so
    it is replayed here through a real XHR rather than parsed directly.

The capture is browser-evaluated JavaScript, so every fixture is loaded into a
real headless Chromium page and the exact production JS constant is evaluated
against it.
"""

from pathlib import Path

import pytest
from cli_tools_shared.exceptions import ClientError
from playwright.sync_api import sync_playwright

from facebook_cli.client import (
    INSTALL_DELIVERY_CAPTURE_JS,
    LIST_PAGE_LISTINGS_JS,
    READ_DELIVERY_CAPTURE_JS,
    TILE_SHIPPING_PLACEHOLDER_LOCATION,
    FacebookClient,
)
from facebook_cli.models import MarketplaceListing

FIXTURES = Path(__file__).parent / "fixtures"

IN_PERSON_ITEM_ID = "26999388286428618"
SHIPPING_ITEM_ID = "1716979012677494"


class _FakePage:
    """Minimal page stand-in that replays recorded ``evaluate`` results."""

    def __init__(self, results: dict):
        self._results = results

    def evaluate(self, js, arg=None):
        if js not in self._results:
            raise AssertionError(f"unexpected evaluate() call: {js[:60]!r}")
        return self._results[js]


def _capture_from(html: str) -> dict:
    """Install the production capture against fixture DOM and read it back."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        page.evaluate(INSTALL_DELIVERY_CAPTURE_JS)
        capture = page.evaluate(READ_DELIVERY_CAPTURE_JS)
        browser.close()
    return capture


# --- Detail-page capture ----------------------------------------------------


def test_capture_reads_a_local_pickup_only_listing():
    """The reported listing returned no delivery field and `location: null`;
    Facebook's own payload says IN_PERSON in Evansville, IN."""
    capture = _capture_from(
        (FIXTURES / "marketplace_item_delivery_in_person.html").read_text(encoding="utf-8")
    )

    assert capture["deliveryTypes"][IN_PERSON_ITEM_ID] == ["IN_PERSON"]
    assert capture["locationText"][IN_PERSON_ITEM_ID] == "Evansville, IN"
    assert capture["conflicts"] == {}


def test_capture_reads_a_shipping_capable_listing():
    """A listing that ships is distinguishable from one that does not -- which
    is the entire point of the field."""
    capture = _capture_from(
        (FIXTURES / "marketplace_item_delivery_shipping.html").read_text(encoding="utf-8")
    )

    assert capture["deliveryTypes"][SHIPPING_ITEM_ID] == ["IN_PERSON", "SHIPPING_ONSITE"]
    assert capture["locationText"][SHIPPING_ITEM_ID] == "Williamsburg, VA"


def test_capture_installs_only_once():
    """A second install must not discard payloads already captured."""
    html = (FIXTURES / "marketplace_item_delivery_in_person.html").read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        first = page.evaluate(INSTALL_DELIVERY_CAPTURE_JS)
        second = page.evaluate(INSTALL_DELIVERY_CAPTURE_JS)
        capture = page.evaluate(READ_DELIVERY_CAPTURE_JS)
        browser.close()

    assert first["installed"] is True
    assert second["installed"] is False
    assert capture["deliveryTypes"][IN_PERSON_ITEM_ID] == ["IN_PERSON"]


def test_capture_ignores_a_page_with_no_listing_data():
    """A login wall or removed-listing shell yields nothing rather than a
    fabricated fulfillment model."""
    capture = _capture_from("<div role='main'><h1>Log in to Facebook</h1></div>")

    assert capture["deliveryTypes"] == {}
    assert capture["parseErrors"] == 0


# --- Relay pagination transport ---------------------------------------------


def test_capture_harvests_scroll_loaded_tiles_from_a_pagination_response():
    """Scroll-loaded tiles carry fulfillment ONLY in the Relay pagination
    response, so the hook must read an XHR body -- including Facebook's
    multi-document streaming shape."""
    body = (FIXTURES / "marketplace_search_pagination_response.txt").read_text(encoding="utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route(
            "**/api/graphql/**",
            lambda route: route.fulfill(status=200, content_type="text/plain", body=body),
        )
        page.route(
            "https://www.facebook.com/marketplace/**",
            lambda route: route.fulfill(
                status=200, content_type="text/html", body="<div role='main'></div>"
            ),
        )
        # A real origin, so the in-page XHR resolves like it does on Facebook.
        page.goto("https://www.facebook.com/marketplace/evansville/search/")
        page.evaluate(INSTALL_DELIVERY_CAPTURE_JS)
        page.evaluate(
            """() => new Promise((resolve) => {
                const xhr = new XMLHttpRequest();
                xhr.open('POST', '/api/graphql/');
                xhr.addEventListener('loadend', () => setTimeout(resolve, 50));
                xhr.send('q=1');
            })"""
        )
        capture = page.evaluate(READ_DELIVERY_CAPTURE_JS)
        browser.close()

    assert capture["payloads"] >= 1
    assert len(capture["deliveryTypes"]) > 20
    assert capture["conflicts"] == {}
    # Every captured listing names at least one delivery type; an empty array
    # would be reported as "offers no fulfillment".
    assert all(types for types in capture["deliveryTypes"].values())


# --- Fail-loud contract on `get` --------------------------------------------


def test_get_fails_loudly_when_facebook_describes_no_delivery_types():
    """An unreadable fulfillment model must never be reported as a listing that
    does not ship."""
    page = _FakePage({
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 3},
        READ_DELIVERY_CAPTURE_JS: {
            "deliveryTypes": {"111": ["IN_PERSON"]},
            "locationText": {},
            "conflicts": {},
            "payloads": 2,
            "parseErrors": 0,
        },
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="did not describe the fulfillment options"):
        client._extract_listing_fulfillment(page, "999")


def test_get_fails_loudly_on_an_empty_delivery_types_array():
    page = _FakePage({
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 1},
        READ_DELIVERY_CAPTURE_JS: {
            "deliveryTypes": {"999": []},
            "locationText": {},
            "conflicts": {},
            "payloads": 1,
            "parseErrors": 0,
        },
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="did not describe the fulfillment options"):
        client._extract_listing_fulfillment(page, "999")


def test_conflicting_payloads_fail_loudly():
    """If two payloads disagree about a listing, no listing's read is trusted."""
    page = _FakePage({
        READ_DELIVERY_CAPTURE_JS: {
            "deliveryTypes": {"999": ["IN_PERSON"]},
            "locationText": {},
            "conflicts": {"999": [["IN_PERSON"], ["IN_PERSON", "SHIPPING_ONSITE"]]},
            "payloads": 2,
            "parseErrors": 0,
        },
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="conflicting delivery_types"):
        client._read_delivery_capture(page)


def test_uninstalled_capture_fails_loudly():
    page = _FakePage({READ_DELIVERY_CAPTURE_JS: None})
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="capture was not installed"):
        client._read_delivery_capture(page)


def test_listing_fulfillment_returns_location_when_facebook_carries_one():
    page = _FakePage({
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 1},
        READ_DELIVERY_CAPTURE_JS: {
            "deliveryTypes": {"999": ["IN_PERSON", "SHIPPING_ONSITE"]},
            "locationText": {"999": "Evansville, IN"},
            "conflicts": {},
            "payloads": 1,
            "parseErrors": 0,
        },
    })
    client = FacebookClient.__new__(FacebookClient)

    assert client._extract_listing_fulfillment(page, "999") == {
        "delivery_types": ["IN_PERSON", "SHIPPING_ONSITE"],
        "location": "Evansville, IN",
    }


# --- `list` rows ------------------------------------------------------------


def test_list_rows_get_delivery_types_and_undescribed_rows_stay_null(capsys):
    """A tile Facebook never described reports null (UNKNOWN), never []. The
    live case is Facebook's injected notification tile, whose listing data comes
    from the notifications feed rather than the search payload."""
    page = _FakePage({
        READ_DELIVERY_CAPTURE_JS: {
            "deliveryTypes": {"111": ["IN_PERSON"], "222": ["IN_PERSON", "SHIPPING_ONSITE"]},
            "locationText": {},
            "conflicts": {},
            "payloads": 3,
            "parseErrors": 0,
        },
    })
    client = FacebookClient.__new__(FacebookClient)
    items = [{"item_id": "111"}, {"item_id": "222"}, {"item_id": "27542838245367180"}]

    client._attach_delivery_types(page, items)

    assert items[0]["delivery_types"] == ["IN_PERSON"]
    assert items[1]["delivery_types"] == ["IN_PERSON", "SHIPPING_ONSITE"]
    assert items[2]["delivery_types"] is None
    warning = capsys.readouterr().err
    assert "must never be read as 'no shipping offered'" in warning
    assert "27542838245367180" in warning


def test_no_warning_when_every_row_is_described(capsys):
    page = _FakePage({
        READ_DELIVERY_CAPTURE_JS: {
            "deliveryTypes": {"111": ["IN_PERSON"]},
            "locationText": {},
            "conflicts": {},
            "payloads": 1,
            "parseErrors": 0,
        },
    })
    client = FacebookClient.__new__(FacebookClient)
    items = [{"item_id": "111"}]

    client._attach_delivery_types(page, items)

    assert capsys.readouterr().err == ""


# --- Model contract ---------------------------------------------------------


def test_model_rejects_an_empty_delivery_types_list():
    """[] would read as 'this seller offers no fulfillment at all'."""
    with pytest.raises(ValueError, match="must be None .unknown. or a non-empty list"):
        MarketplaceListing(
            item_id="1", title="Bricks", price="$10", url="/marketplace/item/1/",
            delivery_types=[],
        )


def test_model_keeps_facebook_tokens_verbatim():
    """Reported raw so a token Facebook adds later is never silently dropped."""
    listing = MarketplaceListing(
        item_id="1", title="Bricks", price="$10", url="/marketplace/item/1/",
        delivery_types=["IN_PERSON", "PUBLIC_MEETUP", "DOOR_PICKUP", "SHIPPING_ONSITE"],
    )

    assert listing.delivery_types == [
        "IN_PERSON", "PUBLIC_MEETUP", "DOOR_PICKUP", "SHIPPING_ONSITE"
    ]


def test_unknown_delivery_types_stays_none():
    listing = MarketplaceListing(
        item_id="1", title="Bricks", price="$10", url="/marketplace/item/1/",
    )

    assert listing.delivery_types is None


# --- "Ships to you" is not a location ---------------------------------------


def test_shipping_placeholder_is_not_reported_as_a_location():
    """Facebook renders "Ships to you" in a tile's location slot for a distant
    listing (it is a distance decision, not a fulfillment one). Recording it as
    a location gave downstream consumers a place name that does not exist."""
    page = _FakePage({
        LIST_PAGE_LISTINGS_JS: {
            "rows": [
                {"item_id": "1", "title": "LEGO Duplo Bath Time 10413", "price": "$12",
                 "original_price": None, "location": TILE_SHIPPING_PLACEHOLDER_LOCATION,
                 "url": "/marketplace/item/1/"},
                {"item_id": "2", "title": "Legos 5lbs", "price": "$60",
                 "original_price": None, "location": "Newburgh, IN",
                 "url": "/marketplace/item/2/"},
            ],
            "unparsed": [],
        },
    })
    client = FacebookClient.__new__(FacebookClient)

    rows = client._extract_list_page_listings(page)

    assert rows[0]["location"] is None
    assert rows[1]["location"] == "Newburgh, IN"
    assert MarketplaceListing(**rows[0]).location is None
