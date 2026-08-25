#!/usr/bin/env python3
"""OfferUp: the answers sit in the item page's Apollo state, with no read yet.

Every field here needs a human or an agent page read. `NEEDS_PAGE_READ` says
where to look.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "offerup"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "shipping_estimate": "item page `fulfillmentDetails.shippingEnabled` "
                         "under `props.pageProps.initialApolloState`. A "
                         "shipping-enabled listing shows the rate beside the "
                         "buy button; a pickup-only one has no rate at all",
    "available_fulfillment": "item page fulfillmentDetails.localPickupEnabled "
                             "/ .shippingEnabled",
    "item_location": "item page locationDetails.locationName under "
                     "props.pageProps.initialApolloState.ROOT_QUERY",
    "seller_id": "item page `ownerId` under "
                 "`props.pageProps.initialApolloState`. The GraphQL query in "
                 "`offerup_cli/client.py` already asks for it, so it is in "
                 "the payload the crawl reads. No reader is written for this "
                 "source yet, so it is captured by hand for now.",
    "seller_name": "item page `owner.profile.name`, already in the same "
                   "GraphQL query as `ownerId`. "
                   "`owner.profile.isBusinessAccount` distinguishes a shop "
                   "from a private seller and is worth a learning note.",
}


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "OfferUp lists at a fixed price with an optional offer; it runs no "
    "auctions")
