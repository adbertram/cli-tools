#!/usr/bin/env python3
"""Poshmark: a flat prepaid label, and no `listings get` surface to read.

Every field here needs a human or an agent page read. `NEEDS_PAGE_READ` says
where to look.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "poshmark"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "shipping_estimate": "Poshmark charges one flat prepaid-label rate to the "
                         "buyer, shown on the listing's SHIPPING line. It is "
                         "a platform constant rather than a per-listing "
                         "number, so read it once off a live listing and "
                         "record it with the date it was read",
    "available_fulfillment": "listing SHIPPING line (flat prepaid label). "
                             "NOTE: the phrase 'local pick up' in Poshmark "
                             "HTML is a moderation banned-word list, not a "
                             "listing signal",
    "item_location": "ships only; no pickup point is published",
    "seller_id": "`poshmark listings search` -> `lister_id`, the closet's "
                 "opaque key (verified live 2026-08-05: "
                 "'64da83052061e43fa12eaed4'). The crawl already holds it, so "
                 "record it from the search row. No `listings get` surface "
                 "exists, so there is no per-listing read to hang a reader "
                 "on.",
    "seller_name": "the closet's @handle on the listing page, beside the "
                   "photo. The CLI search tile does not carry it and there is "
                   "no `listings get` surface, so it needs the direct-URL "
                   "page read the source already makes for availability.",
}


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "Poshmark sells at a fixed price with an optional offer; a closet "
    "listing has no closing time")
