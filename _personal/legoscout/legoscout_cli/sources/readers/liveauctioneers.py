#!/usr/bin/env python3
"""LiveAuctioneers: item pages are Incapsula-blocked to curl; WebFetch renders them.

Every field here needs a human or an agent page read. `NEEDS_PAGE_READ` says
where to look.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "liveauctioneers"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "auction_end_date": "the item page states the SESSION start ('Aug 26, "
                        "2026 3:00 PM EDT'), and a per-lot close is decided "
                        "live during the sale. curl gets an Incapsula "
                        "challenge, so the page needs a browser read. Store "
                        "the session start in ISO and say in "
                        "`evidence_summary` that it is the session, not the "
                        "lot",
    "available_fulfillment": "item page labels 'Local pickup available' / "
                             "'Ship with LiveAuctioneers' / 'Arrange Your Own "
                             "Shipping'",
    "item_location": "item page states the house's city/state (e.g. 'Ottawa, "
                     "IL'); direct curl is Incapsula-blocked but WebFetch "
                     "renders it. No ZIP is published, so the town+state line "
                     "is the whole answer",
    "seller_id": "the auction house id in the lot's own image URL path: "
                 "`p1.liveauctioneers.com/<sellerId>/<catalogId>/<itemId>_<n>_x.jpg`. "
                 "Unverified as a reader; the image URLs are captured during "
                 "the crawl, so the id is in hand.",
    "seller_name": "the `/c/lego/` category page's inline schema.org ItemList "
                   "-> `offers.seller.name`, the auction house. That blob is "
                   "NOT inside a `<script type=\"application/ld+json\">` tag -- "
                   "brace-match from each literal `{\"@type\":\"Product\"` "
                   "instead. One curl of `/c/lego/` yields the house for "
                   "EVERY lot; item pages are Incapsula-blocked to curl and "
                   "need WebFetch.",
}


# This source publishes no destination rate at all, so an explicit unquoted
# answer with a reason IS the answer. See listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "LiveAuctioneers houses invoice freight after the sale through their "
    "own shipper, so no rate exists at bid time. Estimate it from the house "
    "address; never record 0.0")
