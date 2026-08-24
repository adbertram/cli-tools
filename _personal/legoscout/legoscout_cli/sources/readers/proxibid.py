#!/usr/bin/env python3
"""Proxibid: BLOCKED. Imperva 'Error 15 - access denied' to every access path.

curl, WebFetch and the in-app browser all get the same wall. Per the project's
hard rules, stop the source rather than work around it.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "proxibid"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "auction_end_date": "the lot page carries the close time beside the bid "
                        "box, and the category page renders time-remaining. "
                        "BOTH answer Imperva HTTP 403 to curl (re-checked "
                        "live 2026-08-06), so this is a bot wall, not a parse "
                        "gap. Per the project's hard rules, stop the source "
                        "rather than work around it",
    "available_fulfillment": "lot page 'Shipping and Pickup Information': "
                             "Pickup Terms + Shipping. BLOCKED: the site "
                             "answers Imperva 'Error 15 - access denied' to "
                             "curl, WebFetch and the in-app browser alike, so "
                             "this is a bot wall, not a parse gap -- per the "
                             "project's hard rules, stop the source rather "
                             "than work around it",
    "item_location": "lot page 'Shipping and Pickup Information' -> Pickup "
                     "Terms; same Imperva block applies",
    "seller_id": "lot page seller/house block, also shown on the "
                 "`/for-sale/art-antiques-collectibles/legos` category page "
                 "beside price and time-remaining. BLOCKED: same Imperva "
                 "wall. Per the project's hard rules, stop the source rather "
                 "than work around it.",
    "seller_name": "same block as `seller_id`; same Imperva block applies. "
                   "The category page is the surface that renders the house "
                   "name.",
}


# This source publishes no destination rate at all, so an explicit unquoted
# answer with a reason IS the answer. See listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "Proxibid houses invoice freight after the sale, and the lot page is "
    "unreadable in any case: www.proxibid.com answers Imperva HTTP 403 to "
    "curl on both the lot page and the category page (re-checked live "
    "2026-08-06). Per the project's hard rules, stop the source rather than "
    "work around it")
