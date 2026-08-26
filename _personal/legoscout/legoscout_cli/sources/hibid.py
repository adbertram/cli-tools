#!/usr/bin/env python3
"""Read a HiBid lot's live bidding state. The single reader of HiBid lot status.

HiBid publishes a lot the moment an auction house posts its catalog, which can
be weeks before bidding opens. Those pages look identical to a live lot -- same
layout, a price, a countdown -- so a search index will happily hand back lots
nobody can bid on yet. Adam does not want them: a lot he cannot act on is not a
deal.

The canonical lot page embeds the whole Apollo cache in `script#hibid-state`.
What matters is the bidding WINDOW -- `bidOpenDateTime` / `bidCloseDateTime` --
which goes into the ledger as `auction_start_date` / `auction_end_date`. Readers
compare those to the clock. Nothing stores a live/not-live flag: it would be
wrong the moment bidding opens.

This module has no command of its own. Reach it through a reader:

    legoscout deals read 'hibid|314234951' item_location

or import it from the tool's own interpreter and call `lot_state(314234951)`.
"""
import argparse
import json
import re
import sys
import time
import urllib.request

STATE_RE = re.compile(r'id="hibid-state"[^>]*>(.*?)</script>', re.S)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")


def canonical_url(lot):
    """Subdomain lot pages (`*.hibid.com/lot/<id>`) are JS-only shells; only
    the canonical host server-renders the state blob."""
    text = str(lot).strip()
    if text.isdigit():
        return "https://hibid.com/lot/%s" % text, text
    url = re.sub(r"^https?://[a-z0-9-]+\.hibid\.com/lot/",
                 "https://hibid.com/lot/", text)
    m = re.search(r"/lot/(\d+)", url)
    if not m:
        raise ValueError("not a HiBid lot URL or id: %r" % text)
    return url, m.group(1)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse(html, lot_id):
    m = STATE_RE.search(html)
    if not m:
        raise ValueError("no hibid-state blob -- page was a JS shell or blocked")
    apollo = json.loads(m.group(1)).get("apollo.state")
    if not apollo:
        raise ValueError("hibid-state carried no apollo.state")

    lot = apollo.get("Lot:%s" % lot_id)
    if lot is None:
        raise ValueError("Lot:%s absent from the page state" % lot_id)
    ls = lot.get("lotState") or {}

    # Follow the lot's OWN auction ref. Picking the first Auction: key in the
    # cache reads a different sale's bid window on any page that embeds more
    # than one, which silently mislabels the lot.
    aref = (lot.get("auction") or {}).get("__ref")
    auction = apollo.get(aref) or {}
    astate = auction.get("auctionState") or {}
    # Apollo normalises nested entities to {"__ref": "Auctioneer:85246"}; the
    # auction house's city/state is what decides pickup feasibility, so follow it.
    house = auction.get("auctioneer") or {}
    if "__ref" in house:
        house = apollo.get(house["__ref"]) or {}

    return {
        "lot_id": lot_id,
        # The bidding window is the whole answer. Readers compare it to the
        # clock; nothing stores a live/not-live flag, which would be stale the
        # moment bidding opens.
        "auction_start_date": auction.get("bidOpenDateTime"),
        "auction_end_date": auction.get("bidCloseDateTime"),
        "auction_status": astate.get("auctionStatus"),
        "is_closed": bool(ls.get("isClosed")),
        "is_archived": bool(ls.get("isArchived")),
        "high_bid": ls.get("highBid"),
        "bid_count": ls.get("bidCount"),
        "min_bid": ls.get("minBid"),
        "buy_now": ls.get("buyNow"),
        "currency": auction.get("currencyAbbreviation"),
        # PER-LOT, and it is the one that counts. The auction-level
        # `shippingType` is SHIPPING_OFFERED_ALL / _SOME / _NONE, and on a
        # _SOME sale half the catalogue is pickup-only -- lot 313898136's house
        # ships, the lot next to it may not. `shippingOffered` is the lot's own
        # answer and feeds `available_fulfillment` directly; pickup is always
        # available at the house, so False means pickup-only, not "no way to
        # get it".
        "shipping_offered": bool(lot.get("shippingOffered")),
        "shipping_type": (auction.get("auctionOptions") or {}).get("shippingType"),
        "auction_notice": auction.get("auctionNotice"),
        "house": house.get("name"),
        "city": house.get("city"),
        "state": house.get("state"),
        "postal_code": house.get("postalCode"),
    }


def lot_state(lot, attempts=5):
    """Read one lot's state, retrying a flaky render.

    HiBid intermittently serves a page whose state blob is missing the lot it
    was asked for -- lot 313898132 failed then succeeded twice in a row on
    2026-07-26. That is a bad read of a good page, so re-read it; only a lot
    that never resolves raises. Nothing here substitutes a value.

    The rate is what makes it flaky. At 10 concurrent readers on 2026-08-06, 4
    of 100 lots exhausted the old 3 attempts at 0s/2s/4s, and EVERY one of them
    succeeded when re-read alone afterwards. So the backoff doubles rather than
    stepping, and there are five attempts: 0s, 2s, 4s, 8s, 16s.
    """
    url, lot_id = canonical_url(lot)
    last = None
    for attempt in range(attempts):
        if attempt:
            time.sleep(2.0 * (2 ** (attempt - 1)))
        try:
            out = parse(fetch(url), lot_id)
        except ValueError as exc:
            last = exc
            continue
        out["url"] = url
        out["read_attempts"] = attempt + 1
        return out
    raise ValueError(
        "%s after %d attempts over %.0f seconds. HiBid rate-limits the lot "
        "page under concurrency; re-read this lot on its own before treating "
        "it as gone."
        % (last, attempts, sum(2.0 * (2 ** i) for i in range(attempts - 1))))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lot", help="lot id or hibid.com lot URL")
    a = ap.parse_args()
    try:
        out = lot_state(a.lot)
    except (ValueError, OSError) as exc:
        sys.exit("hibid_lot_state: %s" % exc)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
