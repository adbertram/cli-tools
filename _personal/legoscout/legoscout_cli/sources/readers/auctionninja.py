#!/usr/bin/env python3
"""AuctionNinja: one lot-page fetch answers fulfillment, address and seller.

Lots from the same seller differ, so the lot's own 'Pickup Details' panel
decides -- never the seller's general terms.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "auctionninja"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "auction_end_date": "the lot page's close countdown is rendered "
                        "CLIENT-SIDE: the served HTML carries no ISO "
                        "timestamp, no countdown element and no spelled-out "
                        "date anywhere (checked live 2026-08-06 on "
                        "auctionninja|23026, 263kB of markup). Read the "
                        "'Bidding ends' line off the rendered page with a "
                        "browser, or take the close time from the seller's "
                        "auction index page",
}

_PANEL = "Pickup Details"
# The FIRST `new-shipping-available-icon-detail` block holds the label and the
# address; the second is the 'When to Pickup' window. Read structurally, not by
# scanning the flattened panel: the panel's own labels sit immediately before the
# address and a text scan swallows them into the city name.
_ADDRESS = (r'class="new-shipping-available-icon-detail"\s*>\s*<a[^>]*>(.*?)</a>'
            r'\s*<p>(.*?)</p>')
_SELLER_SLUG = r'<base href="https://www\.auctionninja\.com/([a-z0-9\-_]+)/"'
# NEVER match a bare `auctionninja.com/<slug>/'>Name<` anchor: the page also
# renders a 'Find a Seller' dropdown listing EVERY seller on the platform, and a
# loose pattern returns its first entry ('1920 Enterprises LLC') for every lot.
_SELLER_NAME = (r'class="category-top-heading".*?auctionninja\.com/'
                r'[a-z0-9\-_]+/">([^<]+)</a>')


def fetch(deal):
    url = listing.direct_url(deal)
    return listing.cached((NAMESPACE, url), lambda: listing.http(url))


def available_fulfillment(deal):
    """Lot page 'Pickup Details' panel, which carries a literal
    'Shipping Available' label when THAT lot ships."""
    page = fetch(deal)
    options = ["local_pickup"]
    evidence = ["local_pickup: always (collection at the seller/house)"]
    panel = listing.flatten(listing.window(page, _PANEL, 1200))
    ships = "Shipping Available" in panel
    if ships:
        options.append("shipping")
    evidence.append("shipping: 'Shipping Available' in the Pickup Details "
                    "panel=%s" % ships)
    return options, "; ".join(evidence)


def item_location(deal):
    """Lot page 'Pickup Details' -> the first icon-detail block's address line."""
    text = listing.group(listing.window(fetch(deal), _PANEL), _ADDRESS, 2)
    if text is listing.MISSING:
        raise listing.Undetermined(
            "the Pickup Details panel states no icon-detail address block")
    text = listing.tidy(listing.flatten(text))
    return (listing.trailing_city_state_zip(text),
            "Pickup Details -> %r" % text)


def seller_id(deal):
    """Lot page `<base href="https://www.auctionninja.com/<seller-slug>/">`.

    AuctionNinja namespaces every lot under its seller, so the slug is the
    stable key.
    """
    value = listing.group(fetch(deal), _SELLER_SLUG)
    if value is listing.MISSING:
        raise listing.Undetermined(
            "the lot page carries no <base href> seller slug")
    return value.strip(), "base href slug=%r" % value.strip()


def seller_name(deal):
    """Lot page `category-top-heading` breadcrumb -> the SECOND link
    ('AuctionNinja / Girlfriends Estate Sales')."""
    value = listing.group(fetch(deal), _SELLER_NAME)
    if value is listing.MISSING:
        raise listing.Undetermined(
            "the lot page carries no category-top-heading seller breadcrumb")
    value = listing.flatten(value).strip()
    return value, "category-top-heading=%r" % value


# This source publishes no destination rate at all, so an explicit unquoted
# answer with a reason IS the answer. See listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "AuctionNinja houses invoice freight AFTER the sale, so no rate exists "
    "at bid time. Estimate it from the lot's Pickup Details address with "
    "`legoscout pricing shipping --origin-zip <zip> --weight-lbs <lbs>`; "
    "never record 0.0")
