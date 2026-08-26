#!/usr/bin/env python3
"""EstateSales.NET: the item page states both halves of fulfillment outright."""
from __future__ import annotations

from .. import listing

NAMESPACE = "estatesales"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "auction_end_date": "the item page's inline blob carries the SALE window, "
                        "not a lot close: `dates[].utcStartDate` / "
                        "`utcEndDate` plus `isOver` and `showEndTime` "
                        "(checked live 2026-08-06 on "
                        "estatesales|4975902|226831907). A marketplace item "
                        "is priced by scheduled discount rather than bidding, "
                        "so the sale end is not an auction close -- record "
                        "`not-an-auction` for a marketplace item, and read "
                        "the lot close off the linked auction for an auction "
                        "sale",
    "shipping_estimate": "the item page publishes `allowsShipping` as a "
                         "boolean and no rate. Whether a company ships, and "
                         "at what price, is set per company and quoted on "
                         "request. Record an unquoted answer with that "
                         "reason; never record 0.0",
    "item_location": "item page inline blob cityName / stateCode / "
                     "postalCodeNumber",
    "seller_id": "EstateSales.NET publishes no seller id on the marketplace "
                 "item page. The inline schema.org blob names the "
                 "organisation and nothing else. Record null and read the "
                 "name into `seller_name`.",
}

_SHIPS = r'"allowsShipping":\s*(true|false)'
_PICKUP = r'"allowsLocalPickup":\s*(true|false)'
_SELLER = r'"seller":\{"@type":"Organization","name":"([^"]+)"\}'


def fetch(deal):
    url = listing.direct_url(deal)
    return listing.cached((NAMESPACE, url), lambda: listing.http(url))


def _flag(page, pattern, label):
    value = listing.group(page, pattern)
    if value is listing.MISSING:
        raise listing.Undetermined(
            "the payload carries no %s (absent) -- upgrade the source reader "
            "rather than reading its absence as an answer" % label)
    return value == "true"


def available_fulfillment(deal):
    """Item page inline `allowsShipping` / `allowsLocalPickup`."""
    page = fetch(deal)
    ships = _flag(page, _SHIPS, "allowsShipping")
    pickup = _flag(page, _PICKUP, "allowsLocalPickup")

    options, evidence = [], []
    if pickup:
        options.append("local_pickup")
    evidence.append("local_pickup: allowsLocalPickup=%s" % pickup)
    if ships:
        options.append("shipping")
    evidence.append("shipping: allowsShipping=%s" % ships)

    if not options:
        raise listing.Undetermined(
            "the listing offers neither pickup nor shipping, which no live "
            "listing does -- re-read the page")
    return options, "; ".join(evidence)


def seller_name(deal):
    """Item page inline schema.org Product blob -> `offers.seller.name`.

    The blob is unicode-escaped (`\\u002F` for a slash), but the organisation
    name itself is plain.
    """
    value = listing.group(fetch(deal), _SELLER)
    if value is listing.MISSING:
        raise listing.Undetermined(
            "the page carries no schema.org offers.seller.name blob")
    return value.strip(), "offers.seller.name=%r" % value.strip()
