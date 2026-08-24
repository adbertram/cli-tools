#!/usr/bin/env python3
"""Mercari: `listings get` -> a prepaid label and the seller behind it."""
from __future__ import annotations

from .. import listing

NAMESPACE = "mercari"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "item_location": "`mercari listings get` -> "
                     "`shippingFromArea.shippingFromAreaName` is a STATE only "
                     "('Ohio'), with no city and no ZIP (checked live "
                     "2026-08-06). `pickup_area.resolve` needs a city or a "
                     "ZIP, and Mercari is shipping-only so pickup never "
                     "applies -- record the state verbatim and leave "
                     "`origin_zip` null",
    "shipping_estimate": "`mercari listings get` -> `shippingPayer` decides "
                         "who pays, and `shippingClass.shippingClassName` is "
                         "a weight band ('4 lb'), not a price (checked live "
                         "2026-08-06). When the seller pays, the buyer's "
                         "freight is 0.00 and that is a real quote; when the "
                         "buyer pays, read the rate off the listing page",
}
def fetch(deal):
    lot = listing.lot_id(deal)
    return listing.cached((NAMESPACE, lot),
                          lambda: listing.cli(["mercari", "listings", "get", lot]))


def available_fulfillment(deal):
    """`listings get` -> `shippingPayer`.

    Mercari transacts only through a prepaid label and exposes no pickup
    mechanism at all, so there is no local_pickup rule here.
    """
    payload = fetch(deal)
    listing.require(payload, "shippingPayer.name")
    ships = listing.truthy(payload, "shippingPayer.name")
    if not ships:
        raise listing.Undetermined(
            "the listing offers neither pickup nor shipping, which no live "
            "listing does -- re-read the page")
    return ["shipping"], "shipping: any_of['shippingPayer.name']=['shippingPayer.name']"


def seller_id(deal):
    """`listings get` -> `seller.sellerId`. Stored as TEXT so a numeric key and
    its string form cannot become two sellers."""
    payload = fetch(deal)
    value = listing.dig(payload, "seller.sellerId")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no seller.sellerId")
    if value is not None:
        value = str(value)
    return value, "seller.sellerId=%r" % value


def seller_name(deal):
    """`listings get` -> `seller.sellerName`, the display name ('izzy Uribe').

    `seller.sellerUserName` is the derived handle ('user806901442') and is NOT
    read here.
    """
    payload = fetch(deal)
    value = listing.dig(payload, "seller.sellerName")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no seller.sellerName")
    return value, "seller.sellerName=%r" % value


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "Mercari sells at a fixed price with an optional offer; the listing "
    "stays up until it sells and never closes on a clock")
