#!/usr/bin/env python3
"""Nextdoor: the CLI exposes no classifieds surface and no listing URL exists.

The feed row is the only surface, and it carries a display name and nothing else.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "nextdoor"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "available_fulfillment": "CLI exposes no classifieds surface; no listing URL "
                             "exists",
    "item_location": "CLI exposes no classifieds surface; no listing URL exists",
    "seller_id": "Nextdoor publishes no stable public seller key on a "
                 "classified. The feed row carries the author's display name "
                 "only. Record null for the id and the display name for the name.",
    "seller_name": "`nextdoor feed` -> `seller`, the author's display name "
                   "(`nextdoor_cli/client.py:520` maps `authorName.displayName` "
                   "to it). The crawl row already holds it, so record it from "
                   "the feed row.",
}


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "a Nextdoor classified is a neighbour-to-neighbour advert at a stated "
    "price; the platform runs no bidding")


# This source publishes no destination rate at all, so an explicit unquoted
# answer with a reason IS the answer. See listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "a Nextdoor classified is collection from a neighbour; the platform "
    "carries no shipping surface and quotes no rate")
