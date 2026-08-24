#!/usr/bin/env python3
"""Re-read one field across the ledger, from the listing itself.

Five scripts used to do this: `backfill_available_fulfillment.py`,
`backfill_item_location.py`, `backfill_auction_state.py`,
`backfill_listing_type.py` and `backfill_shipping.py`. All five are deleted.
Their `main()` loops were 290 code lines of the same thing -- argparse with
`--dry-run` / `--apply` / `--source` / `--limit`, `ledger_db.load_document()`,
a status skip set, a namespace filter, an already-answered predicate, a per-row
try/except collecting undetermined rows, a JSON report, and one save at the end.
Only the field, the predicate and the writer differed, so those are the config
and this is the loop.

Where the answer comes from is `legoscout_cli/sources/readers/<namespace>.py`,
one module per marketplace with one function per deal-record column. Nothing here
knows a marketplace's field names.

    legoscout deals refresh --list
    legoscout deals refresh available_fulfillment --dry-run
    legoscout deals refresh item_location --apply --source shopgoodwill
    legoscout deals refresh shipping_estimate --dry-run --limit 5
    legoscout deals refresh item_location --apply --set 'liveauctioneers|236411349=Ottawa, IL'

Two rules every sweep obeys:

  * A row that cannot be read is REPORTED, never guessed. `available_fulfillment`
    exists because a 2026-07-26 audit found ten rows priced as free in-radius
    pickup while sitting in other states -- a missing answer read as shipping.
  * A row Adam has acted on is left alone. Repricing an `inquired` or
    `bid_placed` row rewrites a decision he already made.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import fulfillment as af  # noqa: E402
from ..pricing import fees  # noqa: E402
from . import db as ledger_db  # noqa: E402
from ..sources import listing  # noqa: E402
from ..pricing import pickup_area  # noqa: E402
from . import shipping as se  # noqa: E402
from ..sources import readers as sources  # noqa: E402

# Dead listings. Nothing on them can be re-read, and their numbers are history.
INACTIVE = ("unavailable", "blocked", "rejected")
# Rows Adam has already acted on. `backfill_shipping.py` excluded these for the
# same reason: a re-price rewrites the basis of a decision he already took.
ACTIONED = ("rejected", "purchased", "inquired", "bid_placed")

# Rows are committed every this many writes. `ledger_db.save()` is one
# transaction (ledger_db.py), so a partial file is impossible -- but the old
# scripts saved ONCE at the very end, so an abort at row 40 of 41 threw away all
# 40 completed reads along with the CLI calls that earned them.
BATCH = 25

# What a row can genuinely meet on the wire, and nothing else.
#
# This tuple used to be `Exception`. `listing.Undetermined` already has its own
# branch above it, so the blanket clause caught only DEFECTS -- a TypeError, a
# KeyError, an sqlite error -- and filed each one as "this listing did not
# answer", complete with a message telling a human to go read the page by hand.
# A reader-cache defect on 2026-08-06 did exactly that: 17 working source
# modules were reported as `no_reader` and nobody saw a stack trace.
#
#   OSError               every socket/DNS/TLS/timeout failure and every missing
#                         file. `urllib.error.URLError` and `HTTPError` are
#                         OSError subclasses, so this covers the HTTP readers.
#   subprocess.SubprocessError
#                         the source CLIs: `TimeoutExpired` from
#                         `listing.cli`'s 180s cap, `CalledProcessError` from a
#                         checked call.
#   json.JSONDecodeError  a CLI or a page that answered with something that is
#                         not the JSON its reader parses.
#   af.Undetermined       `available_fulfillment` is not recorded on this row
#                         yet, which is the OTHER sweep's job.
#   se.Unreadable         the row's stored `shipping_estimate` is not a shape
#                         this module can read.
#
# Everything else propagates, crashes the run, and gets fixed.
UNREAD = (OSError, subprocess.SubprocessError, json.JSONDecodeError,
          af.Undetermined, se.Unreadable)


class Sweep:
    """One field, and the two things that differ between backfills.

    The field name IS the source-module function name, so a read needs no
    mapping. `compute` is the alternative for a field derived from the record
    itself rather than read off the listing -- `fee_breakdown` is arithmetic
    over fields already stored.
    """

    def __init__(self, field, *, apply_value, done, compute=None,
                 gate=None, skip_status=INACTIVE, needs=()):
        self.field = field
        self.compute = compute
        self.apply_value = apply_value
        self.done = done
        self.gate = gate
        self.skip_status = skip_status
        self.needs = needs

    def read(self, deal):
        if self.compute:
            return self.compute(deal)
        return sources.read(deal, self.field)


# --- the four sweeps --------------------------------------------------------

def _write_fulfillment(deal, value):
    deal[af.FIELD] = af.normalize(value)
    return {af.FIELD: deal[af.FIELD]}


def _write_location(deal, value):
    """Store the location verbatim, then resolve reach.

    `pickup_miles: None` is a real answer -- "outside the radius" -- and it is
    what the pickup-only gate in legoscout-pricing keys off. An unresolvable
    location lands in `undetermined` rather than being stored.

    `pickup_area.resolve` reports an unresolvable location as a bare
    `ValueError`, which says nothing about whose fault it is. It is named here
    as what it actually is -- a listing whose location text does not answer the
    question -- so `run()` no longer needs a blanket `except Exception` to file
    it, and a real defect on this path stays a crash.
    """
    try:
        verdict = pickup_area.resolve(value)
    except ValueError as exc:
        raise listing.Undetermined(
            "%s: %r is not a resolvable pickup location: %s"
            % (deal["listing_key"], value, exc)) from exc
    deal["item_location"] = value
    deal["pickup_miles"] = verdict["miles"]
    return {"item_location": value, "pickup_miles": verdict["miles"],
            "in_radius": verdict["eligible"]}


def _write_shipping(deal, value):
    """Store the estimate in canonical form, whatever spelling arrived.

    A plain string from `--set` is an agent's page read of WHY no rate exists,
    so it becomes `unquoted(reason)`. That is the documented way to correct a
    row whose stored $0.00 was an unparsed rate rather than free shipping --
    `ebay|336691199794` recorded `eBay seller-calculated shipping` at $0.00,
    which eBay computes at checkout and never quoted at all.
    """
    if isinstance(value, str):
        value = se.unquoted(value)
    deal[se.FIELD] = se.normalize(value)
    return {se.FIELD: deal[se.FIELD], "total": se.total_of(deal)}


def _write_auction_end(deal, value):
    deal["auction_end_date"] = value
    return {"auction_end_date": value}


def _compute_fee_breakdown(deal):
    """Landed cost from the price `price_basis` names, plus whatever shipping is
    known. Run the `shipping_estimate` sweep FIRST, so a source that publishes a
    rate has already stored it.

    An unknown freight cost is passed as `None`, never as 0.0: `fees.landed_cost`
    then marks the row `shipping_unknown` and `landed_is_floor`, so the deals
    page reads it as the floor it is instead of as free delivery.
    """
    from . import build_record as bdr

    hammer = bdr.priced_amount(deal)
    if hammer is None:
        raise listing.Undetermined(
            "no numeric price under price_basis=%r, so there is nothing to build "
            "a landed cost from" % deal.get("price_basis"))
    breakdown = fees.landed_cost(deal["listing_key"], hammer,
                                 se.total_of(deal), handling=0.0)
    deal["fee_breakdown"] = breakdown
    deal["estimated_total"] = breakdown["landed_total"]
    weight = deal.get("weight_lbs")
    if isinstance(weight, (int, float)) and weight:
        deal["per_lb_price"] = round(breakdown["landed_total"] / weight, 4)
        deal["per_lb_price_basis"] = "landed"
    return breakdown, "hammer=%s shipping=%s -> landed %s%s" % (
        hammer, se.total_of(deal), breakdown["landed_total"],
        " (FLOOR, shipping unknown)" if breakdown["shipping_unknown"] else "")


def _landed_cost_is_current(deal):
    """Whether the stored breakdown is still a valid answer for this row.

    Two ways it stops being one, and the sweep must rebuild in both:

      * its `hammer` is not the price `price_basis` names, so the landed cost was
        built from the wrong number;
      * it ignores a shipping quote the source published, which is the defect
        `validate_deal_records.shipping_errors` reports. That rule is imported
        rather than restated -- if the validator calls a row wrong, the sweep
        must be the thing that fixes it, not a second opinion about it.
    """
    from . import schema as deal_schema
    from . import validate as vdr

    breakdown = deal.get("fee_breakdown")
    if not breakdown:
        return False
    if vdr.shipping_errors(deal):
        return False
    hammer = deal_schema.num(breakdown.get("hammer"))
    price = deal_schema.priced_amount(deal)
    if hammer is None or price is None:
        return True
    return abs(hammer - price) <= 0.005


def _origin_of(deal):
    """(zip, city, state, label) for a carrier quote, or raise.

    Order: the origin the crawl already captured, then HiBid's own lot state,
    then the curated house table. `backfill_shipping.origin_for` called
    `est.load(...)`, a function that does not exist in
    `estimate_inbound_shipping`, so every non-HiBid row raised AttributeError --
    outside its `except (ValueError, OSError)`, which crashed the whole run
    rather than reporting one row.
    """
    from ..pricing import inbound_shipping as est

    namespace = deal["listing_key"].split("|")[0]
    zip_ = str(deal.get("origin_zip") or "").strip()
    if zip_:
        return zip_, "", "", "origin_zip on the record"
    if namespace == "hibid":
        return est.hibid_origin(deal["listing_key"].split("|")[-1])
    with open(est.ORIGINS, encoding="utf-8") as fh:
        houses = json.load(fh)["houses"]
    name = deal.get("seller_name") or deal.get("source") or ""
    house = houses.get(name) or houses.get(name.lower())
    if not house:
        raise listing.Undetermined(
            "no origin for %r: the record carries no origin_zip and %r is not in "
            "seller_origins.json -- capture the origin at crawl time rather than "
            "assuming one" % (deal["listing_key"], name))
    return house["zip"], house.get("city", ""), house.get("state", ""), name


def _compute_carrier_estimate(deal):
    """A carrier rate for a listing whose SOURCE publishes none.

    Auction houses invoice freight after the sale, so the rate that decides the
    bid does not exist at bid time. This quotes one so the row carries a
    defensible number instead of a null -- and marks it `shipping_estimated`, the
    column the deals page already reads, so it never reads as a seller quote.

    A row with no stated weight cannot be quoted, and this NEVER invents one.
    """
    from ..pricing import inbound_shipping as est

    if not af.offers_shipping(deal):
        raise listing.Undetermined(
            "the seller does not ship, so there is no freight to estimate")
    weight = deal.get("weight_lbs")
    if not isinstance(weight, (int, float)) or not weight:
        raise listing.Undetermined(
            "no stated weight, and a weight assumed to make a quote possible is "
            "a fabricated landed cost")
    zip_, city, state, label = _origin_of(deal)
    quote = est.quote(zip_, city, state, weight)
    if "error" in quote:
        raise listing.Undetermined(quote["error"])
    estimate = se.quoted(
        shipping_price=quote["carrier_rate"],
        handling_price=quote["handling_assumed"],
        service="%s %s from %s (%s, %s %s) -- estimate, not a seller quote"
                % (quote["carrier"], quote["service"], label, city, state, zip_))
    deal[se.FIELD] = estimate
    deal["shipping_estimated"] = True
    return estimate, "$%.2f %s + $%.2f handling from %s" % (
        quote["carrier_rate"], quote["carrier"], quote["handling_assumed"], zip_)


# The three spellings of "nobody has recorded this yet" in a string field.
# `unknown` is the sentinel output_contract.md defines and the one
# `build_deal_record._typed_default` writes; `None` and `""` are what the ledger
# held before `deal_schema.validate` started refusing them. A `done` test that
# only checks truthiness reads the sentinel as an ANSWER and skips the row
# forever -- which is what `item_location` did to 40 rows the moment they were
# migrated from `None` to `unknown`.
_NOT_RECORDED = (None, "", "unknown")


def _recorded(deal: dict, field: str) -> bool:
    return deal.get(field) not in _NOT_RECORDED


SWEEPS = {
    "available_fulfillment": Sweep(
        "available_fulfillment",
        done=af.is_recorded, apply_value=_write_fulfillment),
    "item_location": Sweep(
        "item_location",
        done=lambda d: _recorded(d, "item_location"),
        # Only a row that can actually be collected needs a pickup point, and an
        # unrecorded `available_fulfillment` is the other sweep's job.
        gate=lambda d: af.is_recorded(d) and af.offers_pickup(d),
        needs=("available_fulfillment",),
        apply_value=_write_location),
    "shipping_estimate": Sweep(
        "shipping_estimate",
        done=lambda d: se.of(d) is not None,
        apply_value=_write_shipping),
    "auction_end_date": Sweep(
        "auction_end_date",
        # `not-an-auction` on a row whose listing_type says auction is a POSITIVE
        # claim that contradicts itself; 53 live ShopGoodwill lots stored it
        # while the source returned a real endTime.
        done=lambda d: (_recorded(d, "auction_end_date")
                        and d.get("auction_end_date") != "not-an-auction"),
        gate=lambda d: str(d.get("listing_type") or "").startswith("auction"),
        apply_value=_write_auction_end),
    "shipping_estimated": Sweep(
        "shipping_estimated", compute=_compute_carrier_estimate,
        # Only rows the SOURCE left unpriced. A published rate always wins over
        # a carrier estimate.
        done=lambda d: se.is_quoted(d),
        skip_status=INACTIVE + ACTIONED[1:],
        needs=("available_fulfillment", "shipping_estimate"),
        apply_value=lambda deal, value: {se.FIELD: value,
                                         "shipping_estimated": True,
                                         "total": se.total_of(deal)}),
    "fee_breakdown": Sweep(
        "fee_breakdown", compute=_compute_fee_breakdown,
        # A breakdown whose `hammer` is not the price `price_basis` names is not
        # an answer, it is a landed cost built from the wrong number. Two active
        # Depop rows were in that state, hidden because the validator's inline
        # basis table omitted the since-retired `ask_price` basis and skipped
        # the check entirely.
        done=_landed_cost_is_current,
        skip_status=INACTIVE + ("inquired", "bid_placed", "purchased"),
        needs=("shipping_estimate",),
        apply_value=lambda deal, value: {"fee_breakdown": value,
                                         "estimated_total": deal["estimated_total"]}),
}


def run(sweep, *, apply, source=None, limit=None, include_inactive=False,
        overrides=(), keys=(), force=False, ledger=None):
    doc = ledger_db.load_document(ledger) if ledger else ledger_db.load_document()
    by_key = {d["listing_key"]: d for d in doc["deals"]}
    filled, undetermined, gone, no_reader = [], [], [], {}
    unread_by_exception: dict[str, int] = {}
    already = skipped = 0
    written_since_save = 0

    todo = []
    for spec in overrides:
        key, sep, raw = spec.partition("=")
        if not sep or not raw.strip():
            sys.exit("--set wants KEY=VALUE, got %r" % spec)
        if key not in by_key:
            sys.exit("--set: no deal with listing_key %r" % key)
        todo.append((by_key[key], raw.strip()))

    if not overrides:
        # Every counter this loop reports is scoped to the rows the caller
        # ASKED for, so the namespace and key filters run first. The status
        # check used to run ahead of them, and `--source k-bid` on a 199-row
        # source reported `skipped_by_status: 1605` -- the whole ledger's dead
        # rows, which reads as "your source is almost entirely dead".
        answering = None if sweep.compute else sources.answers(sweep.field)
        for deal in doc["deals"]:
            if keys and deal["listing_key"] not in keys:
                continue
            namespace = deal["listing_key"].split("|")[0]
            if source and namespace != source:
                continue
            if not include_inactive and deal.get("status") in sweep.skip_status:
                skipped += 1
                continue
            if sweep.gate and not sweep.gate(deal):
                continue
            # `--force` re-answers a row the predicate calls done. Needed after a
            # correction upstream: fixing an estimate does not by itself make the
            # landed cost built on the old one look stale.
            if not force and sweep.done(deal):
                already += 1
                continue
            if answering is not None and not answering.get(namespace):
                no_reader.setdefault(
                    namespace,
                    {"rows": 0,
                     "where_the_answer_is": sources.where(namespace, sweep.field)})
                no_reader[namespace]["rows"] += 1
                continue
            todo.append((deal, None))
        # `is not None`, not truthiness: `--limit 0` is a caller asking for zero
        # rows, and reading it as "no limit" ran the whole ledger instead.
        if limit is not None:
            todo = todo[:limit]

    for deal, override in todo:
        key = deal["listing_key"]
        try:
            if override is None:
                value, evidence = sweep.read(deal)
            else:
                value, evidence = override, "agent page read, passed via --set"
            record = sweep.apply_value(deal, value)
        except listing.Undetermined as exc:
            entry = {"listing_key": key, "why": str(exc)[:220]}
            (gone if getattr(exc, "gone", False) else undetermined).append(entry)
            continue
        except UNREAD as exc:
            name = type(exc).__name__
            unread_by_exception[name] = unread_by_exception.get(name, 0) + 1
            undetermined.append({"listing_key": key, "error_type": name,
                                 "why": "%s: %s" % (name, str(exc)[:200])})
            continue
        filled.append(dict(record, listing_key=key, evidence=str(evidence)[:120]))
        print("  %-46s %s" % (key, str(evidence)[:96]), file=sys.stderr, flush=True)
        written_since_save += 1
        if apply and written_since_save >= BATCH:
            ledger_db.save(doc) if ledger is None else ledger_db.save(doc, ledger)
            written_since_save = 0

    if apply and written_since_save:
        ledger_db.save(doc) if ledger is None else ledger_db.save(doc, ledger)

    return {
        "field": sweep.field,
        "considered": len(todo),
        "already_answered": already,
        "skipped_by_status": skipped,
        "filled": len(filled),
        "undetermined": undetermined,
        # Which wire failure produced the unread rows, counted by exception
        # type. A run whose `undetermined` is all `TimeoutExpired` is a slow
        # source; one that names anything surprising is a defect to chase, and
        # the count is what makes that visible in the report itself.
        "unread_by_exception": unread_by_exception,
        "listing_gone": gone,
        "no_reader": no_reader,
        "written": bool(apply and filled),
        "records": filled,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="legoscout deals refresh",
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("field", nargs="?", choices=sorted(SWEEPS))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source", help="one listing_key namespace")
    ap.add_argument("--include-inactive", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--key", action="append", default=[],
                    help="limit to these listing_keys (repeatable)")
    ap.add_argument("--force", action="store_true",
                    help="re-answer rows the done-predicate would skip")
    ap.add_argument("--ledger")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="write an agent-read answer for one row, through the "
                         "same resolve-and-write path the readers use")
    ap.add_argument("--list", action="store_true", help="the sweeps and what they read")
    a = ap.parse_args()

    if a.list:
        print("%-24s %s" % ("FIELD", "SOURCES THAT ANSWER"))
        for name, sweep in sorted(SWEEPS.items()):
            answering = ["(computed)"] if sweep.compute else [
                s for s, yes in sources.answers(sweep.field).items() if yes]
            print("%-24s %s" % (name, ", ".join(sorted(answering))))
        return 0

    if not a.field:
        ap.error("name a field, or pass --list")
    if a.apply == a.dry_run:
        sys.exit("pass exactly one of --apply / --dry-run")

    sweep = SWEEPS[a.field]
    for prerequisite in sweep.needs:
        print("note: %r reads %r; run that sweep first if it is incomplete"
              % (a.field, prerequisite), file=sys.stderr)

    out = run(sweep, apply=a.apply, source=a.source, limit=a.limit,
              include_inactive=a.include_inactive, overrides=a.set,
              keys=tuple(a.key), force=a.force, ledger=a.ledger)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
