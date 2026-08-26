#!/usr/bin/env python3
"""EstateSales.org: the answers are inlined in `window.pageData`, not in an endpoint.

Collection at the sale is always an option; `item.shipping` is a 0/1 flag on the
lot itself.

EVERY LOT HERE IS A TIMED AUCTION. The registry has said `auction_tier: always`
since this source was added, and the item blob proves it per lot: `bidding`, a
`start_date_time`/`item_close_date_time` pair and an IANA `timezone` are on all
of them. This module used to answer `auction_end_date` with
`listing.never_an_auction(...)`, which stamped the literal string
`not-an-auction` onto live bidding rows -- `estatesalesorg|125565727` was
`status_text="active"` and closing `2026-08-10 21:25:00 US/Central` while the
reader called it a fixed-price listing. A row that cannot state a close time
cannot expire, so `invalidate.sweep` never revisits it and it sits in the ledger
forever. `sources/reader_contract.py` now refuses that combination outright.
"""
from __future__ import annotations

import datetime
import zoneinfo

from .. import listing

NAMESPACE = "estatesalesorg"
PRICE_BASIS_RULE = listing.PRICE_BASIS_RULE

NEEDS_PAGE_READ = {
    "seller_name": "item page: the estate-sale company's name is rendered in the "
                   "listing header, but the page-data blob carries only the "
                   "numeric `sellerId` and no company-name key was found on it "
                   "(checked 2026-08-05). Read the header, or resolve the id "
                   "against the company profile page. Record null and say so in "
                   "`evidence_summary` until an extractor is verified against a "
                   "live page.",
}

_ITEM_BLOB = r'"item":\{'
_ADDRESS = r'class="location-address[^"]*"\s*>(.*?)</span>'
_SELLER_ID = r'"sellerId":(\d+)'


def fetch(deal):
    url = listing.direct_url(deal)
    return listing.cached((NAMESPACE, url), lambda: listing.http(url))


def available_fulfillment(deal):
    """Item page `window.pageData.item.shipping`, a 0/1 flag on the lot itself."""
    page = fetch(deal)
    flag = listing.dig(listing.json_after(page, _ITEM_BLOB), "shipping")
    if flag is listing.MISSING or flag is None:
        raise listing.Undetermined(
            "the payload carries no item.shipping (%s) -- upgrade the source "
            "reader rather than reading its absence as an answer"
            % ("absent" if flag is listing.MISSING else "null"))

    options = ["local_pickup"]
    evidence = ["local_pickup: always (collection at the seller/house)"]
    ships = bool(flag) and flag not in ("0", "false", "False")
    if ships:
        options.append("shipping")
    evidence.append("shipping: item.shipping=%r" % (flag,))
    return options, "; ".join(evidence)


def item_location(deal):
    """Item page `location-address` span, beside the map pin and the
    'Get directions' link."""
    text = listing.group(fetch(deal), _ADDRESS)
    if text is listing.MISSING:
        raise listing.Undetermined(
            "the page states no location where the location-address span "
            "expects one")
    text = listing.flatten(text).replace("Get directions", "").strip()
    hit = listing.PATTERNS["city_state_zip"].search(text)
    if not hit:
        raise listing.Undetermined(
            "the page states no location where the location-address span "
            "expects one")
    text = listing.tidy(text[:hit.end()])
    listing.require_city_state_zip(text)
    return text, "location-address -> %r" % text


def seller_id(deal):
    """Item page inline page-data blob -> `sellerId`."""
    value = listing.group(fetch(deal), _SELLER_ID)
    if value is listing.MISSING:
        raise listing.Undetermined("the page carries no sellerId in its page-data blob")
    return value.strip(), "sellerId=%r" % value.strip()


def _bidding_window(deal, field):
    """One end of the bidding window as `YYYY-MM-DDTHH:MM:SS-05:00`.

    The blob prints wall-clock time with no offset (`"2026-08-10 21:25:00"`) and
    names its zone separately (`"US/Central"`). Both parts are required: the
    naive half alone is four different instants across this site's lots, and the
    consignors are spread over US/Eastern, US/Central and US/Mountain. `zoneinfo`
    resolves the offset for that DATE, so a lot closing in November gets CST and
    one closing in August gets CDT without a table of abbreviations to maintain.

    Every branch raises rather than substituting a sentinel. `not-an-auction` is
    a lie on this source (`auction_tier: always`), and `unknown` on a lot that
    published its close time is a row the expiry sweep will keep re-reading.
    """
    item = listing.json_after(fetch(deal), _ITEM_BLOB)
    stamp = listing.dig(item, field)
    if stamp is listing.MISSING or stamp is None:
        raise listing.Undetermined(
            "the payload carries no item.%s (%s) -- every lot on this source is "
            "a timed auction, so a missing bidding window is a reader to "
            "upgrade, not a fixed-price listing"
            % (field, "absent" if stamp is listing.MISSING else "null"))
    name = listing.dig(item, "timezone")
    if name is listing.MISSING or name is None:
        raise listing.Undetermined(
            "item.%s is %r but the payload names no item.timezone -- storing a "
            "close time without its offset moves it by hours" % (field, stamp))
    try:
        zone = zoneinfo.ZoneInfo(str(name))
    except zoneinfo.ZoneInfoNotFoundError:
        raise listing.Undetermined(
            "item.timezone is %r, which is not a zone this machine knows -- add "
            "it rather than assuming an offset" % (name,)) from None
    try:
        local = datetime.datetime.strptime(str(stamp), "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise listing.Undetermined(
            "item.%s is %r, which is not the 'YYYY-MM-DD HH:MM:SS' this source "
            "publishes: %s" % (field, str(stamp)[:120], exc)) from None
    iso = local.replace(tzinfo=zone).isoformat()
    return iso, "item.%s=%r + item.timezone=%r -> %s" % (field, stamp, name, iso)


def auction_end_date(deal):
    """Item page `window.pageData.item.item_close_date_time`, read in
    `item.timezone`. When bidding closes on this lot."""
    return _bidding_window(deal, "item_close_date_time")


def auction_start_date(deal):
    """Item page `window.pageData.item.start_date_time`, read in
    `item.timezone`. When bidding opened on this lot."""
    return _bidding_window(deal, "start_date_time")


# The rate exists; it is just not published until after the hammer. See
# listing.never_quotes_shipping().
shipping_estimate = listing.never_quotes_shipping(
    "EstateSales.org quotes freight only on the post-auction invoice, so no "
    "destination rate is readable at bid time -- item.shipping is a 0/1 "
    "willing-to-ship flag, not a price")
