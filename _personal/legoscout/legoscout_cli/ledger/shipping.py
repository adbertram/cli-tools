#!/usr/bin/env python3
"""The single shape of a source's own destination shipping quote.

`shipping_estimate` records what the MARKETPLACE published for delivery to
`47725`. It is not the landed cost -- `fee_breakdown.shipping_handling` is, and
`build_deal_record` derives that from this rather than letting a second agent
retype the number.

Four fields, and deliberately only four:

    {"status": "quoted",   "shipping_price": 16.23, "handling_price": 2.0,
                           "service": "GROUND_HOME_DELIVERY"}
    {"status": "unquoted", "reason": "PACKAGE.WEIGHT.INVALID"}

`destination_zip` and `country` are NOT stored. Ship-to is US `47725` on every
source by project rule, and 2,401 rows were each carrying the same two
constants. `total` is not stored either: it is `shipping_price + handling_price`,
and storing a derived value is what made the first design need a validator rule
to confirm a number agreed with its own inputs. `total_of()` computes it.

`unquoted` is a real answer and never means $0.00. A HiBid house that invoices
freight after the sale, a ShopGoodwill lot whose weight will not calculate, and
a pickup-only listing all publish no rate -- and pricing any of them at zero is
the fiction the 2026-07-26 audit found on ten rows.

    legoscout deals refresh shipping_estimate 'shopgoodwill|272682584'   # one record
    legoscout deals refresh shipping_estimate                            # ledger coverage
    legoscout deals refresh shipping_estimate --normalize-ledger --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

FIELD = "shipping_estimate"

QUOTED = "quoted"
UNQUOTED = "unquoted"

QUOTED_FIELDS = ("status", "shipping_price", "handling_price", "service")
UNQUOTED_FIELDS = ("status", "reason")


class Unreadable(ValueError):
    """A stored value that is not a shipping estimate. Never reshaped silently."""


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def quoted(shipping_price, handling_price=None, service=None) -> dict:
    """A published rate. `total` is computed by `total_of`, never passed in."""
    price = _num(shipping_price)
    if price is None:
        raise Unreadable(
            "a quoted estimate needs a numeric shipping_price, got %r -- call "
            "unquoted(reason) when the source published no rate" % (shipping_price,))
    return {
        "status": QUOTED,
        "shipping_price": round(price, 2),
        # `None` means the source publishes no separate handling line, which is
        # the normal Poshmark/eBay/Depop shape. It is not zero-with-confidence
        # and it is not unknown-shipping; `total_of` reads it as no extra charge.
        "handling_price": None if _num(handling_price) is None else round(_num(handling_price), 2),
        "service": None if service is None else str(service),
    }


def unquoted(reason) -> dict:
    """No rate published, and WHY. A reason is required: 'unquoted' with no
    explanation is indistinguishable from a worker that forgot to look."""
    text = str(reason or "").strip()
    if not text:
        raise Unreadable(
            "unquoted() needs a reason -- record what the source said (pickup "
            "only, weight invalid, freight invoiced after the sale) rather than "
            "an unexplained blank")
    return {"status": UNQUOTED, "reason": text}


# ---------------------------------------------------------------------------
# Legacy shapes. Seven of them reached the ledger because nothing enforced one,
# and six source-worker agents each invented their own spelling in a single run.
# This is a mapping TABLE rather than a reader per shape.
# ---------------------------------------------------------------------------

# Old spellings of each surviving field, most authoritative first.
ALIASES = {
    "shipping_price": ("shipping_price", "shipping_cost", "cost", "carrier_rate"),
    "handling_price": ("handling_price", "handling_cost", "handling_assumed"),
    # `basis` is deliberately NOT here. Depop's worker used it for provenance
    # prose ("Depop search-row price_breakdown.shipping"), which is not the name
    # of a shipping service, and carrying it as one puts a sentence about the
    # crawler in a field the deals page shows as a carrier.
    "service": ("service", "shipping_class_name"),
    "reason": ("reason", "note"),
}

# Keys that carried no information this object keeps: project constants, a
# derived total, a flag that already has its own ledger column
# (`shipping_estimated`), and per-source provenance prose.
DISCARDED = frozenset({
    "destination_zip", "country", "total", "shipping_estimated", "status",
    "source_quoted", "shipping_payer", "total_price_quoted", "origin_zip",
    "origin", "seller_box_fee", "confidence", "carrier", "note", "basis",
})


def normalize(value: Any) -> dict | None:
    """Any historical spelling -> the canonical object, or `None`.

    `None` in and `None` out: a source that publishes no quote at all (HiBid,
    K-BID, Facebook) legitimately records nothing, and that is different from
    recording an unquoted answer with a reason.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise Unreadable("%s is not JSON: %r" % (FIELD, value[:120])) from None
    if value is None:
        return None

    # A bare number is what three source workers wrote (`4.39`, `13.81`, `50.0`).
    # It is the rate the source published, so it survives as one.
    if _num(value) is not None:
        return quoted(_num(value))

    if not isinstance(value, dict):
        raise Unreadable(
            "%s is %s, not an object -- see shipping_estimate.quoted()/unquoted()"
            % (FIELD, type(value).__name__))

    unknown = [k for k in value
               if k not in DISCARDED and not any(k in names for names in ALIASES.values())]
    if unknown:
        raise Unreadable(
            "%s carries unrecognized key(s) %s -- add the spelling to "
            "shipping_estimate.ALIASES or fix the producer; do not let a new "
            "invented shape reach the ledger" % (FIELD, sorted(unknown)))

    picked = {}
    for field, names in ALIASES.items():
        for name in names:
            if value.get(name) is not None:
                picked[field] = value[name]
                break

    price = _num(picked.get("shipping_price"))
    if price is not None:
        return quoted(price, picked.get("handling_price"), picked.get("service"))
    # No rate AND no reason is not an unquoted answer -- it is the old all-null
    # default object, which meant the crawl recorded nothing at all. Calling that
    # `unquoted` would claim someone looked and the source said no. `None` is the
    # truthful reading, and it leaves the row eligible for a later re-read.
    reason = picked.get("reason")
    return unquoted(reason) if reason else None


def of(deal: dict) -> dict | None:
    """The estimate on one deal record. Raises on a shape nothing can read."""
    try:
        return normalize(deal.get(FIELD))
    except Unreadable as exc:
        raise Unreadable("%s: %s" % (deal.get("listing_key", "<no listing_key>"), exc)) from None


def is_quoted(deal: dict) -> bool:
    estimate = of(deal)
    return bool(estimate) and estimate["status"] == QUOTED


def total_of(deal: dict) -> float | None:
    """The full delivered charge, or `None` when nothing was quoted.

    `0.0` is a real answer -- a listing can genuinely state free shipping -- so
    callers must test for `None`, never for falsiness.
    """
    estimate = of(deal)
    if not estimate or estimate["status"] != QUOTED:
        return None
    return round(estimate["shipping_price"] + (estimate["handling_price"] or 0.0), 2)


def describe(deal: dict) -> str:
    estimate = of(deal)
    if not estimate:
        return "no quote published"
    if estimate["status"] != QUOTED:
        return "not quoted (%s)" % estimate["reason"]
    return "$%.2f%s" % (total_of(deal),
                        " %s" % estimate["service"] if estimate["service"] else "")


def _report(normalize_ledger, dry_run) -> int:
    import collections

    from . import db as ledger_db

    doc = ledger_db.load_document()
    by_source = collections.defaultdict(collections.Counter)
    changed = 0
    for deal in doc["deals"]:
        namespace = str(deal.get("listing_key", "|")).split("|")[0]
        try:
            estimate = normalize(deal.get(FIELD))
        except Unreadable as exc:
            by_source[namespace]["UNREADABLE"] += 1
            print("  %-46s %s" % (deal.get("listing_key"), exc), file=sys.stderr)
            continue
        by_source[namespace][estimate["status"] if estimate else "none"] += 1
        if normalize_ledger and deal.get(FIELD) != estimate:
            deal[FIELD] = estimate
            changed += 1

    print("%-22s %s" % ("SOURCE", "SHIPPING_ESTIMATE"))
    for namespace in sorted(by_source):
        counts = by_source[namespace]
        print("%-22s %s" % (namespace, ", ".join("%s=%d" % kv for kv in sorted(counts.items()))))

    if normalize_ledger:
        print("\n%d record(s) rewritten to the canonical shape%s"
              % (changed, " (dry run, nothing written)" if dry_run else ""))
        if changed and not dry_run:
            ledger_db.save(doc)
            print("ledger updated")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("listing_key", nargs="?")
    ap.add_argument("--normalize-ledger", action="store_true",
                    help="rewrite every stored estimate into the canonical shape")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not a.listing_key:
        return _report(a.normalize_ledger, a.dry_run)

    from . import db as ledger_db

    deal = ledger_db.get_deal(a.listing_key)
    if deal is None:
        sys.exit("shipping_estimate: no deal with listing_key %r" % a.listing_key)
    print(json.dumps({"listing_key": a.listing_key,
                      FIELD: of(deal),
                      "total": total_of(deal),
                      "display": describe(deal)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
