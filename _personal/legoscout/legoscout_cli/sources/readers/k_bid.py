#!/usr/bin/env python3
"""K-BID: the lot page carries the shipping glyph, the auction page the rest.

K-BID states removal and the seller at the AUCTION level, not the lot.
`listing_key` is `k-bid|<auction>-<lot>`, so the auction id is in hand.
"""
from __future__ import annotations

from .. import listing

NAMESPACE = "k-bid"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ: dict = {}

_LIVE_LOT = r"(?i)(Pay Online|Auction Closing|lot)"
_TRUCK = r'(<i class="bi-truck"[^>]*title="Shipping Available")'
_ADDRESS = r"Auction Location:\s*([^<]+)"
_AFFILIATE_ID = r'id="affiliate_name".*?/affiliate-profile/detail/(\d+)'
_AFFILIATE_NAME = r'id="affiliate_name".*?<a[^>]*>(.*?)</a>'
# The LOT's own scheduled close, not the auction's. K-BID closes lots in a
# staggered sequence, so the auction-level "Auction Closing:" block under
# `lot_detail_tab_details_closing` is minutes to hours earlier than the lot.
_SCHEDULED_CLOSE = (r'<span id="lot_scheduled_close"[^>]*'
                    r'title="Scheduled Close Time"[^>]*>([^<]+)</span>')


def lot_page(deal):
    url = listing.direct_url(deal)
    return listing.cached((NAMESPACE, "lot", url), lambda: listing.http(url))


def auction_page(deal):
    url = "https://www.k-bid.com/auction/%s" % listing.auction_id(deal)
    return listing.cached((NAMESPACE, "auction", url), lambda: listing.http(url))


def available_fulfillment(deal):
    """Lot page per-lot `bi-truck` 'Shipping Available' glyph.

    Auction 65418 lot 227A has it; 65644 lot 348R does not -- and the parent
    auction's general shipping language does not decide.
    """
    page = lot_page(deal)
    if listing.group(page, _LIVE_LOT) is listing.MISSING:
        raise listing.Undetermined(
            "the payload carries no lot page markers (absent) -- upgrade the "
            "source reader rather than reading its absence as an answer")

    options = ["local_pickup"]
    evidence = ["local_pickup: always (collection at the seller/house)"]
    ships = listing.group(page, _TRUCK) is not listing.MISSING
    if ships:
        options.append("shipping")
    evidence.append("shipping: bi-truck 'Shipping Available' glyph=%s" % ships)
    return options, "; ".join(evidence)


def item_location(deal):
    """AUCTION page -> the 'Auction Location:' line."""
    text = listing.group(auction_page(deal), _ADDRESS)
    if text is listing.MISSING:
        raise listing.Undetermined(
            "the auction page states no 'Auction Location:' line")
    text = listing.tidy(listing.flatten(text))
    listing.require_city_state_zip(text)
    return text, "Auction Location -> %r" % text


def auction_end_date(deal):
    """LOT page -> `<span id="lot_scheduled_close">`, normalised to UTC ISO.

    K-BID prints "Mon, Aug 3, 2026 9:47pm CDT". Stored verbatim that never
    matches the `YYYY-MM-DD` prefix `invalidate.sweep.parse_past` looks for, so
    the lot could never expire. `listing.iso_end_date` normalises it.

    The lot's own span wins over the auction's "Auction Closing:" block: K-BID
    staggers lot closes, so the auction figure is early for every lot but the
    first.
    """
    text = listing.group(lot_page(deal), _SCHEDULED_CLOSE)
    if text is listing.MISSING:
        raise listing.Undetermined(
            "the lot page carries no lot_scheduled_close span")
    text = listing.tidy(listing.flatten(text))
    return listing.iso_end_date(text), "lot_scheduled_close -> %r" % text


def seller_id(deal):
    """AUCTION page -> the affiliate-profile id behind the `id="affiliate_name"`
    heading. The affiliate is the K-BID seller of record."""
    value = listing.group(auction_page(deal), _AFFILIATE_ID)
    if value is listing.MISSING:
        raise listing.Undetermined(
            "the auction page carries no affiliate-profile id under "
            "id=\"affiliate_name\"")
    return value.strip(), "affiliate-profile/detail/%s" % value.strip()


def seller_name(deal):
    """AUCTION page -> the anchor text under `id="affiliate_name"`.

    The affiliate is the K-BID seller of record; the underlying consignor is
    never published.
    """
    value = listing.group(auction_page(deal), _AFFILIATE_NAME)
    if value is listing.MISSING:
        raise listing.Undetermined(
            "the auction page carries no affiliate name under id=\"affiliate_name\"")
    value = listing.flatten(value).strip()
    return value, "affiliate_name=%r" % value


# This source publishes no destination rate at all, so an explicit unquoted
# answer with a reason IS the answer. See listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "K-BID publishes no destination rate. The lot page carries a bi-truck "
    "'Shipping Available' glyph and nothing more; the affiliate invoices "
    "freight after the sale. The deal-record schema names K-BID as one of "
    "the three sources whose shipping_estimate is legitimately absent")
