#!/usr/bin/env python3
"""HiBid: the lot's own `hibid-state` blob, read by `hibid_lot_state.lot_state`.

`Lot.shippingOffered` is PER LOT even when the sale is SHIPPING_OFFERED_SOME,
and the parser follows the lot's OWN auction ref, so a page embedding two sales
cannot hand back the neighbour's address.
"""
from __future__ import annotations

from .. import hibid as hibid_lot_state
from .. import listing

NAMESPACE = "hibid"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "seller_id": "HiBid publishes no stable public seller id. The house IS the "
                 "seller, and the lot's `hibid-state` blob carries only an "
                 "internal auctioneer ref, not an id a later run can join on. "
                 "Record null and read the house into `seller_name`.",
    "shipping_estimate": "HiBid houses never quote freight at bid time -- they "
                         "invoice it after the sale through Pak Mail, a UPS "
                         "Store or a local shipper. Estimate it from the "
                         "captured origin with `legoscout pricing shipping "
                         "--hibid-lot <id>`; never record 0.0.",
}


def fetch(deal):
    lot = listing.lot_id(deal)
    return listing.cached((NAMESPACE, lot),
                          lambda: hibid_lot_state.lot_state(lot))


def available_fulfillment(deal):
    """`lot_state` -> `shipping_offered`. Collection at the house is always an option."""
    payload = fetch(deal)
    listing.require(payload, "shipping_offered")

    options = ["local_pickup"]
    evidence = ["local_pickup: always (collection at the seller/house)"]
    ships = listing.truthy(payload, "shipping_offered")
    if ships:
        options.append("shipping")
    evidence.append("shipping: any_of['shipping_offered']=%s"
                    % (["shipping_offered"] if ships else None))
    return options, "; ".join(evidence)


def item_location(deal):
    """`lot_state` -> `city` / `state` / `postal_code`."""
    payload = fetch(deal)
    listing.require(payload, "city", "state")
    parts = {}
    for name, path in (("city", "city"), ("state", "state"), ("zip", "postal_code")):
        found = listing.dig(payload, path)
        parts[name] = "" if found is listing.MISSING else str(found).strip()
    text = listing.tidy("{city}, {state} {zip}".format(**parts))
    return text, "city/state/postal_code -> %r" % text


def auction_end_date(deal):
    """`lot_state` -> `auction_end_date`, already ISO on the blob.

    The lot's own `hibid-state` blob carries `auction_start_date`,
    `auction_end_date` and `is_closed` as ISO strings, so nothing here parses a
    printed date. The value is the SALE's close, which is what HiBid publishes;
    a per-lot soft close is decided at run time and never appears in the blob.
    """
    payload = fetch(deal)
    value = listing.dig(payload, "auction_end_date")
    if value is listing.MISSING or value is None:
        raise listing.Undetermined(
            "the lot state carries no auction_end_date (is_closed=%r)"
            % (listing.dig(payload, "is_closed"),))
    return value, "auction_end_date=%r" % value


def seller_name(deal):
    """`lot_state` -> `house`, the auction house's name.

    The house IS the seller on HiBid; individual consignors are never published.
    """
    payload = fetch(deal)
    value = listing.dig(payload, "house")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no house")
    return value, "house=%r" % value
