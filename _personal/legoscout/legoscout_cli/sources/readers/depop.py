#!/usr/bin/env python3
"""Depop: no per-listing endpoint, so the listing is found among search results.

Matching on the id is what stops the old reader's failure mode -- returning a
NEIGHBOUR's shipping method when the listing itself has sold.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "depop"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "item_location": "the search payload carries no location object at all. "
                     "Depop ships only, so no pickup point exists to resolve. "
                     "Record `item_location` as the string `unknown` and "
                     "`origin_zip` as null, and never invent one.",
    "shipping_estimate": "the search row's `price_breakdown.shipping` is "
                         "Depop's own destination rate. It is captured at "
                         "CRAWL time and is not re-readable per listing "
                         "afterwards, so refresh it by re-crawling rather "
                         "than by a per-row read.",
    "seller_id": "the Depop username, which prefixes the product `slug` "
                 "('kj_sells_ituff-lego-marvel-infinity-saga-bro-7120'). "
                 "UNVERIFIED: a hyphen split was not provable on 2026-08-05 "
                 "because `depop.com/<user>/` answers Cloudflare 403 to curl, "
                 "so a username containing a hyphen would split wrong. Read "
                 "the username off the listing page instead, or record null "
                 "and say so in `evidence_summary`. Append a learning note "
                 "once a split rule is proven against a live profile.",
    "seller_name": "same as `seller_id`: Depop's username is both the key and "
                   "the display name. The search payload carries no `seller` "
                   "object at all (checked live 2026-08-05).",
}


def fetch(deal):
    """The one search row whose `id` is this listing's."""
    query = listing.title(deal)
    rows = listing.cached(
        (NAMESPACE, "search", query),
        lambda: listing.cli(["depop", "search", query, "--limit", "60"]))
    want = listing.lot_id(deal)
    for row in rows if isinstance(rows, list) else []:
        if str(listing.dig(row, "id")) == want:
            return row
    raise listing.Undetermined(
        "no row in the result matches id == %r -- the listing may have sold" % want)


def available_fulfillment(deal):
    """The matched row -> `shipping_method.shipping_id`.

    Checkout is label-based, so the row carries the parcel and the payer.
    """
    row = fetch(deal)
    listing.require(row, "shipping_method.shipping_id")
    if not listing.truthy(row, "shipping_method.shipping_id"):
        raise listing.Undetermined(
            "the listing offers neither pickup nor shipping, which no live "
            "listing does -- re-read the page")
    return (["shipping"],
            "shipping: any_of['shipping_method.shipping_id']="
            "['shipping_method.shipping_id']")


# `not-an-auction` is the schema's own answer for this field on a fixed-price
# row, and this source has no other kind. See listing.never_an_auction().
auction_end_date = listing.never_an_auction(
    "Depop sells at a fixed price with an optional Make offer; no listing "
    "has a closing time")
