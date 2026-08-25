#!/usr/bin/env python3
"""Build the LEGO Scout deals table rows -- one shape for bulk and sets alike.

There used to be two builders emitting two positional arrays, decoded on the
page through hand-maintained index maps. Since the score is now one number that
means the same thing in both categories, the table is one table, and a row is a
plain dict: adding a field is adding a key, not renumbering an index map.

Scoring fields come straight off the record. This builder computes no score and
derives no quality -- legoscout-deal-scoring owns every one of those numbers,
and a second implementation here is exactly how the two would drift.

This is the Python port of the five retired `.mjs` files. `legoscout display rows`
became `build_rows()`, `ledger_db.mjs` became direct `ledger.db` /
`ledger.sellers` calls plus `bidding_open()`, `legoscout_cli/display/rows.py` became
`listing_type()` / `is_bid_only_auction()`, `legoscout_cli/display/rows.py` became
`sources.registry` reads, and `available_fulfillment.mjs` became
`ledger.fulfillment.label()`. Node is no longer a dependency.

JavaScript `??` is null-coalescing, not falsy-or, so it is ported as
`_first_not_none(...)` and `0` / `0.0` survive. JavaScript `||` fallbacks are
ported as written, because `0` in and `0` out is the same result. These defaults
are the row contract, not error suppression.
"""
from __future__ import annotations

import argparse
import decimal
import json
import math
import re
import sys
from datetime import datetime, timezone
from urllib.parse import quote

from ..ledger import db as ledger_db
from ..ledger import fulfillment
from ..ledger import minifig_analysis
from ..ledger import sellers as sellers_db
from ..sources import registry

# The three values the page accepts. It THROWS on anything else, so an
# unenforced value does not degrade one row -- it takes the whole page down.
#
# Auction-ness must NEVER be inferred from price basis. A not-yet-started
# auction has no current price, so the old `price_basis == "current_price"` test
# silently reclassified every zero-bid auction as a firm buy-now listing --
# HiBid lot 314234951 (2026-07-26) showed a $61.33 profit as real money and
# survived the "buy-now only" filter while its auction was still 18 days out.
# `listing_type` is written by the collector and read verbatim here.
LISTING_TYPES = ("auction", "auction_with_buy_now", "fixed")

# Completeness Gate -- mirrors set-listing-analysis.md. Three tiers, evaluated in
# order: a seller who DISCLAIMS knowledge ("may be missing pieces") is not the
# same as one who ASSERTS incompleteness ("parts lot only"). Analyst prose about
# *profit* completeness is scrubbed first so the pipeline's own wording cannot
# self-trigger the gate.
ANALYST_NOISE_RE = re.compile(
    r"profit\s+is\s+incomplete|profit[_\s]incomplete|profit\s+is\s+not\s+complete"
    r"|incomplete\s+profit", re.I)
DISCLAIM_RE = re.compile(
    r"(may|might|could|possibly)\s+(be\s+|have\s+)?missing"
    r"|completeness\s+(has\s+)?(is\s+)?not\s+(been\s+)?(verified|guaranteed)"
    r"|not\s+verified\s+complete|does\s+not\s+warrant\s+completeness"
    r"|no\s+guarantee\s+of\s+completeness|not\s+guaranteed\s+complete"
    r"|sold\s+as[-\s]is|\bas-is\b|\buntested\b|not\s+confirmed\s+complete", re.I)
ASSERT_INCOMPLETE_RE = re.compile(
    r"\bnot\s+complete\b(?!ly)|\b(is|are|was|were)\s+incomplete\b"
    r"|\bincomplete\s+(set|sets|lot|build)\b|\bused\s+and\s+incomplete\b"
    r"|\bparts?\s+lot\s+only\b|\bparts\s+only\b|\bfor\s+parts\b"
    r"|\bsold\s+as\s+parts\b|\bmissing\s+(pieces|parts|minifig)"
    r"|\b(pieces|parts)\s+are\s+missing\b|\bpartial\s+(set|build)\b"
    r"|\b(large\s+)?majority\s+of\s+(the\s+)?[\w\s]{0,24}?(pieces|parts)"
    r"|\bmost\s+of\s+the\s+(pieces|parts)\b"
    r"|\bnot\s+all\s+(of\s+)?(the\s+)?(pieces|parts)\b", re.I)
COMPLETE_RE = re.compile(
    r"\b(100% complete|all pieces (are )?(present|included)|complete set"
    r"|is complete|factory sealed|new in box|sealed|unopened|nib)\b", re.I)

# `zero_comp_note` holds either a short LABEL ("no sold comps") or a paragraph of
# appraiser prose explaining a zero-comp verdict. A label belongs in the cell; a
# paragraph does not fit in a table column and already reaches Adam as the
# dagger tooltip (`display/server.py`). This is the line between them.
COMP_REASON_MAX = 40

_ENDS_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TRAILING_ZEROS_RE = re.compile(r"\.?0+$")
_MONEY_STRIP_RE = re.compile(r"[$,]")


class _Undefined:
    """A key JavaScript would leave `undefined`, which `JSON.stringify` omits."""

    def __repr__(self):
        return "undefined"


UNDEFINED = _Undefined()


def _first_not_none(*values):
    """JavaScript `??`: the first value that is neither None nor undefined.

    `0` and `0.0` are answers and survive. A falsy-or here is how a $0.00 hammer
    would silently become the next candidate in the chain.
    """
    for value in values:
        if value is not None and value is not UNDEFINED:
            return value
    return None


def _to_fixed(value, digits):
    """ECMAScript `Number.prototype.toFixed`.

    The spec picks the integer n for which `n / 10**digits - x` is closest to
    zero, and on a tie picks the LARGER n. Python's `round()` is banker's
    rounding, which breaks ties the other way half the time, so a 12.5% premium
    would print as 12% here and 13% in the retired builder.

    A non-finite input is rejected by name. `Decimal("Infinity").quantize()`
    raises `InvalidOperation`, whose whole message is
    `[<class 'decimal.InvalidOperation'>]` -- true, and useless for finding the
    field that carried the infinity.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(
            "cannot render %r to %d decimal places: it is not a number" % (value, digits))
    quantum = decimal.Decimal(1).scaleb(-digits)
    exact = decimal.Decimal(value)
    return str(exact.quantize(quantum, rounding=decimal.ROUND_HALF_UP))


def listing_type(deal):
    value = deal.get("listing_type")
    if value not in LISTING_TYPES:
        raise ValueError(
            "%s: listing_type is %s, expected one of %s. Fix the collector: "
            "deal_schema.json requires the field, so no new record can reach "
            "the ledger without it."
            % (deal.get("listing_key"), json.dumps(value), ", ".join(LISTING_TYPES)))
    return value


def is_bid_only_auction(deal):
    """Bid-only auction: no firm price exists, so the figure on the page is an
    opening or current bid and every number derived from it is a ceiling."""
    return listing_type(deal) == "auction"


def bidding_open(deal, now=None):
    """A listing Adam cannot act on right now is not a deal.

    Auction sites publish a catalog as soon as the house posts it -- HiBid weeks
    ahead -- and those lots render identically to live ones.

    The START DATE decides whenever there is one, because a date self-updates
    against the clock while a stored flag goes stale the moment bidding opens.

    `bidding_open` is the fallback, not the primary. AuctionZip, AuctionNinja,
    K-BID and eBay publish no bid-open timestamp at all, so on those sources the
    date can never answer and the worker's own read of the lot is the only
    evidence there is. Requiring the date instead cost 2 good eBay lots on
    2026-08-04, which were dropped rather than recorded.

    A row with neither answer is not an unopened auction; it stays visible.
    """
    now = now or datetime.now(timezone.utc)
    start = deal.get("auction_start_date")
    if start and start not in ("unknown", "not-an-auction"):
        parsed = _parse_date(start)
        if parsed is not None:
            return parsed <= now
    flag = deal.get("bidding_open")
    if isinstance(flag, bool):
        return flag
    return True


def _parse_date(text):
    """`Date.parse`'s answer for the shapes the ledger actually stores, or None."""
    raw = str(text).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def set_completeness(deal):
    stored = deal.get("set_completeness")
    if stored in ("incomplete", "complete", "unknown"):
        return stored
    observations = deal.get("observations")
    rationale = (observations or {}).get("model_rationale") \
        if isinstance(observations, dict) else None
    text = " ".join(part for part in (deal.get("title"), deal.get("notes"),
                                      rationale, deal.get("risks_unknowns"))
                    if part)
    text = ANALYST_NOISE_RE.sub(" ", text)
    if DISCLAIM_RE.search(text):
        return "unknown"
    if ASSERT_INCOMPLETE_RE.search(text):
        return "incomplete"
    if COMPLETE_RE.search(text):
        return "complete"
    return "unknown"


def short_ends(end_date):
    if not end_date or end_date in ("not-an-auction", "unknown"):
        return None
    hit = _ENDS_RE.search(str(end_date))
    return "%s-%s" % (hit.group(2), hit.group(3)) if hit else None


def parse_money(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if not value or value == "unknown":
        return None
    try:
        number = float(_MONEY_STRIP_RE.sub("", str(value)))
    except ValueError:
        return None
    return number if number == number and abs(number) != float("inf") else None


def set_numbers_array(deal):
    raw = deal.get("set_numbers")
    if isinstance(raw, list) and raw:
        return raw
    if isinstance(raw, str) and raw.strip():
        return [part.strip() for part in raw.split(",") if part.strip()]
    return []


def comp_value(deal, key):
    """A comp cell is either a number or a REASON.

    Collapsing "no sold comps" to a bare "unknown" reads as a pipeline failure
    rather than a real BrickLink answer -- set-listing-analysis.md requires the
    reason survive to the table.

    The reason comes from `zero_comp_note`, NOT from the comp field. The comp
    fields are typed `number|null` and 51 rows held a reason string in them
    instead, which no profit calculation could read; a one-time migration on
    2026-08-05 moved them. One field holds the number, one field holds the
    reason, and this reads whichever one exists.
    """
    number = parse_money(deal.get(key))
    if number is not None:
        return number
    raw = deal.get("zero_comp_note")
    note = raw.strip() if isinstance(raw, str) else ""
    if note and note.lower() != "unknown" and len(note) <= COMP_REASON_MAX:
        return note
    return "unknown" if set_numbers_array(deal) else "no set # in listing"


def profit_incomplete(deal):
    """`set_analysis` is an ARRAY of per-set entries, one per detected set, and
    every entry carries `potential_profit` -- see `ledger/set_analysis.py`, the
    only writer. Two legacy spellings are gone: `set_analysis.sets`, a wrapper
    that matched none of the array-shaped rows, and the entry keys `profit` /
    `set_profit`, which meant this same number. `net_after_fees` and
    `net_resale_after_fees` do NOT: they are resale before cost, so an entry
    carrying only one of those is genuinely unpriced and must read as
    incomplete."""
    if deal.get("profit_incomplete") is True:
        return True
    nums = deal.get("set_numbers") if isinstance(deal.get("set_numbers"), list) else []
    sets = deal.get("set_analysis") if isinstance(deal.get("set_analysis"), list) else []
    return bool(nums) and (
        len(sets) != len(nums)
        or any(parse_money((entry or {}).get("potential_profit")
                           if isinstance(entry, dict) else None) is None
               for entry in sets))


def fee_cell(deal):
    """Buyer's premium and sales tax materially change landed cost on auction
    sources, so they are surfaced per row rather than buried inside
    `estimated_total`."""
    fb = deal.get("fee_breakdown") or {}
    premium = fb.get("premium_pct") or 0
    tax = fb.get("sales_tax_pct") or 0
    if not premium and not tax:
        return "—"
    parts = []
    if premium:
        pct = premium * 100
        parts.append(_to_fixed(pct, 1 if pct % 1 else 0) + "% BP"
                     + ("*" if fb.get("premium_is_default") else ""))
    if tax:
        pct = tax * 100
        parts.append(_TRAILING_ZEROS_RE.sub("", _to_fixed(pct, 2 if pct % 1 else 0))
                     + "% tax" + ("*" if fb.get("sales_tax_is_default") else ""))
    return " + ".join(parts)


def fee_amt(deal):
    fb = deal.get("fee_breakdown") or {}
    amount = (fb.get("premium_amount") or 0) + (fb.get("sales_tax_amount") or 0)
    return amount if amount else None


def ship_cell(deal):
    """$0.00 and "unknown" are different answers and must not render alike.

    A zero is real only on a listing that states free shipping or one Adam
    collects himself, and WHICH of those comes from `available_fulfillment`
    alone -- carried alongside as `fulfil` so the page can say "pickup" instead
    of a $0.00 that reads as free freight.
    """
    value = (deal.get("fee_breakdown") or {}).get("shipping_handling")
    return None if value is None else value


def row(deal, favorites, reg=registry.sources):
    cat = deal.get("listing_category")
    if cat not in ("bulk", "set", "minifigure", "excluded"):
        # Only pre-vocabulary rows reach here; the validator gates everything
        # written today. Keep the old two-way read so a legacy row still
        # renders rather than vanishing from the table.
        cat = "set" if cat == "set" else "bulk"
    scoring = deal.get("scoring") if isinstance(deal.get("scoring"), dict) else None
    fb = deal.get("fee_breakdown") or {}
    observations = deal.get("observations") if isinstance(deal.get("observations"), dict) else {}
    vision = observations.get("vision") if isinstance(observations.get("vision"), dict) else {}

    source = deal.get("source", UNDEFINED)
    seller_id = deal.get("seller_id")
    registry_entry = reg.entry(deal["listing_key"])

    out = {
        "key": deal.get("listing_key", UNDEFINED),
        "cat": cat,
        "title": deal.get("title") or "unknown",
        "url": deal.get("direct_url") or deal.get("url") or "",
        "source": registry_entry["short"],
        "status": deal.get("status", UNDEFINED),
        "contact": registry_entry["capability"]["can_offer"],
        "auc": is_bid_only_auction(deal),
        "ltype": listing_type(deal),
        "ends": short_ends(deal.get("auction_end_date")),

        # Scoring. `scored` distinguishes a row this scorer has actually seen
        # from one still carrying a frozen legacy number -- the two are not on
        # the same scale and must never rank against each other.
        "scored": scoring is not None,
        "score": (scoring.get("score", UNDEFINED) if scoring
                  else _first_not_none(deal.get("score", UNDEFINED))),
        "quality": _first_not_none(scoring.get("quality", UNDEFINED)) if scoring else None,
        "maxPrice": _first_not_none(scoring.get("max_price", UNDEFINED)) if scoring else None,
        "modelScore": _first_not_none(scoring.get("model_score", UNDEFINED)) if scoring else None,
        "divergence": _first_not_none(scoring.get("divergence", UNDEFINED)) if scoring else None,
        "divergenceFlag": bool(scoring.get("divergence_flag")) if scoring else False,
        "unscorable": _first_not_none(scoring.get("unscorable", UNDEFINED)) if scoring else None,
        "scoreBasis": _first_not_none(scoring.get("basis", UNDEFINED)) if scoring else None,
        "signals": _first_not_none(scoring.get("signals", UNDEFINED)) if scoring else None,
        "weightSource": _first_not_none(scoring.get("weight_source", UNDEFINED)) if scoring else None,
        "visionStatus": vision.get("status") or "not_observed",
        "targetColors": vision.get("target_colors") or None,

        # Money
        "total": _first_not_none(deal.get("estimated_total", UNDEFINED)),
        "hammer": _first_not_none(fb.get("hammer", UNDEFINED),
                                  deal.get("buy_now_price", UNDEFINED),
                                  deal.get("static_price", UNDEFINED),
                                  deal.get("current_price", UNDEFINED)),
        "ship": ship_cell(deal),
        "shipEst": bool(deal.get("shipping_estimated")),
        "fees": fee_cell(deal),
        "feeAmt": fee_amt(deal),
        "prem": _first_not_none(fb.get("premium_pct", UNDEFINED), 0),
        "tax": _first_not_none(fb.get("sales_tax_pct", UNDEFINED), 0),
        "premAmt": _first_not_none(fb.get("premium_amount", UNDEFINED), 0),
        "taxAmt": _first_not_none(fb.get("sales_tax_amount", UNDEFINED), 0),
        "premFix": _first_not_none(fb.get("premium_fixed", UNDEFINED), 0),
        "taxBasis": fb.get("tax_basis") or "hammer_plus_premium",
        "buyNow": bool(deal.get("buy_now_price")),
        "fulfil": fulfillment.label(deal),
        "weight": _first_not_none(deal.get("weight_lbs", UNDEFINED)),

        # Seller identity is a live join against the sellers table, never a
        # column on the deal row -- see ledger/sellers.py and `favorite_set()`.
        # The score bonus itself is NOT computed here: it is already baked into
        # `scoring.score` by legoscout-deal-scoring, so `sellerFavorite` only
        # drives the star and the row highlight, never a second score calc.
        #
        # `sellerSource` is the RAW canonical source (`deal["source"]`, e.g.
        # "shopgoodwill"), deliberately distinct from `source` above (the
        # registry's short display label). The sellers table is keyed on the
        # canonical value, so a favorite toggle must round-trip THIS, not the
        # display string.
        "sellerId": _first_not_none(seller_id),
        "sellerName": _first_not_none(deal.get("seller_name", UNDEFINED)),
        "sellerSource": source,
        "sellerFavorite": (source, seller_id) in favorites if seller_id else False,
    }

    if cat == "bulk":
        out["perLb"] = (deal["estimated_total"] / deal["weight_lbs"]
                        if deal.get("estimated_total") is not None
                        and deal.get("weight_lbs") else None)
        # eBay sold $/lb from `legoscout pricing comps --bulk` -- informational
        # only, per Decision A: never fed into `potential_profit` or the score.
        out["ebayPerLb"] = parse_money(deal.get("ebay_avg_price_per_lb"))
    elif cat == "minifigure":
        out["profit"] = parse_money(deal.get("potential_profit"))
        out["pinc"] = profit_incomplete(deal)
        # The canonical reader owns the field shape and all aggregate semantics.
        # In particular, counts are quantity sums and sold depth is the deepest
        # single identity market, never an ad-hoc sum in this display layer.
        analysis = minifig_analysis.entries(deal)
        if analysis:
            out["figCount"] = minifig_analysis.figure_count(analysis)
            out["identifiedCount"] = minifig_analysis.identified_count(analysis)
            out["unknownCount"] = minifig_analysis.unknown_count(analysis)
            out["minifigSubtotal"] = minifig_analysis.priced_subtotal(analysis)
            out["minifigSoldCount"] = minifig_analysis.sold_count(analysis)
            out["figSrc"] = ("detection" if deal.get("figure_count_source")
                             == "detection" else None)
            out["identificationComplete"] = (
                out["unknownCount"] == 0
                and all(entry.get("unit_value") is not None
                        and not entry.get("errors") for entry in analysis)
            )
            out["figures"] = [
                {
                    "figNo": entry.get("fig_no"),
                    "name": ((entry.get("catalog") or {}).get("name")
                             or "Unknown"),
                    "quantity": entry["quantity"],
                    "unitValue": entry.get("unit_value"),
                    "extendedValue": entry.get("extended_value"),
                    "soldCount": ((entry.get("used") or {})
                                  .get("price_detail_count")),
                    "conditionNotes": entry.get("condition_notes"),
                    "cropUrl": ("/crops/" + quote(
                        entry["representative_crop_ref"], safe="/")
                        if entry.get("representative_crop_ref") else None),
                    "status": (entry.get("verification") or {}).get("status"),
                    "nullValueReason": entry.get("null_value_reason"),
                    "errors": entry.get("errors") or [],
                }
                for entry in analysis
            ]
        else:
            # Positive reader-only compatibility branch. These values are never
            # selected for an identifier-backed row.
            out["figCount"] = (deal.get("figure_count")
                               if isinstance(deal.get("figure_count"), int) else None)
            out["perFig"] = parse_money(deal.get("ebay_avg_price_per_fig"))
            out["ebayCount"] = (deal.get("ebay_comp_count")
                                if isinstance(deal.get("ebay_comp_count"), int)
                                else None)
            out["zeroCompNote"] = (
                deal.get("zero_comp_note")
                if isinstance(deal.get("zero_comp_note"), str) else None)
            out["figSrc"] = (deal.get("figure_count_source")
                             if deal.get("figure_count_source") in
                             ("stated", "photo_count", "unknown") else None)
        # Same auction floor as a set: the profit is built on the current bid,
        # so show what Adam nets if he holds the line at Max Bid.
        out["profitAtMaxBid"] = (
            (out["profit"] + out["total"]) - out["maxPrice"]
            if (out["auc"] and out["profit"] is not None and out["total"] is not None
                and out["maxPrice"] is not None) else None)
    elif cat == "excluded":
        out["exclReason"] = (deal.get("exclusion_reason")
                             if isinstance(deal.get("exclusion_reason"), str) else None)
    else:
        out["nums"] = set_numbers_array(deal)
        out["cond"] = deal.get("set_condition") or "unknown"
        out["used"] = comp_value(deal, "used_avg_6mo")
        out["new"] = comp_value(deal, "new_avg_6mo")
        out["profit"] = parse_money(deal.get("potential_profit"))
        # eBay sold comps from `legoscout pricing comps` -- this lot-level SUM
        # stays informational, same as `used`/`new` (BrickLink). The actual
        # profit input is each entry's `blended_avg_sold_price` inside
        # `set_analysis`, a comp-count-weighted BrickLink+eBay average; see
        # `deal_schema.json`'s `ebay_avg_sold_price` and `build_record._apply_comps`.
        out["ebayAvg"] = parse_money(deal.get("ebay_avg_sold_price"))
        out["ebayCount"] = (deal.get("ebay_comp_count")
                            if isinstance(deal.get("ebay_comp_count"), int) else None)
        out["zeroCompNote"] = (deal.get("zero_comp_note")
                               if isinstance(deal.get("zero_comp_note"), str) else None)
        out["pinc"] = profit_incomplete(deal)
        out["cmpl"] = set_completeness(deal)

        # Bid-only auctions have no settled price -- `potential_profit` above was
        # computed against the CURRENT bid, a floor that will likely rise. Show
        # what Adam is guaranteed to net if he holds the line at his own
        # walk-away Max Bid: `scoring.max_price` is already denominated in LANDED
        # dollars (see legoscout-deal-scoring's `_score_set`,
        # `max_price = resale - $15`), so this is simply resale value minus that
        # ceiling -- which is exactly the deal-scoring skill's configured minimum
        # margin (`SET_MIN_PROFIT`, currently $15) for every set that clears
        # scoring, by design. It reads as a floor guarantee, not a per-listing
        # estimate: winning at or under Max Bid nets at least this; winning
        # below it nets more.
        out["profitAtMaxBid"] = (
            (out["profit"] + out["total"]) - out["maxPrice"]
            if (out["auc"] and out["profit"] is not None and out["total"] is not None
                and out["maxPrice"] is not None) else None)

    return {key: value for key, value in out.items() if value is not UNDEFINED}


def js_numbers(value, path="row"):
    """Render numbers the way `JSON.stringify` does.

    JavaScript has one number type, so `70.0` serializes as `70`. The page JS
    parses either spelling to the same Number, but the retired `legoscout display rows`
    IS the row contract, and a byte-for-byte diff against it is the only proof
    the port kept every value. A float that is exactly an integer therefore
    prints as one, below the 1e21 exponent-notation threshold.

    `nan` and `inf` are NOT numbers this can render. Python writes them as the
    bare tokens `NaN` and `Infinity`, which `JSON.parse` rejects, so one such
    value on one field took the whole page down at `await res.json()`. They are
    rejected here, named by field path, and the caller turns that into one
    broken row instead of a blank page.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                "%s is %r, which JSON.parse cannot read. Fix the number on the "
                "record; there is no rendering of it." % (path, value))
        return int(value) if value.is_integer() and abs(value) < 1e21 else value
    if isinstance(value, dict):
        return {key: js_numbers(item, "%s.%s" % (path, key))
                for key, item in value.items()}
    if isinstance(value, list):
        return [js_numbers(item, "%s[%d]" % (path, index))
                for index, item in enumerate(value)]
    return value


def broken_row(deal, exc):
    """The row that stands in for one that could not be built.

    This is blast-radius containment, NOT error suppression. Nothing is
    substituted for the value that failed: the row carries no price, no score
    and no fees, it says so in its own title, and it names the listing and the
    reason in `rowError` and on stderr. A single row with a string in
    `fee_breakdown.premium_pct` used to raise out of the list comprehension and
    return ZERO rows for the whole ledger -- 3 good rows lost to 1 bad one.

    `cat` and `status` are read straight off the record because the page's own
    filters key on them; a broken row that no filter can reach is a dropped row
    wearing a different name.
    """
    reason = "%s: %s" % (type(exc).__name__, exc)
    key = deal.get("listing_key")
    print("row FAILED for %s -- %s" % (key, reason), file=sys.stderr)
    cat = deal.get("listing_category")
    if cat not in ("bulk", "set", "minifigure", "excluded"):
        cat = "set" if cat == "set" else "bulk"
    return {
        "key": key,
        "cat": cat,
        "status": deal.get("status"),
        "title": "ROW FAILED TO BUILD -- %s" % reason,
        "url": "",
        "rowError": reason,
        "scored": False,
    }


def build_rows(active_only=False, path=None):
    """Every visible row, in ledger order. Read-only.

    One unrenderable record fails ONE row. Every other row still renders, and
    the failed one is reported in place, by key -- see `broken_row()`.
    """
    skip_status = ({"unavailable", "blocked", "rejected"} if active_only
                   else {"unavailable", "blocked"})
    favorites = sellers_db.favorite_set(path) if path else sellers_db.favorite_set()
    ledger = (ledger_db.load_document_readonly(path) if path
              else ledger_db.load_document_readonly())
    # `registry.sources` is a module-level singleton bound to the default
    # ledger path -- fine for every other caller, which always runs against
    # that path, but wrong here the moment `path` names a different database
    # (adam-server's deployed instance, or a test's scratch copy). A source
    # registry read against the wrong file doesn't return stale data, it
    # raises `FileNotFoundError` -- which is exactly what failed every row on
    # first deploy, 100% of the page, silently landing as "no results".
    reg = registry.Registry(path) if path else registry.sources
    out = []
    for deal in (ledger.get("deals") or []):
        if deal.get("status") in skip_status or not bidding_open(deal):
            continue
        try:
            out.append(js_numbers(row(deal, favorites, reg)))
        except Exception as exc:
            out.append(broken_row(deal, exc))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--active-only", action="store_true",
                    help="drop rejected rows as well as unavailable and blocked")
    ap.add_argument("--db", help="read a different ledger (a copy, for probes)")
    a = ap.parse_args()
    built = build_rows(a.active_only, a.db)
    failed = [{"listing_key": r["key"], "error": r["rowError"]}
              for r in built if "rowError" in r]
    # allow_nan=False: `NaN` and `Infinity` are Python-only tokens. Emitting one
    # is what broke `await res.json()` on the page, so this asserts the contract
    # rather than trusting it.
    print(json.dumps({"rows": built, "failed": failed}, allow_nan=False))
    # A page that is missing a row did not fully succeed.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
