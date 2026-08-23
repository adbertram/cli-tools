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
  - ``marketplace_item_delivery_post_id_alias.html`` -- captured live 2026-08-04
    from ``/marketplace/item/28800686242866906/``, the "Lego Lot" listing that
    `marketplace get` refused to read. Facebook files the node under its LISTING
    id 1533173811265557 and publishes the requested id as ``story.post_id`` and
    ``product_item.id``. This is the fixture for the id-alias resolution.
  - ``marketplace_search_pagination_response.txt`` -- the verbatim body of a
    Relay pagination response served while scrolling a Marketplace search. This
    is the ONLY transport that carries fulfillment for scroll-loaded tiles, so
    it is replayed here through a real XHR rather than parsed directly. It also
    carries the per-listing ``is_sold``/``is_pending``/``is_live`` booleans and
    ``primary_listing_photo`` that the list surface reports.

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
# One listing, two ids: the URL/tile id Facebook's notification tile links by,
# and the listing id its own payload node is keyed by.
ALIAS_POST_ID = "28800686242866906"
ALIAS_LISTING_ID = "1533173811265557"


def _capture_stub(**overrides) -> dict:
    """A capture in the exact shape ``INSTALL_DELIVERY_CAPTURE_JS`` writes."""
    capture = {
        "deliveryTypes": {},
        "locationText": {},
        "availability": {},
        "primaryImage": {},
        "seller": {},
        "aliases": {},
        "conflicts": {},
        "availabilityConflicts": {},
        "aliasConflicts": {},
        "payloads": 1,
        "parseErrors": 0,
    }
    capture.update(overrides)
    return capture


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
    # Facebook's own listing-state booleans ride in the same node.
    assert capture["availability"][IN_PERSON_ITEM_ID] == {
        "is_sold": False, "is_pending": False, "is_live": True
    }


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
    assert capture["aliases"] == {}
    assert capture["parseErrors"] == 0


def test_capture_reads_listing_state_without_delivery_types():
    """The status command must read state from a listing node whose fulfillment
    fields are absent, without weakening the full-detail fulfillment contract."""
    capture = _capture_from(
        '<script type="application/json">'
        '{"__typename":"GroupCommerceProductItem","id":"status-only",'
        '"is_sold":false,"is_pending":false,"is_live":true}'
        "</script>"
    )

    assert capture["deliveryTypes"] == {}
    assert capture["availability"]["status-only"] == {
        "is_sold": False,
        "is_pending": False,
        "is_live": True,
    }


# --- One listing, two ids ---------------------------------------------------


def test_capture_indexes_facebooks_own_id_alias_for_a_listing():
    """`marketplace get 28800686242866906` failed on a page that described the
    listing in full -- under its OTHER id. Facebook publishes the mapping."""
    capture = _capture_from(
        (FIXTURES / "marketplace_item_delivery_post_id_alias.html").read_text(encoding="utf-8")
    )

    assert capture["deliveryTypes"][ALIAS_LISTING_ID] == ["IN_PERSON", "PUBLIC_MEETUP"]
    assert ALIAS_POST_ID not in capture["deliveryTypes"]
    assert capture["aliases"][ALIAS_POST_ID] == ALIAS_LISTING_ID
    assert capture["aliasConflicts"] == {}


def test_get_resolves_a_listing_requested_by_its_post_id():
    """The documented recovery path for an undescribed `list` row: a definitive
    read of the listing Facebook's search payload never covered."""
    html = (FIXTURES / "marketplace_item_delivery_post_id_alias.html").read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        client = FacebookClient.__new__(FacebookClient)
        fulfillment = client._extract_listing_fulfillment(page, ALIAS_POST_ID)
        browser.close()

    assert fulfillment == {
        "delivery_types": ["IN_PERSON", "PUBLIC_MEETUP"],
        "location": "Evansville, IN",
        "availability": "Available",
        "seller_id": "100069931946880",
        "seller_name": "Larry Gerbig",
    }


def test_a_listing_requested_by_its_listing_id_still_resolves_directly():
    """The alias index must not displace a direct hit."""
    capture = _capture_stub(
        deliveryTypes={"111": ["IN_PERSON"], "222": ["SHIPPING_ONSITE"]},
        aliases={"111": "222"},
    )

    assert FacebookClient._resolve_captured_listing_id(capture, "111") == "111"
    assert FacebookClient._resolve_captured_listing_id(capture, "999") is None


def test_an_alias_to_an_undescribed_listing_is_not_a_hit():
    """An alias that points at a listing this page never described resolves to
    nothing, so the caller still fails loudly."""
    capture = _capture_stub(deliveryTypes={}, aliases={"111": "222"})

    assert FacebookClient._resolve_captured_listing_id(capture, "111") is None


def test_conflicting_id_aliases_fail_loudly():
    """Two listings claiming the same alias would make one of them answer for
    the other."""
    page = _FakePage({
        READ_DELIVERY_CAPTURE_JS: _capture_stub(
            deliveryTypes={"111": ["IN_PERSON"]},
            aliasConflicts={"999": ["111", "222"]},
        ),
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="conflicting listing-id aliases"):
        client._read_delivery_capture(page)


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
    # The same response answers "is it still for sale?" and "what does it look
    # like?", so the list surface needs no per-listing detail navigation.
    assert len(capture["availability"]) == len(capture["deliveryTypes"])
    assert all(
        set(state) == {"is_sold", "is_pending", "is_live"}
        for state in capture["availability"].values()
    )
    assert len(capture["primaryImage"]) == len(capture["deliveryTypes"])
    assert all(uri.startswith("https://") for uri in capture["primaryImage"].values())
    assert capture["availabilityConflicts"] == {}
    # ...and "who is selling it", so `list` answers without a per-item detail call.
    assert len(capture["seller"]) == len(capture["deliveryTypes"])
    assert all(
        seller["id"] and seller["name"] for seller in capture["seller"].values()
    )
    # Distinct sellers, not one leaked across every row.
    assert len({seller["id"] for seller in capture["seller"].values()}) > 1


# --- Seller capture ---------------------------------------------------------


@pytest.mark.parametrize("fixture,item_id,seller_id,seller_name", [
    ("marketplace_item_delivery_in_person.html", IN_PERSON_ITEM_ID,
     "61590475513218", "Zach Broson"),
    ("marketplace_item_delivery_shipping.html", SHIPPING_ITEM_ID,
     "100060779521742", "Frye Cristina"),
    ("marketplace_item_delivery_post_id_alias.html", ALIAS_LISTING_ID,
     "100069931946880", "Larry Gerbig"),
])
def test_detail_page_capture_reads_the_listings_seller(
    fixture, item_id, seller_id, seller_name
):
    """The seller comes from Facebook's own ``marketplace_listing_seller`` node.

    The detail page also renders a "Seller information" heading, and the
    description extractor already finds it -- to mark where the description
    ends, then discards it. Reading the payload instead means the search
    surface answers too, and a display name Facebook renders differently per
    viewer cannot change the answer.
    """
    capture = _capture_from((FIXTURES / fixture).read_text(encoding="utf-8"))
    assert capture["seller"][item_id] == {"id": seller_id, "name": seller_name}


def test_a_listing_whose_payload_names_no_seller_reports_null_not_an_error():
    """Unlike ``delivery_types``, an absent seller is not fatal.

    An empty ``delivery_types`` reads as "this seller offers no fulfillment",
    which is a wrong answer a consumer acts on. An absent seller cannot be
    misread as a DIFFERENT seller, so it is reported as null.
    """
    page = _FakePage({
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 1},
        READ_DELIVERY_CAPTURE_JS: _capture_stub(deliveryTypes={"999": ["IN_PERSON"]}),
    })
    client = FacebookClient.__new__(FacebookClient)

    fulfillment = client._extract_listing_fulfillment(page, "999")
    assert fulfillment["seller_id"] is None
    assert fulfillment["seller_name"] is None
    assert fulfillment["delivery_types"] == ["IN_PERSON"]


def test_the_capture_shape_check_covers_the_seller_map():
    """`seller` is in CAPTURE_MAPS, so a payload change that drops it fails loudly
    instead of reporting every listing as having no seller."""
    from facebook_cli.client import CAPTURE_MAPS

    assert "seller" in CAPTURE_MAPS
    stub = _capture_stub(deliveryTypes={"999": ["IN_PERSON"]})
    del stub["seller"]
    page = _FakePage({
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 1},
        READ_DELIVERY_CAPTURE_JS: stub,
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="unexpected shape"):
        client._extract_listing_fulfillment(page, "999")


# --- Fail-loud contract on `get` --------------------------------------------


def test_get_fails_loudly_when_facebook_describes_no_delivery_types():
    """An unreadable fulfillment model must never be reported as a listing that
    does not ship."""
    page = _FakePage({
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 3},
        READ_DELIVERY_CAPTURE_JS: _capture_stub(deliveryTypes={"111": ["IN_PERSON"]}),
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="did not describe the fulfillment options"):
        client._extract_listing_fulfillment(page, "999")


def test_get_fails_loudly_on_an_empty_delivery_types_array():
    page = _FakePage({
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 1},
        READ_DELIVERY_CAPTURE_JS: _capture_stub(deliveryTypes={"999": []}),
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="did not describe the fulfillment options"):
        client._extract_listing_fulfillment(page, "999")


def test_conflicting_payloads_fail_loudly():
    """If two payloads disagree about a listing, no listing's read is trusted."""
    page = _FakePage({
        READ_DELIVERY_CAPTURE_JS: _capture_stub(
            deliveryTypes={"999": ["IN_PERSON"]},
            conflicts={"999": [["IN_PERSON"], ["IN_PERSON", "SHIPPING_ONSITE"]]},
        ),
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="conflicting delivery_types"):
        client._read_delivery_capture(page)


def test_conflicting_listing_state_fails_loudly():
    """A stale "live" beside a fresh "sold" is the one answer a consumer
    re-checking a saved listing must not get wrong."""
    page = _FakePage({
        READ_DELIVERY_CAPTURE_JS: _capture_stub(
            deliveryTypes={"999": ["IN_PERSON"]},
            availabilityConflicts={"999": [
                {"is_sold": False, "is_pending": False, "is_live": True},
                {"is_sold": True, "is_pending": False, "is_live": False},
            ]},
        ),
    })
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="conflicting listing-state booleans"):
        client._read_delivery_capture(page)


def test_a_capture_missing_a_map_fails_loudly():
    """The capture JS and this reader must not drift apart silently."""
    stub = _capture_stub()
    del stub["aliases"]
    page = _FakePage({READ_DELIVERY_CAPTURE_JS: stub})
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="unexpected shape"):
        client._read_delivery_capture(page)


def test_uninstalled_capture_fails_loudly():
    page = _FakePage({READ_DELIVERY_CAPTURE_JS: None})
    client = FacebookClient.__new__(FacebookClient)

    with pytest.raises(ClientError, match="capture was not installed"):
        client._read_delivery_capture(page)


def test_listing_fulfillment_returns_location_when_facebook_carries_one():
    page = _FakePage({
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 1},
        READ_DELIVERY_CAPTURE_JS: _capture_stub(
            deliveryTypes={"999": ["IN_PERSON", "SHIPPING_ONSITE"]},
            locationText={"999": "Evansville, IN"},
            availability={"999": {"is_sold": False, "is_pending": False, "is_live": True}},
        ),
    })
    client = FacebookClient.__new__(FacebookClient)

    assert client._extract_listing_fulfillment(page, "999") == {
        "delivery_types": ["IN_PERSON", "SHIPPING_ONSITE"],
        "location": "Evansville, IN",
        "availability": "Available",
        "seller_id": None,
        "seller_name": None,
    }


def test_listing_availability_is_unknown_when_facebook_omits_the_booleans():
    """None means unknown. It must not be reported as an available listing."""
    page = _FakePage({
        INSTALL_DELIVERY_CAPTURE_JS: {"installed": True, "listings": 1},
        READ_DELIVERY_CAPTURE_JS: _capture_stub(deliveryTypes={"999": ["IN_PERSON"]}),
    })
    client = FacebookClient.__new__(FacebookClient)

    assert client._extract_listing_fulfillment(page, "999")["availability"] is None


# --- `list` rows ------------------------------------------------------------


def test_list_rows_get_delivery_types_and_undescribed_rows_stay_null(capsys):
    """A tile Facebook never described reports null (UNKNOWN), never []. The
    live case is Facebook's injected notification tile, whose listing data comes
    from the notifications feed rather than the search payload."""
    page = _FakePage({
        READ_DELIVERY_CAPTURE_JS: _capture_stub(
            deliveryTypes={"111": ["IN_PERSON"], "222": ["IN_PERSON", "SHIPPING_ONSITE"]},
            payloads=3,
        ),
    })
    client = FacebookClient.__new__(FacebookClient)
    items = [{"item_id": "111"}, {"item_id": "222"}, {"item_id": "27542838245367180"}]

    client._attach_captured_listing_fields(page, items)

    assert items[0]["delivery_types"] == ["IN_PERSON"]
    assert items[1]["delivery_types"] == ["IN_PERSON", "SHIPPING_ONSITE"]
    assert items[2]["delivery_types"] is None
    assert items[2]["availability"] is None
    assert items[2]["primary_image_url"] is None
    warning = capsys.readouterr().err
    assert "must never be read as 'no shipping offered'" in warning
    assert "27542838245367180" in warning


def test_list_rows_report_facebooks_listing_state_and_tile_photo():
    """A consumer re-checking N saved listings for sold-state gets the answer
    from the search payload, without N detail navigations."""
    page = _FakePage({
        READ_DELIVERY_CAPTURE_JS: _capture_stub(
            deliveryTypes={"111": ["IN_PERSON"], "222": ["IN_PERSON"], "333": ["IN_PERSON"]},
            availability={
                "111": {"is_sold": False, "is_pending": False, "is_live": True},
                "222": {"is_sold": True, "is_pending": False, "is_live": False},
                "333": {"is_sold": False, "is_pending": True, "is_live": True},
            },
            primaryImage={"111": "https://scontent.xx.fbcdn.net/v/photo1.jpg"},
        ),
    })
    client = FacebookClient.__new__(FacebookClient)
    items = [{"item_id": "111"}, {"item_id": "222"}, {"item_id": "333"}]

    client._attach_captured_listing_fields(page, items)

    assert [item["availability"] for item in items] == ["Available", "Sold", "Pending"]
    assert items[0]["primary_image_url"] == "https://scontent.xx.fbcdn.net/v/photo1.jpg"
    # A described listing with no tile photo reports None, not a guessed URL.
    assert items[1]["primary_image_url"] is None


def test_list_rows_resolve_a_tile_linked_by_its_post_id():
    """The tile href and the payload node can name the same listing by
    different ids."""
    page = _FakePage({
        READ_DELIVERY_CAPTURE_JS: _capture_stub(
            deliveryTypes={ALIAS_LISTING_ID: ["IN_PERSON", "PUBLIC_MEETUP"]},
            availability={
                ALIAS_LISTING_ID: {"is_sold": False, "is_pending": False, "is_live": True}
            },
            aliases={ALIAS_POST_ID: ALIAS_LISTING_ID},
        ),
    })
    client = FacebookClient.__new__(FacebookClient)
    items = [{"item_id": ALIAS_POST_ID}]

    client._attach_captured_listing_fields(page, items)

    assert items[0]["delivery_types"] == ["IN_PERSON", "PUBLIC_MEETUP"]
    assert items[0]["availability"] == "Available"


def test_no_warning_when_every_row_is_described(capsys):
    page = _FakePage({
        READ_DELIVERY_CAPTURE_JS: _capture_stub(deliveryTypes={"111": ["IN_PERSON"]}),
    })
    client = FacebookClient.__new__(FacebookClient)
    items = [{"item_id": "111"}]

    client._attach_captured_listing_fields(page, items)

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
