#!/usr/bin/env python3
"""America's Thrift Supply: a single-retailer Shopify storefront IS the seller.

The storefront JSON's `vendor` field is a product brand, not a seller, and must
not be used here.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "americasthriftsupply"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

SELLER = "America's Thrift Supply"

NEEDS_PAGE_READ = {
    "available_fulfillment": "`americasthriftsupply products get <handle>` -> "
                             "variants[].requires_shipping",
    "item_location": "single warehouse retailer, ships only",
    "seller_id": "Single-retailer Shopify storefront. America's Thrift Supply "
                 "sells its own inventory and the storefront JSON exposes no "
                 "per-product seller, so there is no id to record.",
    "shipping_estimate": "the storefront JSON has no shipping-rate endpoint -- "
                         "real-time rates need a live cart/checkout session the "
                         "read-only CLI never creates. Estimate with `legoscout "
                         "pricing shipping --house \"America's Thrift Supply\"`; "
                         "never leave it null.",
}


def seller_name(deal):
    """The source IS the seller. Constant for every listing, not read off a page."""
    return SELLER, "{'const': %r}=%r" % (SELLER, SELLER)


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "America's Thrift Supply is a fixed-price Shopify storefront: every "
    "bale and mystery box carries an Add to cart price and no lot ever "
    "closes")
