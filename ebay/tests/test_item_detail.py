"""Offline tests for the eBay item-detail parser (``parse_item_detail``).

These never hit eBay: they feed ``parse_item_detail`` the same page-state dict
shape that ``ITEM_DETAIL_JS`` returns and assert the resulting ``ItemDetail``.
The JSON-LD block mirrors a real ``/itm/<id>`` schema.org ``Product`` captured
against the live session (item 127992747834).
"""
import pytest

from ebay_cli.browser_client import parse_item_detail, BrowserError
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


def test_parse_item_detail_captcha_raises():
    state = _bin_page_state()
    state["captcha"] = True
    with pytest.raises(BrowserError, match="CAPTCHA"):
        parse_item_detail("127992747834", state)
