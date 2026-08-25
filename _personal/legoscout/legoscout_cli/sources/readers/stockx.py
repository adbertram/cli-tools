#!/usr/bin/env python3
"""StockX: an anonymous ask/bid order book that ships from its own centre.

There is no seller, no pickup and no published origin. A product with no ask is
not buyable, and that raises rather than defaulting to shipping.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "stockx"

# StockX runs an ask/bid order book with no auction and no seller-set BIN, so
# `listing_type` is `fixed` and both auction dates are null.
PRICE_BASIS_RULE = (
    "StockX runs an ask/bid order book with no auction and no seller-set BIN, "
    "so `listing_type` is `fixed` and both auction dates are null. The only "
    "number Adam can pay is the lowest standard Ask, "
    "`market.state.askServiceLevels.standard.lowest.amount` (same value as "
    "`market.state.lowestAsk.amount`) -> record it as `buy_now_price` with "
    "`price_basis: buy_now`. `market.state.highestBid.amount` is another BUYER's "
    "open Offer, not a price Adam can pay; never record it as `current_price`. "
    "`standard.processingFee.amount` is the ask PLUS the buyer Processing Fee: "
    "use it for the fee, never as the price.")

NEEDS_PAGE_READ = {
    "item_location": "StockX publishes no seller location: the seller ships to a "
                     "StockX verification centre and StockX ships to the buyer, "
                     "so neither the product page nor the CLI exposes an origin "
                     "city, state or ZIP. Record `item_location: \"unknown\"` "
                     "and `origin_zip: null`, and never invent one. Fulfillment "
                     "is shipping-only, so `pickup_area.resolve()` never applies "
                     "here.",
    "seller_id": "Anonymous order book: the buyer transacts with StockX, not a "
                 "seller, and no ask is attributed to a person or a shop. That "
                 "null is a fact, not a gap.",
    "seller_name": "See `seller_id`. Record null.",
    "shipping_estimate": "StockX shows the buyer shipping fee only at checkout "
                         "and states it is not a fixed amount: it varies with "
                         "item price, size, type, the carrier rate at purchase "
                         "time, and the destination "
                         "(https://stockx.com/help/articles/"
                         "how-much-does-shipping-cost-for-buyers). The read-only "
                         "CLI never opens a checkout and StockX publishes no "
                         "origin, so there is nothing to price from. Record the "
                         "answer through `shipping_estimate.unquoted(<that "
                         "reason>)` and treat every StockX landed cost as a floor.",
}

_ASK = "market.state.lowestAsk.amount"


def fetch(deal):
    lot = listing.lot_id(deal)
    return listing.cached(
        (NAMESPACE, lot),
        lambda: listing.cli(["stockx", "products", "market", lot]))


def available_fulfillment(deal):
    """`stockx products market <url_key>` -> `market.state.lowestAsk`.

    StockX ships every order from its own verification centre and exposes no
    seller-meetup pickup, so there is no `local_pickup` rule. The Pickup choice
    at checkout routes an Xpress Ship order to a carrier point, which is a
    delivery option on a shipped order.
    """
    payload = fetch(deal)
    listing.require(payload, _ASK)
    if not listing.truthy(payload, _ASK):
        raise listing.Undetermined(
            "the listing offers neither pickup nor shipping, which no live "
            "listing does -- re-read the page")
    return ["shipping"], "shipping: any_of[%r]=[%r]" % (_ASK, _ASK)


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "StockX is a standing order book. An Offer rests until it matches an "
    "Ask, is cancelled, or expires; the registry records that there is no "
    "closing time, so this is not an auction")
