#!/usr/bin/env python3
"""Reddit: DORMANT and hard-blocked. Do not probe.

Every access path is blocked pending a Reddit OAuth 'script' credential in the
cli-tools secret manager.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "reddit"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "available_fulfillment": "source is hard-blocked; no page can be read",
    "item_location": "source is hard-blocked; no page can be read",
    "seller_id": "the redditor's username (`u/<name>`) on the post. DORMANT "
                 "source: every access path is blocked pending a Reddit OAuth "
                 "'script' credential in the cli-tools secret manager. Do not "
                 "probe.",
    "seller_name": "same as `seller_id`: the redditor's username is both the key "
                   "and the display name. DORMANT; do not probe.",
}


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "r/Legomarket is a forum thread, not a marketplace: a price is a "
    "comment and nothing closes")


# This source publishes no destination rate at all, so an explicit unquoted
# answer with a reason IS the answer. See listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "r/Legomarket is a forum thread. Shipping is whatever two people agree "
    "in a comment; the platform quotes nothing")
