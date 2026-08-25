#!/usr/bin/env python3
"""AuctionZip: `auctionzip get <ref>` -> the house's address and name.

Removal is always at the house, so the house address IS the pickup point.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "auctionzip"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "available_fulfillment": "`auctionzip get <ref>` -> shipping_terms free text "
                             "(e.g. 'IF ITEMS NEED TO BE SHIPPED...' vs 'NO "
                             "SHIPPING')",
    "seller_id": "AuctionZip publishes no stable house id on the lot payload. "
                 "`auctionzip get <ref>` returns `auction_house` as a name only. "
                 "Record null and read the name into `seller_name`.",
}


def fetch(deal):
    lot = listing.lot_id(deal)
    return listing.cached((NAMESPACE, lot),
                          lambda: listing.cli(["auctionzip", "get", lot]))


def item_location(deal):
    """`auctionzip get` -> `location`, the auction house's full address."""
    payload = fetch(deal)
    value = listing.dig(payload, "location")
    if value is listing.MISSING:
        raise listing.Undetermined("the page states no location where "
                                   "`location` expects one")
    text = listing.tidy(str(value))
    listing.require_zip(text)
    return text, "location -> %r" % text


def auction_end_date(deal):
    """`auctionzip get <ref>` -> `close_time`, normalised to UTC ISO.

    AuctionZip prints "August 9, 2026 8:00 AM EDT". Stored verbatim, that never
    matches the `YYYY-MM-DD` prefix `invalidate.sweep.parse_past` looks for, so
    the lot could never expire -- two rows sat in exactly that state on
    2026-08-06. `listing.iso_end_date` is what makes the stored value
    answerable.

    `close_time: null` is real. AuctionZip carries two kinds of ref: a TIMED
    lot, which has `auction_type`, `lot_number` and a close time, and a plain
    sale listing, which has none of the three (ref 4155222, checked live
    2026-08-06: every one of them null at `status: open`). A sale listing has
    no close time to read, so this raises and the row lands in `undetermined`
    rather than storing a sentinel that claims one exists.
    """
    payload = fetch(deal)
    value = listing.dig(payload, "close_time")
    if value is listing.MISSING or value is None:
        raise listing.Undetermined(
            "close_time is %r (status=%r, auction_type=%r) -- a ref with no "
            "auction_type is a sale listing, not a timed lot, and publishes no "
            "close time"
            % (None if value is listing.MISSING else value,
               listing.dig(payload, "status"),
               listing.dig(payload, "auction_type")))
    return listing.iso_end_date(value), "close_time=%r" % value


def seller_name(deal):
    """`auctionzip get <ref>` -> `auction_house`. The house is the seller."""
    payload = fetch(deal)
    value = listing.dig(payload, "auction_house")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no auction_house")
    return value, "auction_house=%r" % value


# This source publishes no destination rate at all, so an explicit unquoted
# answer with a reason IS the answer. See listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "AuctionZip publishes shipping_terms as free text ('IF ITEMS NEED TO BE "
    "SHIPPED...' / 'NO SHIPPING') and no rate. The house invoices freight "
    "after the sale. Estimate it from the house address; never record 0.0")
