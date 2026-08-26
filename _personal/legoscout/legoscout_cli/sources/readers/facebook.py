#!/usr/bin/env python3
"""Facebook Marketplace: `marketplace get` -> its own per-listing delivery model."""
from __future__ import annotations

from .. import listing

NAMESPACE = "facebook"

# Marketplace runs no bidding and no Buy It Now, so branches (1) and (2) of the
# shared rule can never match here and only the fixed-ask branch applies. Stated
# outright rather than inherited: the shared prose named no branch for a listing
# that has only an asking price, so every run invented its own answer and the
# ledger accumulated four bases for one identical row shape.
#
# This tuple is that same fact in the form a checker can read, because prose
# alone did not hold it. The rule text below has said `static_price` since
# 2026-08-06 and the drift continued anyway -- of 122 stored rows, 36 crawled
# 2026-07-30 said `current_price`, 19 crawled 2026-08-04 said `buy_now` while
# duplicating the amount into `static_price` AND `buy_now_price`, and only the
# rest said `static_price`. All 55 were repaired on 2026-08-18. `validate.check`
# reads this tuple and now rejects any other basis on this source, so the next
# drift fails at the write instead of surfacing as an ungroupable column six
# runs later. `unknown` stays legal: it means the listing was never read, which
# is a gap rather than a contradiction.
PRICE_BASES = ("static_price",)

PRICE_BASIS_RULE = (
    "Every Facebook Marketplace listing is a fixed ask: the platform runs no "
    "auctions and publishes no separate Buy It Now, so branch (3) of the "
    "shared rule is the ONLY branch that ever matches. Record the listing's "
    "asking price in `static_price` and set price_basis: static_price. Leave "
    "current_price and buy_now_price null. The buyer-side Offer flow is a "
    "message to the seller, not a published price, so it never changes the "
    "basis and its amount is never stored." + " " + listing.PRICE_BASIS_RULE)

NEEDS_PAGE_READ = {}

# Facebook's own tokens. An unrecognized one raises rather than being guessed.
_TOKEN_MAP = {
    "DOOR_DROPOFF": "local_pickup",
    "DOOR_PICKUP": "local_pickup",
    "IN_PERSON": "local_pickup",
    "PUBLIC_MEETUP": "local_pickup",
}
_TOKEN_PREFIX_MAP = {"SHIPPING": "shipping"}


def fetch(deal):
    lot = listing.lot_id(deal)
    return listing.cached((NAMESPACE, lot),
                          lambda: listing.cli(["facebook", "marketplace", "get", lot]))


def available_fulfillment(deal):
    """`marketplace get` -> `delivery_types`.

    NEVER read the description's meet-up prose or a search tile's location slot:
    Facebook renders 'Ships to you' there based on DISTANCE, not fulfillment.
    """
    payload = fetch(deal)
    listing.require(payload, "delivery_types")
    tokens = listing.dig(payload, "delivery_types")
    if tokens is listing.MISSING or not tokens:
        raise listing.Undetermined("the payload carries no delivery_types")

    for token in tokens:
        if token in _TOKEN_MAP:
            continue
        if any(token.startswith(p) for p in _TOKEN_PREFIX_MAP):
            continue
        raise listing.Undetermined(
            "unrecognized delivery_types value %r -- classify it in this module "
            "before guessing what it means" % token)

    options = []
    for option in ("local_pickup", "shipping"):
        if any(_TOKEN_MAP.get(t) == option for t in tokens) or \
                any(option == mapped for prefix, mapped in _TOKEN_PREFIX_MAP.items()
                    for t in tokens if t.startswith(prefix)):
            options.append(option)

    if not options:
        raise listing.Undetermined(
            "the listing offers neither pickup nor shipping, which no live "
            "listing does -- re-read the page")
    return options, "delivery_types=%s" % "+".join(tokens)


def item_location(deal):
    """`marketplace get` -> `location`, Facebook's own `location_text`.

    Facebook blurs a seller's position on purpose: the page prints a city and
    state under a "Location is approximate" caption and never a ZIP, so this
    answers `require_city_state`, not `require_city_state_zip`, and `origin_zip`
    stays null for this source by construction.

    The old note here claimed `get` "often returns location: null" and told a
    crawler to carry the value off the `list` row by hand. That was the
    detail-page gap recorded on 2026-07-24; it is closed. On 2026-08-18 eight
    `get` calls returned a location on all eight -- Evansville IN, Henderson KY,
    Newburgh IN -- each matching its own `list` row exactly. A null now means
    this listing published none, which is a raise, not a hand-carry.
    """
    payload = fetch(deal)
    listing.require(payload, "location")
    value = listing.dig(payload, "location")
    if value is listing.MISSING or not value:
        raise listing.Undetermined("the payload carries no location")
    text = listing.tidy(str(value))
    listing.require_city_state(text)
    return text, "location=%r" % text


def seller_id(deal):
    """`marketplace get` -> `seller_id`, the seller's numeric Facebook profile id,
    read from Facebook's own `marketplace_listing_seller` node."""
    payload = fetch(deal)
    value = listing.dig(payload, "seller_id")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no seller_id")
    return value, "seller_id=%r" % value


def seller_name(deal):
    """`marketplace get` -> `seller_name`, the display name off the same node.

    A person can change a display name, so join on `seller_id`. Never read a
    name out of the description prose.
    """
    payload = fetch(deal)
    value = listing.dig(payload, "seller_name")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no seller_name")
    return value, "seller_name=%r" % value


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "Facebook Marketplace lists at a fixed price with an optional offer "
    "flow; it runs no auctions")


# This source publishes no destination rate at all, so an explicit unquoted
# answer with a reason IS the answer. See listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "Facebook Marketplace publishes no destination rate on a listing. The "
    "deal-record schema names Facebook as one of the three sources whose "
    "shipping_estimate is legitimately absent")
