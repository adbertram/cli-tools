"""Offline tests for the eBay item-detail parser (``parse_item_detail``).

These never hit eBay: they feed ``parse_item_detail`` the same page-state dict
shape that ``ITEM_DETAIL_JS`` returns and assert the resulting ``ItemDetail``.
The JSON-LD block mirrors a real ``/itm/<id>`` schema.org ``Product`` captured
against the live session (item 127992747834).
"""
import pytest

from ebay_cli.browser_client import (
    ITEM_DETAIL_JS,
    BrowserError,
    _numeric_price,
    parse_item_detail,
)
from ebay_cli.models.item_detail import ItemDetail


PRODUCT_JSONLD = {
    "@type": "Product",
    "@context": "https://schema.org",
    "name": "LEGO White Technic, Panel Fairing #13/14 Large Short, Side A And B. 64394, 64680",
    "image": [
        {"@type": "ImageObject", "url": "https://i.ebayimg.com/images/g/Sy8AAeSwstFotgtJ/s-l1600.jpg"},
    ],
    "offers": {
        "@type": "Offer",
        "url": "https://www.ebay.com/itm/127992747834",
        "itemCondition": "https://schema.org/NewCondition",
        "availability": "https://schema.org/InStock",
        "priceCurrency": "USD",
        "price": "2.95",
        "shippingDetails": [
            {
                "@type": "OfferShippingDetails",
                "shippingRate": {"@type": "MonetaryAmount", "value": "6.25", "currency": "USD"},
            }
        ],
    },
    "brand": {"@type": "Brand", "name": "LEGO"},
}


def _bin_page_state():
    return {
        "url": "https://www.ebay.com/itm/127992747834",
        "doc_title": "LEGO White Technic ... | eBay",
        "dom_title": None,
        "price_primary": "US $2.95/ea",
        "bin_price": "US $2.95/ea",
        "bid_count": None,
        "time_left": None,
        "condition": "New",
        "quantity": "5 available",
        "seller": "Legos and Collectibles",
        "image": None,
        # Captured live from item 127992747834 on 2026-07-26: shipping row
        # only, no local-pickup row.
        "pickup_dom": None,
        "shipping_values_dom": (
            "US $6.25 USPS Ground Advantage®. See detailsfor shipping"
            "Located in: Pensacola, Florida, United States"
        ),
        "has_bid": False,
        "has_best_offer": False,
        "ended_banner": False,
        "error_page": False,
        "captcha": False,
        "jsonld": [{"@type": "ItemPage"}, PRODUCT_JSONLD],
    }


def test_parse_item_detail_bin_from_jsonld():
    detail = parse_item_detail("127992747834", _bin_page_state())

    assert isinstance(detail, ItemDetail)
    assert detail.item_id == "127992747834"
    assert detail.title.startswith("LEGO White Technic")
    assert detail.price == "2.95"
    assert detail.currency == "USD"
    assert detail.condition == "New"
    assert detail.availability == "InStock"
    assert detail.ended is False
    assert detail.shipping_price == "6.25"
    assert detail.format == "Buy It Now"
    assert detail.bin_price == "2.95"
    assert detail.current_bid is None
    assert detail.brand == "LEGO"
    assert detail.seller == "Legos and Collectibles"
    assert detail.quantity == "5 available"
    assert detail.image_url == "https://i.ebayimg.com/images/g/Sy8AAeSwstFotgtJ/s-l1600.jpg"
    assert detail.url == "https://www.ebay.com/itm/127992747834"
    assert detail.ships is True
    assert detail.local_pickup is False
    assert detail.item_location == "Pensacola, Florida, United States"


def test_parse_item_detail_auction_from_dom():
    """Auction with no Product JSON-LD: price/bids/time-left come from the DOM."""
    state = {
        "url": "https://www.ebay.com/itm/999888777666",
        "doc_title": "LEGO auction | eBay",
        "dom_title": "LEGO Bulk Auction Lot 10 lbs",
        "price_primary": "US $10.50",
        "bin_price": None,
        "bid_count": "3 bids",
        "time_left": "6d 4h",
        "shipping_dom": "US $8.99 USPS Priority Mail",
        "pickup_dom": None,
        "shipping_values_dom": (
            "US $8.99 USPS Priority Mail. See detailsfor shipping"
            "Located in: Owensboro, Kentucky, United States"
        ),
        "condition": "Used",
        "quantity": None,
        "seller": "brickseller",
        "image": "https://i.ebayimg.com/images/g/abc/s-l1600.jpg",
        "has_bid": True,
        "has_best_offer": False,
        "ended_banner": False,
        "error_page": False,
        "captcha": False,
        "jsonld": [],
    }

    detail = parse_item_detail("999888777666", state)

    assert detail.title == "LEGO Bulk Auction Lot 10 lbs"
    assert detail.format == "Auction"
    assert detail.bids == 3
    assert detail.current_bid == "10.50"
    assert detail.price == "10.50"
    assert detail.time_left == "6d 4h"
    assert detail.bin_price is None
    assert detail.condition == "Used"
    assert detail.shipping_price == "8.99"  # parsed from DOM when JSON-LD absent
    assert detail.currency == "USD"
    assert detail.ships is True
    assert detail.local_pickup is False
    assert detail.item_location == "Owensboro, Kentucky, United States"


def test_parse_item_detail_pickup_and_shipping():
    """Item 157780039676: both fulfillment rows present (live capture 2026-07-26)."""
    state = _bin_page_state()
    state["pickup_dom"] = "Free local pickup 30 mi from 47711. See map"
    state["shipping_values_dom"] = (
        "US $5.58 delivery in 2–4 daysGet it between Wed, Jul 29 and Fri, Jul 31 "
        "to 47711. See detailsfor shippingLocated in: Owensboro, Kentucky, United States"
    )

    detail = parse_item_detail("157780039676", state)

    assert detail.local_pickup is True
    assert detail.ships is True
    assert detail.item_location == "Owensboro, Kentucky, United States"


def test_parse_item_detail_pickup_only():
    """Item 388666458525: pickup row only, no shipping row (live capture 2026-07-26).

    This is the case a null ``shipping_price`` alone cannot distinguish from a
    rate that failed to parse.
    """
    state = _bin_page_state()
    state["pickup_dom"] = "Free local pickup 45 mi from 47711. See map"
    state["shipping_values_dom"] = None
    state["jsonld"] = []
    state["dom_title"] = "Original Lego Lightsaber Blade"

    detail = parse_item_detail("388666458525", state)

    assert detail.local_pickup is True
    assert detail.ships is False
    assert detail.item_location is None
    assert detail.shipping_price is None


def test_numeric_price_ignores_prose_punctuation():
    """The section heading a pickup-only page carries is not a shipping rate."""
    assert _numeric_price("Shipping, returns, and payments") is None
    assert _numeric_price("US $5.58 ") == "5.58"
    assert _numeric_price("US $1,234.00") == "1234.00"


def test_parse_item_detail_shipping_row_without_a_quote():
    """A shipping row that quotes nothing is not a shipping offer.

    The row always ends with a clipped "See details for shipping" link, so the
    bare word "shipping" must not be read as a rate.
    """
    state = _bin_page_state()
    state["pickup_dom"] = "Free local pickup 45 mi from 47711. See map"
    state["shipping_values_dom"] = (
        "Does not ship to United States. See detailsfor shipping"
        "Located in: Owensboro, Kentucky, United States"
    )

    detail = parse_item_detail("157780039676", state)

    assert detail.ships is False
    assert detail.local_pickup is True
    assert detail.item_location == "Owensboro, Kentucky, United States"


def test_parse_item_detail_free_shipping_row():
    state = _bin_page_state()
    state["pickup_dom"] = None
    state["shipping_values_dom"] = (
        "Free shipping. See detailsfor shippingLocated in: Deatsville, Alabama, United States"
    )

    detail = parse_item_detail("127992747834", state)

    assert detail.ships is True
    assert detail.local_pickup is False
    assert detail.item_location == "Deatsville, Alabama, United States"


def test_parse_item_detail_no_fulfillment_rows_raises():
    """Neither row present means the DOM did not load as expected -- fail loudly."""
    state = _bin_page_state()
    state["pickup_dom"] = None
    state["shipping_values_dom"] = None

    with pytest.raises(BrowserError, match="neither a local-pickup nor a shipping"):
        parse_item_detail("127992747834", state)


def test_parse_item_detail_ended_listing():
    state = _bin_page_state()
    state["ended_banner"] = True
    detail = parse_item_detail("127992747834", state)
    assert detail.ended is True


def test_parse_item_detail_removed_item_raises():
    state = _bin_page_state()
    state["jsonld"] = []
    state["dom_title"] = None
    state["error_page"] = True
    with pytest.raises(BrowserError, match="not found or the listing was removed"):
        parse_item_detail("123456", state)


def test_item_detail_js_uses_the_verified_fulfillment_selectors():
    """Pin the class names captured from live item pages on 2026-07-26.

    eBay's pickup row is ``ux-labels-values--localPickup`` -- a
    ``.ux-labels-values--pickup`` selector matches nothing, which would make
    every listing look shipping-only.
    """
    assert ".ux-labels-values--localPickup .ux-labels-values__values" in ITEM_DETAIL_JS
    assert ".ux-labels-values--shipping .ux-labels-values__values" in ITEM_DETAIL_JS


def test_parse_item_detail_captcha_raises():
    state = _bin_page_state()
    state["captcha"] = True
    with pytest.raises(BrowserError, match="CAPTCHA"):
        parse_item_detail("127992747834", state)
