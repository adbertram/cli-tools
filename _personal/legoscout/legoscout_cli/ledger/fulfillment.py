#!/usr/bin/env python3
"""The single reader of how a listing can be received.

`available_fulfillment` is the ONE field that answers "can this be shipped, can
it be picked up, or both". Nothing else in the pipeline may decide that: not the
source, not `pickup_miles`, not a $0.00 shipping figure, not the word "pickup"
appearing somewhere in a title. Before this field existed the answer was
reassembled independently in the validator, the shipping backfill, the pricing
skill and the row builders, and they disagreed -- the 2026-07-26 audit found ten
active rows priced at free pickup while sitting in other states.

It is a SET, not an enum, because a listing can genuinely offer both. A
ShopGoodwill lot is usually shipped, but https://shopgoodwill.com/item/271837154
carries `pickupOnly: true` and can only be collected in Tallahassee -- so the
answer has to be read off each listing, never off its marketplace.

Stored as a JSON array in the deals table, always sorted, always non-empty:

    ["shipping"]                    seller ships; pickup is not offered
    ["local_pickup"]                pickup only; the seller will not ship
    ["local_pickup", "shipping"]    the listing offers both

There is deliberately NO "unknown" member. A listing whose fulfillment could not
be read is not a listing that offers nothing -- it is an unfinished capture, and
this module raises rather than letting it default to shipping. Where to read the
answer for each marketplace is written per source in
`legoscout_cli/sources/readers/<namespace>.py`.

    legoscout deals refresh available_fulfillment                       # ledger coverage
    legoscout deals refresh available_fulfillment 'hibid|313898136'     # one record
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable

FIELD = "available_fulfillment"

LOCAL_PICKUP = "local_pickup"
SHIPPING = "shipping"

# Canonical order. `normalize()` sorts against this so two records that offer
# the same things compare equal as stored text.
VALUES: tuple[str, ...] = (LOCAL_PICKUP, SHIPPING)


class Undetermined(ValueError):
    """The record does not say how the listing can be received.

    Deliberately loud. Defaulting to shipping is what put ten out-of-state
    pickup lots on the deals page at $0.00 freight.
    """


def normalize(values: Iterable[str]) -> list[str]:
    """Validate and canonicalize a set of fulfillment options for writing."""
    seen = []
    for v in values:
        text = str(v).strip().lower()
        if text not in VALUES:
            raise ValueError(
                "%r is not a fulfillment option -- expected some of %s"
                % (v, "/".join(VALUES)))
        if text not in seen:
            seen.append(text)
    if not seen:
        raise ValueError(
            "a listing offers at least one way to receive it; an empty set is "
            "an unread listing, not a real answer")
    return [v for v in VALUES if v in seen]


def parse(raw: Any) -> tuple[str, ...]:
    """Read a stored value. Accepts the list `ledger_db` hands back, or the raw
    JSON text a direct SQL read returns."""
    if raw is None:
        raise Undetermined("%s is not recorded" % FIELD)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("%s is not JSON: %r (%s)" % (FIELD, raw, exc)) from None
    if not isinstance(raw, (list, tuple)):
        raise ValueError(
            "%s must be an array of %s -- got %r. It is a set, not an enum: a "
            "listing can offer both." % (FIELD, "/".join(VALUES), raw))
    return tuple(normalize(raw))


def of(deal: dict[str, Any]) -> tuple[str, ...]:
    """The fulfillment options for one deal record. Raises if absent or bad."""
    try:
        return parse(deal.get(FIELD))
    except Undetermined as exc:
        raise Undetermined(
            "%s: %s. Read it off the listing -- see that source's "
            "`available_fulfillment()` reader -- or run "
            "`legoscout deals refresh available_fulfillment`. Do not assume it "
            "ships."
            % (deal.get("listing_key", "<no listing_key>"), exc)) from None
    except ValueError as exc:
        raise ValueError("%s: %s" % (deal.get("listing_key", "<no listing_key>"), exc)) from None


def offers_shipping(deal: dict[str, Any]) -> bool:
    return SHIPPING in of(deal)


def offers_pickup(deal: dict[str, Any]) -> bool:
    return LOCAL_PICKUP in of(deal)


def is_pickup_only(deal: dict[str, Any]) -> bool:
    """The gate case: Adam collects it himself or the deal is dead."""
    return of(deal) == (LOCAL_PICKUP,)


def is_recorded(deal: dict[str, Any]) -> bool:
    """Whether the field can be read at all, without raising. For reporting
    and migration only -- decision code calls `of()` and lets it raise."""
    try:
        of(deal)
    except ValueError:
        return False
    return True


def describe(deal: dict[str, Any]) -> str:
    """Display text. The deals page shows this rather than re-deriving it."""
    opts = of(deal)
    if opts == (LOCAL_PICKUP,):
        return "pickup only"
    if opts == (SHIPPING,):
        return "ships"
    return "ships or pickup"


# Rows whose fulfillment no longer decides anything: Adam has already rejected
# or bought them, and the listing behind a rejected row is usually gone, so it
# can never be re-read. They predate the field and render without a label rather
# than taking the whole deals page down. Mirrors the same exemption in
# `validate.py`. Anything still in play must carry the field.
SETTLED = frozenset(("rejected", "purchased"))


def label(deal: dict[str, Any]):
    """The deals-page cell text, or None on a settled row that predates the field.

    Deliberately NOT `describe()`: the page's column is narrow and its three
    strings are `ship/pickup`, `pickup` and `ship`. One owner for every
    rendering of the field, so the page can never re-derive it from
    `pickup_miles`, from a $0.00 shipping figure, or from the source namespace.
    """
    if deal.get(FIELD) is None and deal.get("status") in SETTLED:
        return None
    opts = of(deal)
    if len(opts) == 2:
        return "ship/pickup"
    return "pickup" if opts[0] == LOCAL_PICKUP else "ship"


def _report() -> int:
    import collections

    from . import db as ledger_db

    deals = ledger_db.load_deals()
    by_source: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    for d in deals:
        ns = str(d.get("listing_key", "|")).split("|")[0]
        active = d.get("status") not in ("unavailable", "blocked", "rejected")
        try:
            label = "+".join(of(d))
        except ValueError:
            label = "MISSING"
        by_source[ns][label] += 1
        if active:
            by_source[ns]["_active"] += 1

    print("%-22s %7s %7s  %s" % ("SOURCE", "TOTAL", "ACTIVE", "AVAILABLE_FULFILLMENT"))
    missing = 0
    for ns in sorted(by_source):
        c = by_source[ns]
        total = sum(v for k, v in c.items() if not k.startswith("_"))
        parts = ", ".join("%s=%d" % (k, v) for k, v in sorted(c.items())
                          if not k.startswith("_"))
        missing += c.get("MISSING", 0)
        print("%-22s %7d %7d  %s" % (ns, total, c["_active"], parts))
    print("\n%d of %d records carry %s" % (len(deals) - missing, len(deals), FIELD))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("listing_key", nargs="?",
                    help="report one record instead of ledger coverage")
    a = ap.parse_args()
    if not a.listing_key:
        return _report()

    from . import db as ledger_db

    deal = ledger_db.get_deal(a.listing_key)
    if deal is None:
        sys.exit("available_fulfillment: no deal with listing_key %r" % a.listing_key)
    try:
        print(json.dumps({
            "listing_key": a.listing_key,
            FIELD: list(of(deal)),
            "pickup_only": is_pickup_only(deal),
            "ships": offers_shipping(deal),
            "display": describe(deal),
            "item_location": deal.get("item_location"),
            "pickup_miles": deal.get("pickup_miles"),
        }, indent=1))
    except ValueError as exc:
        sys.exit("available_fulfillment: %s" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
