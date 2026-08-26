#!/usr/bin/env python3
"""eBay: one `ebay listings get <item>` answers fulfillment and the seller."""
from __future__ import annotations

from .. import listing

NAMESPACE = "ebay"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "auction_end_date": "`ebay listings get` returns `time_left` as a "
                        "RELATIVE string ('Ended', '3d 5h') and no absolute "
                        "timestamp (checked live 2026-08-06). Read the item "
                        "page's 'Ends in' row, which renders the absolute "
                        "close date, or convert `time_left` against the fetch "
                        "time and record that it is derived",
    "shipping_estimate": "`ebay listings get` returns `shipping_price` as a "
                         "bare number with no service name, and it is ABSENT "
                         "both when the listing is pickup-only and when eBay "
                         "computes the rate at checkout "
                         "('seller-calculated'). Those two are different "
                         "answers, so read the item page's shipping row "
                         "rather than the number alone -- ebay|336691199794 "
                         "recorded $0.00 for a rate eBay never quoted",
    "item_location": "item page row .ux-labels-values--shipping ('Located in: "
                     "Owensboro, Kentucky, United States'); `ebay listings "
                     "get` exposes neither label row",
}


def fetch(deal):
    lot = listing.lot_id(deal)
    return listing.cached((NAMESPACE, lot),
                          lambda: listing.cli(["ebay", "listings", "get", lot]))


def available_fulfillment(deal):
    """`listings get` -> `ships` / `local_pickup`, eBay's own fulfillment label rows.

    NEVER read `shipping_price`: it is absent both when the listing is pickup
    only and when the rate did not parse -- the exact ambiguity these two flags
    end.
    """
    payload = fetch(deal)
    listing.require(payload, "ships", "local_pickup")

    options, evidence = [], []
    pickup = listing.truthy(payload, "local_pickup")
    if pickup:
        options.append("local_pickup")
    evidence.append("local_pickup: any_of['local_pickup']=%s"
                    % (["local_pickup"] if pickup else None))

    ships = listing.truthy(payload, "ships")
    if ships:
        options.append("shipping")
    evidence.append("shipping: any_of['ships']=%s" % (["ships"] if ships else None))

    if not options:
        raise listing.Undetermined(
            "the listing offers neither pickup nor shipping, which no live "
            "listing does -- re-read the page")
    return options, "; ".join(evidence)


def seller_id(deal):
    """`listings get` -> `seller`. On eBay the username IS the stable key, so
    `seller_id` and `seller_name` hold the same value."""
    payload = fetch(deal)
    value = listing.dig(payload, "seller")
    if value is listing.MISSING:
        raise listing.Undetermined("the payload carries no seller")
    return value, "seller=%r" % value


def seller_name(deal):
    """`listings get` -> `seller`, the same username as `seller_id`.

    eBay renders no separate display name on the item page; the store name,
    where one exists, is not the account key and is not read here.
    """
    return seller_id(deal)
