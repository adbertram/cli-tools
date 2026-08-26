#!/usr/bin/env python3
"""Shop The Salvation Army: `search get` for the panel, the listing page for the seller.

Two fetches, not one. The CLI exposes the shipping panel and the auction dates;
it exposes no seller field at all, so the store, its id and the pickup point all
come off one unauthenticated read of `/Listing/Details/<id>`.
"""
from __future__ import annotations

import re

from .. import listing
from ...ledger import shipping as se

NAMESPACE = "shopsalvationarmy"

# Same default, with one addition: if auction_status is ended and
# buy_it_now_price is non-null, the BIN may still be live -- verify it before
# using price_basis: buy_now. If ended with buy_it_now_price null, the listing is
# unavailable.
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE + (
    " Shop The Salvation Army addition: an ended auction with a non-null "
    "buy_it_now_price may still sell at the BIN -- verify before using it. "
    "Ended with a null BIN means the listing is unavailable.")

NEEDS_PAGE_READ: dict = {}

# 'Seller - Phoenix_430' then 'PHOENIX, AZ US' -- the store name and the pickup
# point come off one string, so the two answers cost one read.
_SELLER_BLOCK = re.compile(r"Seller - (\S+)\s+(.+?)\s+US\b", re.S)
_SELLER_ID = re.compile(r"Seller - (\S+?)_(\d+)\s", re.S)
_PANEL = "detail__sellerInfo"


def fetch(deal):
    lot = listing.lot_id(deal)
    return listing.cached((NAMESPACE, lot),
                          lambda: listing.cli(["shopsalvationarmy", "search",
                                               "get", lot]))


def page(deal):
    url = listing.direct_url(deal)
    return listing.cached((NAMESPACE, "page", url), lambda: listing.http(url))


def _seller_panel(deal):
    """The flattened `detail__sellerInfo` block, the last one on the page."""
    return listing.flatten(listing.window(page(deal), _PANEL, 1200))


def available_fulfillment(deal):
    """`search get` -> `shipping_options`, the listing's own Shipping Options panel.

    Read ONLY that object. `shipping_cost` / `shipping_params` /
    `shipping_quote_status` describe the live carrier quote, and a quote that
    fails means the rate is unknown, not that the seller will not ship. Listing
    562200044 proves it -- 'Local Pick Up: $0.00' AND 'Standard Shipping:
    $46.00', with no calculator to quote.
    """
    payload = fetch(deal)
    listing.require(payload, "shipping_options")

    options, evidence = [], []
    pickup = ["shipping_options.local_pickup"] if listing.truthy(
        payload, "shipping_options.local_pickup") else []
    if pickup:
        options.append("local_pickup")
    evidence.append("local_pickup: any_of['shipping_options.local_pickup']=%s"
                    % (pickup or None))

    ships = [p for p in ("shipping_options.flat_rate",
                         "shipping_options.carrier_calculator")
             if listing.truthy(payload, p)]
    if ships:
        options.append("shipping")
    evidence.append("shipping: any_of['shipping_options.flat_rate', "
                    "'shipping_options.carrier_calculator']=%s" % (ships or None))

    if not options:
        raise listing.Undetermined(
            "the listing offers neither pickup nor shipping, which no live "
            "listing does -- re-read the page")
    return options, "; ".join(evidence)


def item_location(deal):
    """Listing page `detail__sellerInfo` -> the store's town line.

    The seller IS the pickup point. Used rather than
    `shipping_params.from_postal_code`, which is nulled whenever the live quote
    fails and is a ship-from warehouse, not a collection counter.
    """
    text = _seller_panel(deal)
    hit = _SELLER_BLOCK.search(text)
    if not hit:
        raise listing.Undetermined(
            "the page states no 'Seller - <store> <town> US' line in the "
            "detail__sellerInfo block")
    return listing.tidy(hit.group(2)), "detail__sellerInfo -> %r" % hit.group(2)


def auction_end_date(deal):
    """`search get` -> `auction_end_date`.

    Null on a live auction is real: 562200044 is `auction_status: active` with
    no published end date.
    """
    payload = fetch(deal)
    value = listing.dig(payload, "auction_end_date")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no auction_end_date")
    return value, "auction_end_date=%r" % value


def shipping_estimate(deal):
    """`search get` -> `shipping_quote_status`, then the cost, handling and service.

    The status is a WORD (`quoted` / `unavailable` / `destination_required` /
    `not_applicable`), so it must be compared, never read for truthiness.
    """
    payload = fetch(deal)
    status = listing.dig(payload, "shipping_quote_status")
    if status != "quoted":
        return (se.unquoted("shipping_quote_status=%r"
                            % (None if status is listing.MISSING else status)),
                "source reports no live quote")

    shipping = listing.dig(payload, "shipping_cost")
    if shipping is listing.MISSING or not isinstance(shipping, (int, float)):
        raise listing.Undetermined(
            "no numeric shipping price at shipping_cost (got %r) -- a missing "
            "rate is not a free one" % (shipping,))
    handling = listing.dig(payload, "handling_cost")
    service = listing.dig(payload, "shipping_service")
    estimate = se.quoted(
        shipping_price=shipping,
        handling_price=None if handling is listing.MISSING else handling,
        service=None if service is listing.MISSING else service)
    return estimate, "shipping=%s handling=%s service=%s" % (shipping, handling, service)


def seller_id(deal):
    """Listing page `detail__sellerInfo` -> the numeric suffix of
    'Seller - <Store>_<num>' (Phoenix_430 -> 430)."""
    text = _seller_panel(deal)
    hit = _SELLER_ID.search(text)
    if not hit:
        raise listing.Undetermined(
            "the detail__sellerInfo block states no 'Seller - <store>_<id>' key")
    return hit.group(2), "detail__sellerInfo -> %r" % hit.group(2)


def seller_name(deal):
    """Listing page `detail__sellerInfo` -> group 1 of the SAME line
    `item_location` reads group 2 of. The store IS the pickup point."""
    text = _seller_panel(deal)
    hit = _SELLER_BLOCK.search(text)
    if not hit:
        raise listing.Undetermined(
            "the page states no 'Seller - <store> <town> US' line in the "
            "detail__sellerInfo block")
    return listing.tidy(hit.group(1)), "detail__sellerInfo -> %r" % hit.group(1)
