#!/usr/bin/env python3
"""Craigslist: nothing on a post is machine-readable, and the seller is anonymous.

Every field here needs a human or an agent page read. `NEEDS_PAGE_READ` says
where to look.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "craigslist"

# Craigslist runs no bidding and no Buy It Now, so branches (1) and (2) of the
# shared rule can never match here and only the fixed-ask branch applies. Stated
# outright rather than inherited: 54 of 74 stored Craigslist rows had been
# written as `ask_price`, 5 as `current_price` and 4 as `unknown` off the same
# post shape, because the shared prose named no branch for a post that has only
# an asking price.
PRICE_BASIS_RULE = (
    "Every Craigslist post is a fixed ask: the platform runs no bidding of any "
    "kind and publishes no separate Buy It Now, so branch (3) of the shared "
    "rule is the ONLY branch that ever matches. Record the post's asking price "
    "in `static_price` and set price_basis: static_price. Leave current_price "
    "and buy_now_price null. A price the post states as 'OBO' is still the "
    "ask; record the stated number, never a discount you expect to negotiate."
    " " + listing.PRICE_BASIS_RULE)

NEEDS_PAGE_READ = {
    "available_fulfillment": "post body + attrgroup; local pickup unless the "
                             "post states shipping/delivery",
    "item_location": "post `data-latitude`/`data-longitude` plus the title's "
                     "place slug",
    "seller_id": "Craigslist publishes no seller identity. A post carries no "
                 "account name, no profile and no stable poster key -- contact "
                 "runs through an anonymised email relay, by design. Record "
                 "null. This null is a fact, not a gap.",
    "seller_name": "Anonymous posts; see `seller_id`. Record null.",
}


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "a Craigslist post is a classified advert at a stated price; the "
    "platform runs no bidding of any kind")


# This source publishes no destination rate at all, so an explicit unquoted
# answer with a reason IS the answer. See listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "a Craigslist post is collection in person at a stated price; the "
    "platform carries no shipping surface at all, so there is no rate to "
    "read and none to invent")
