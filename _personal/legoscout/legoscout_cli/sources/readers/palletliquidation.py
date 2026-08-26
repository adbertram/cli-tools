#!/usr/bin/env python3
"""Pallet Liquidation Warehouse: a single-retailer storefront IS the seller.

`seller_name` is the same string on every listing, so it is answered without a
CLI call or an HTTP fetch.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "palletliquidation"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

SELLER = "Pallet Liquidation Warehouse"

NEEDS_PAGE_READ = {
    "available_fulfillment": "WooCommerce Store API exposes no fulfillment "
                             "field; source is under a demotion recommendation",
    "item_location": "no fulfillment or location field in the WooCommerce Store API",
    "seller_id": "Single-retailer storefront. Pallet Liquidation Warehouse sells "
                 "its own inventory and publishes no per-listing seller, so "
                 "there is no id to record.",
}


def seller_name(deal):
    """The source IS the seller. Constant for every listing, not read off a page."""
    return SELLER, "{'const': %r}=%r" % (SELLER, SELLER)


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "Pallet Liquidation Warehouse is a fixed-price WooCommerce retailer; "
    "a pallet is bought outright, never bid on")


# This source publishes no destination rate at all, so an explicit unquoted
# answer with a reason IS the answer. See listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "a pallet's freight is quoted at WooCommerce checkout, not on the "
    "product page, and the Store API exposes no shipping field. Treat the "
    "listed price as ex-works and estimate freight separately")
