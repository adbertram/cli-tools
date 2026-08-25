#!/usr/bin/env python3
"""Assemble one full-schema deal record from a crawl candidate and an appraisal.

This is the glue between the two Phase 4 agents: `legoscout-source-worker` produces a
crawl candidate (the `phase == "crawl"` fields in `deal_schema.json`), and
`legoscout-appraiser` produces an appraisal result (the `phase == "appraisal"` fields,
plus an `observations` object shaped like `legoscout-deal-scoring/references/
observation-contract.md`). Neither one ever writes `scoring` or any of the other
`phase == "synthesis"` fields -- this module is the only thing that does.

There is no second, caller-facing copy of a record. A 29-field `display` object used to
be built here and stored beside the real fields; it held 24% of the database and every
field it carried was either a restatement of a top-level column or a formatted string a
reader could format itself. Nothing read it that did not already fall back to the
top-level field on the same line. Deleted 2026-08-04. Read the columns.

Unknown keys on either input are dropped, the same way `ledger_db._deal_to_params` drops
anything not in `_COLUMNS`: a stray crawl-only field (`condition`, `lot_number`, ...)
must not leak into the ledger. That drop is silent, which is why a field a worker
already emits is invisible until the schema names it: workers emitted `seller_name` for
weeks and every one of those values was discarded here. It became a real `phase: "crawl"`
field on 2026-08-05 and now survives, because `CRAWL_FIELDS` is read from the schema.

    from build_deal_record import build_deal_record
    record = build_deal_record(candidate, appraisal,
                                first_seen_at="2026-08-04T12:00:00+00:00",
                                last_seen_at="2026-08-04T12:00:00+00:00")

Raises rather than guessing:
  - `available_fulfillment` missing or unreadable -- see `available_fulfillment.py`.
  - `listing_key` carrying an unregistered source namespace -- see `source_names.py`.
  - `shipping_estimate` present but not an object -- see `_require_shipping_estimate`.
  - `listing_category` not `bulk`/`set` -- see `score_deal.score_record`.
  - a quoted shipping estimate meeting a `fee_breakdown` that is missing, null,
    or carrying a non-numeric `hammer`/`premium_amount`/`sales_tax_amount` --
    see `_fee_line` and `_resolve_shipping`. Those three lines used to read
    `float(breakdown.get(...) or 0.0)`, which priced a missing item price at
    $0.00 and turned a $55.00 landed total into $10.00.

`source` is DERIVED, not copied. It is the `listing_key` namespace, always, because
the two are the same fact and a worker that spells one differently splits a source in
two. The human-readable label is resolved from the registry at render time.
"""
from __future__ import annotations

import math

from typing import Any

from . import fulfillment as af  # noqa: E402
from . import schema as deal_schema  # noqa: E402
from ..pricing import profit as profit_module  # noqa: E402
from ..scoring import score as score_deal  # noqa: E402
from . import sellers as sellers_db  # noqa: E402
from . import minifig_analysis as mfa  # noqa: E402
from . import set_analysis as sa  # noqa: E402
from . import shipping as se  # noqa: E402
from . import source_names  # noqa: E402
from ..orchestrator import (  # noqa: E402
    validate_appraisal_result,
    validate_comps_result,
    validate_identification_result,
)

CRAWL_FIELDS = tuple(deal_schema.fields_for_phase("crawl"))
APPRAISAL_FIELDS = tuple(deal_schema.fields_for_phase("appraisal"))

_UNKNOWN_STRING = "unknown"


def _pick(source: dict, fields: tuple) -> dict:
    return {k: source[k] for k in fields if k in source}


def _typed_default(field: str) -> Any:
    """The output_contract.md convention: `unknown` for strings, `null` for
    numbers, `[]` for arrays -- applied only to fields the two inputs left unset.

    A string field that the schema ALSO declares nullable takes `null`, not the
    sentinel. That is what the ledger already holds: all 1,991 rows without an
    `origin_zip` store NULL and not one stores 'unknown'. It also matters for
    `seller_id`/`seller_name`, where a null is read against the source's
    source module's `seller_id()` reader to tell "this marketplace has no seller"
    apart from "the worker did not read it" -- a sentinel string answers neither
    question and validate_deal_records would have to special-case it.
    """
    spec = deal_schema.load()["properties"][field]
    jtype = spec["type"]
    types = jtype if isinstance(jtype, list) else [jtype]
    if types[0] == "array":
        return []
    if types[0] == "string":
        return None if "null" in types else _UNKNOWN_STRING
    return None


def _fmt_money(value) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return _UNKNOWN_STRING
    return "$%.2f" % value


# The price `price_basis` names. Re-exported so `ledger_sweep` builds its landed
# cost from the same number this module prices from.
priced_amount = deal_schema.priced_amount


def _require_field_types(merged: dict) -> None:
    """Every assembled field must match `deal_schema.json`.

    This used to be `_require_scalar_types`, a hand-rolled re-implementation of
    JSON Schema type dispatch that read `spec["type"]` out of the schema and
    checked only that a scalar field was not a list or a dict. The schema itself
    was never executed. `deal_schema.validate` runs it, so `oneOf`, `const`,
    `required` and `additionalProperties` are enforced too -- which is what keeps
    a seventh invented `shipping_estimate` shape out of the ledger.

    The failure it exists to prevent: `ledger_db.SCALAR_FIELDS` become bare
    SQLite columns, so a list in one fails the whole `executemany` with `Error
    binding parameter 41: type 'list' is not supported` -- a column index, no
    field, no listing, and the entire ledger write aborts rather than one row.
    One appraiser batch in run 20260804T202546Z returned `risks_unknowns` as a
    list on 20 records.
    """
    deal_schema.validate(merged, fields=CRAWL_FIELDS + APPRAISAL_FIELDS)


def _fee_line(breakdown: dict, name: str, listing_key) -> float:
    """One numeric line off `fee_breakdown`, or a raise that names it.

    NEVER `float(breakdown.get(name) or 0.0)`. That spelling read a missing --
    or null, or `0`-equal -- fee line as $0.00 and rebuilt the landed total
    around it. A $45.00 lot quoting $10.00 of freight came back out as a $10.00
    landed total: the item price was simply gone. The row it produced looked
    populated and contradicted itself in public (`score 93 | total 10 | perLb 1
    | hammer 45`), `legoscout deals validate --strict` reported zero errors on
    it, and the score rose from 26 to 93 on a price that does not exist -- which
    puts the row at the top of the table Adam buys from. `premium_amount` and
    `sales_tax_amount` carried the same fallback and understate the same total
    the same silent way.

    A missing fee line is a defect in the appraisal artifact. It is not a zero,
    and a zero is what an appraiser writes when a source genuinely charges
    nothing -- `fees.landed_cost` emits `premium_amount: 0.0` and
    `sales_tax_amount: 0.0` on every no-premium, no-tax marketplace, so the two
    states are already distinguishable and there is nothing to guess.
    """
    if name not in breakdown:
        found = "absent"
    else:
        found = "%r" % (breakdown[name],)
    value = breakdown.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            "build_deal_record: %r quotes shipping from the source, so its landed "
            "total is rebuilt here -- but fee_breakdown.%s is %s, not a number. "
            "Rebuilding around it would price that line at $0.00 and understate "
            "the landed total by exactly the amount that is missing. Fix the "
            "appraisal artifact so every fee line it hands over is numeric."
            % (listing_key, name, found))
    return float(value)


def _buyer_protection_line(breakdown: dict, listing_key) -> float:
    """Return the stated buyer fee, or zero only on sources without that fee."""
    if "buyer_protection_fee" in breakdown:
        return _fee_line(breakdown, "buyer_protection_fee", listing_key)
    if source_names.namespace_of(listing_key or "") == "mercari":
        raise ValueError(
            "build_deal_record: %r has no numeric "
            "fee_breakdown.buyer_protection_fee. Mercari publishes it in "
            "priceSummary, and the landed total cannot omit it." % listing_key)
    return 0.0


def _resolve_shipping(merged: dict) -> None:
    """Fold the source's own quote into the landed cost, or refuse the record.

    ONE number, ONE place. `shipping_estimate` is what the marketplace published;
    `fee_breakdown.shipping_handling` is what the landed cost is built from, and
    it is the only one the deals page reads (`legoscout display rows`). Letting the
    appraiser retype the first into the second is how they came apart: the
    2026-08-03 ShopGoodwill crawl captured $18.23 for `shopgoodwill|272682584`
    and the stored landed cost stayed at the $29.99 item price.

    So the appraiser does not get to disagree. A quoted estimate DERIVES the
    freight line, and an appraisal that supplied a different number raises rather
    than being silently overwritten -- a mismatch means one of the two reads is
    wrong, and guessing which would hide it.
    """
    merged["shipping_estimate"] = se.normalize(merged.get("shipping_estimate"))
    quoted_total = se.total_of(merged)
    if quoted_total is None:
        return
    breakdown = merged.get("fee_breakdown")
    if not isinstance(breakdown, dict):
        # This used to `return`, which is the same defect as the `or 0.0` below
        # wearing a different coat: the source published a rate, and the quote
        # was dropped with no message at all. `validate.shipping_errors` calls
        # exactly that state an ERROR when it finds it in the ledger ("the quote
        # was dropped, so the landed total is a floor that did not have to be
        # one") -- it just could not see it here, because the record never
        # carried the freight line to disagree with.
        #
        # A `null` fee_breakdown is a legitimate state, and it stays one: 164
        # ledger rows hold it, and every one of them is a lot nobody priced.
        # What is NOT legitimate is a priced quote with nowhere to put it. The
        # two are told apart by the `quoted_total is None` return above, which
        # already left unpriced-and-unquoted records untouched.
        raise ValueError(
            "build_deal_record: %r carries a $%.2f shipping quote from the "
            "source but its fee_breakdown is %r, so there is no landed cost to "
            "fold that quote into. Price the lot before assembling it -- a "
            "record that reaches the deals page with the freight silently "
            "dropped shows Adam a landed total that is a floor it did not have "
            "to be." % (merged.get("listing_key"), quoted_total, breakdown))
    stated = breakdown.get("shipping_handling")
    if isinstance(stated, (int, float)) and not isinstance(stated, bool) \
            and abs(stated - quoted_total) > 0.005:
        raise ValueError(
            "build_deal_record: %r quotes $%.2f shipping from the source but the "
            "appraisal built its landed cost on $%.2f. One of the two reads is "
            "wrong -- fix the appraisal artifact rather than letting the deals "
            "page show a landed cost the source contradicts."
            % (merged.get("listing_key"), quoted_total, stated))
    breakdown["shipping_handling"] = quoted_total
    breakdown["shipping_unknown"] = False
    breakdown["landed_is_floor"] = False
    key = merged.get("listing_key")
    hammer = _fee_line(breakdown, "hammer", key)
    buyer_protection_fee = _buyer_protection_line(breakdown, key)
    breakdown["landed_total"] = round(
        hammer + _fee_line(breakdown, "premium_amount", key)
        + buyer_protection_fee
        + _fee_line(breakdown, "sales_tax_amount", key) + quoted_total, 2)
    # `if hammer else None` is a division guard, not a fallback: a zero-bid
    # auction has a real $0.00 hammer, and `landed / 0` is a ratio that does not
    # exist. `null` says that; a substituted number would not.
    breakdown["fee_multiple"] = round(breakdown["landed_total"] / hammer, 4) if hammer else None
    merged["estimated_total"] = breakdown["landed_total"]
    # `per_lb_price` is denominated in landed dollars, so it moves with the total
    # or the row contradicts itself on the page: $3.00/lb beside a $48.22 landed
    # cost on a 10 lb lot.
    weight = merged.get("weight_lbs")
    if isinstance(weight, (int, float)) and not isinstance(weight, bool) and weight:
        merged["per_lb_price"] = round(breakdown["landed_total"] / weight, 4)
        merged["per_lb_price_basis"] = "landed"


def _apply_price_override(merged: dict) -> None:
    """Move a description-contradicted crawl price to the seller's real ask.

    The classifier's `price_override` hand-off names the price a listing's OWN
    TEXT states when that text contradicts the crawl's captured price. Facebook
    is full of $1/$5 placeholder asks hiding real per-set prices in the body
    (facebook-2026-08-18-5); priced off the placeholder, such a row scores off
    money nobody is asking -- facebook|1024732190360342 scored 100 with
    +$112.52 of "profit" on a $5 phantom while its own description said "NOT 5
    DOLLARS" and listed five sets at prices summing to $200.

    Deterministic, and applied BEFORE any landed cost or score is computed:

    - `static_price` or `buy_now_price` moves to `price` when it is numeric,
      and `price_basis` follows the column moved.
    - `price` null means the classifier found NO usable ask in the text: the
      crawl price is contradicted and nothing replaces it, so the candidate
      has no cost basis at all. Per the ledger's numeric-price contract that
      listing is not recorded -- this raises, and the orchestrator drops the
      candidate rather than writing a priceless row.
    - Fixed asks only (`static_price` / `buy_now_price`). An auction's live
      hammer belongs to bidding, never to prose.
    """
    override = merged.get("price_override")
    if not isinstance(override, dict):
        return
    basis = merged.get("price_basis")
    columns = {
        "static_price": "static_price",
        "buy_now": "buy_now_price",
    }
    if basis not in columns:
        if basis == "unknown" and not any(
                isinstance(merged.get(c), (int, float))
                for c in ("static_price", "buy_now_price")):
            # The crawl captured no price anywhere; the override IS the ask.
            columns["unknown"] = "static_price"
            basis = "static_price"
        else:
            raise ValueError(
                "build_deal_record: %r carries a price_override but price_basis is "
                "%r. Overrides apply to fixed-price asks only ('static_price' or "
                "'buy_now'); an auction's hammer belongs to bidding, not to "
                "description prose." % (merged.get("listing_key"),
                                        merged.get("price_basis")))
    price = override.get("price")
    evidence = override.get("evidence")
    if isinstance(evidence, bool) or not isinstance(evidence, str) \
            or not evidence.strip() or not any(ch.isdigit() for ch in evidence):
        raise ValueError(
            "build_deal_record: %r carries a price_override whose evidence is "
            "%r. Evidence must quote the listing's own stated price(s) "
            "verbatim -- an unevidenced correction is an invented price."
            % (merged.get("listing_key"), evidence))

    if isinstance(price, bool) or not isinstance(price, (int, float)) \
            or not math.isfinite(price) or price < 0:
        # No usable ask in the listing text and a contradicted crawl price:
        # there is no cost basis to record. Not `rejected` -- the numeric-price
        # contract drops such listings outright.
        raise ValueError(
            "build_deal_record: %r carries a price_override with no usable "
            "price (%r) -- the listing text contradicts the crawl price of "
            "$%s without stating an ask of its own. The candidate has no cost "
            "basis; drop it from the run per the numeric-price contract."
            % (merged.get("listing_key"), price,
               merged.get(columns.get(basis, "static_price"))))
    merged[columns[basis]] = float(price)
    breakdown = merged.get("fee_breakdown")
    if isinstance(breakdown, dict):
        # The fee table rides ON the ask: premium, tax and landed_total were
        # computed from whatever hammer it carries. If that hammer names the
        # CONTRADICTED crawl price, the appraisal priced the phantom -- refuse
        # rather than quietly rescale percentages around it, and have the
        # classifier re-author landed cost off the stated ask (its own CLI
        # call, `pricing landed-cost --hammer <override price>`). Equal hammers
        # are the normal post-fix shape: the correction is already applied.
        hammer = breakdown.get("hammer")
        if isinstance(hammer, (int, float)) and not isinstance(hammer, bool) \
                and abs(float(hammer) - float(price)) > 0.005:
            raise ValueError(
                "build_deal_record: %r carries a price_override to $%s but its "
                "fee_breakdown.hammer is $%s -- the landed cost was authored "
                "on the contradicted crawl price. Re-author the appraisal's "
                "fee_breakdown against the stated ask "
                "(`legoscout pricing landed-cost --hammer %s ...`) instead of "
                "letting the record carry fees built from a price the listing "
                "text contradicts."
                % (merged.get("listing_key"), price, hammer, price))
        breakdown["hammer"] = round(float(price), 2)


def _require_semantically_valid(merged: dict) -> None:
    """Reject an assembled deal before a caller can persist it.

    `validate.check()` owns cross-field ledger rules. Calling it here prevents
    a caller from writing a record whose pickup eligibility or cost inputs
    contradict its source facts.
    """
    from . import validate as ledger_validate

    key, errors, _warns = ledger_validate.check(merged)
    if errors:
        raise ValueError(
            "build_deal_record: %s violates the ledger contract:\n  %s"
            % (key, "\n  ".join(errors)))


def _apply_comps(merged: dict, comps: dict | None, fee_rate: float | None) -> None:
    """Fold a comps-agent result into the merged record.

    `legoscout-appraiser` no longer produces classification, landed cost, or
    vision -- only comps, via `legoscout pricing comps`
    (`{"mode": "set", "sets": [{"set_no", "bricklink", "ebay"}, ...]}` for a
    set candidate -- one entry per DETECTED set number, always an array, even
    for the common single-set case; `{"mode": "bulk", "bricklink": None,
    "ebay": {...}}` for bulk). This is the ONE place that turns a comps result
    plus a classifier's landed cost into `potential_profit`, `used_avg_6mo`,
    `new_avg_6mo`, and `set_analysis` -- kept here rather than hand-merged by
    the orchestrator (a Claude agent) for the same reason `_resolve_shipping`
    exists: a model re-typing JSON is exactly how a landed cost and a shipping
    quote came apart on 2026-08-03, and how a `potential_profit_total` drifted
    $20.59 from the record's own `potential_profit` on
    `shopgoodwill|271135286` (see `set_analysis.py`).

    A multi-set listing allocates the landed cost EVENLY across every detected
    set number (no better per-set allocation evidence exists generically), and
    sums `used_avg_6mo`/`new_avg_6mo`/`potential_profit` across whichever sets
    priced -- matching the pre-split system's documented rule. A set that
    BrickLink could not confirm, or that lacks its selected condition's
    sold average, stays in `set_analysis` with null price/profit fields and
    contributes nothing to the sums; only the priced sets are summed, and the
    lot is marked `profit_incomplete` whenever any set could not be priced.

    `potential_profit` itself is priced off a comp-count-weighted BLEND of
    BrickLink's selected-condition average and eBay's same-condition average
    (`profit_module.blend_comp_average`), not BrickLink alone -- whichever
    source backs more sold comps pulls the number toward itself, and a set
    BrickLink cannot price but eBay can now prices off eBay rather than
    forcing a fabricated $0. `used_avg_6mo`/`new_avg_6mo` (BrickLink) and
    `ebay_avg_sold_price`/`ebay_comp_count` (eBay) stay pure, unblended
    lot-level sums of their own source -- the blended number lives only in
    each `set_analysis` entry's `blended_avg_sold_price`/`comp_basis`, so the
    derivation stays visible instead of silently overwriting an existing
    column.

    A SET candidate with no `comps` is a defect, not a quiet "no comps": nothing
    would have priced it, and `score_deal.score_record`'s comp-depth and theme
    multipliers both read `set_analysis` -- losing it changes the score with no
    error anywhere. This raises instead.

    A `blocked: true` comps result is the one deliberate exception: the
    classifier could never identify any set number for this candidate (text
    and vision both exhausted), so there was never a set for
    `legoscout pricing comps` to price. That is a real, scoreable "stays
    unpriced" outcome, not the defect the paragraph above raises on -- it
    lands in `zero_comp_note` the same way `legoscout-pricing`'s own
    "set # not in BrickLink" case already does, and marks
    `profit_incomplete` rather than raising.

    `fee_rate` is optional so `synthesis_coverage`'s dry-build (which proves the
    candidate/appraisal/comps triple BUILDS, not what its final price is) can
    validate a set record's shape without knowing the run's configured resale
    fee rate; the real ledger write always supplies it.
    """
    listing_category = merged.get("listing_category")
    if isinstance(comps, dict) and comps.get("blocked") is True:
        if listing_category == "set":
            merged["potential_profit"] = None
            merged["profit_incomplete"] = True
            merged["zero_comp_note"] = comps.get("blocker") or "unknown"

        # `excluded` candidates carry no economics at all -- `build_deal_record`
        # already routed them to `status: rejected` before this runs.
        return
    if comps is None:
        if listing_category == "set":
            raise ValueError(
                "build_deal_record: %r is a %s candidate with no comps result. "
                "Sets are priced by legoscout-appraiser's "
                "`legoscout pricing comps` call -- pass its result as `comps=`, "
                "or this record's pricing fields stay null with nothing "
                "telling you why."
                % (merged.get("listing_key"), listing_category.upper()))
        return

    ebay = comps.get("ebay")
    if isinstance(ebay, dict) and ebay.get("available"):
        merged["ebay_avg_sold_price"] = ebay.get("avg_sold_price")
        merged["ebay_comp_count"] = ebay.get("matched_count")
        merged["ebay_avg_price_per_lb"] = ebay.get("avg_price_per_lb")


    if listing_category != "set":
        return

    sets = comps.get("sets")
    if not isinstance(sets, list) or not sets:
        return

    n = len(sets)
    estimated_total = merged.get("estimated_total")
    allocated_cost = (estimated_total / n
                      if isinstance(estimated_total, (int, float)) and n else None)

    entries: list[dict] = []
    used_sum: float | None = None
    new_sum: float | None = None
    ebay_avg_sum: float | None = None
    ebay_count_sum = 0
    any_ebay_available = False
    profit_sum = 0.0
    any_priced = False
    any_unpriced = False
    any_zero_in_both = False

    for item in sets:
        bricklink = item.get("bricklink") if isinstance(item, dict) else None
        set_ebay = item.get("ebay") if isinstance(item, dict) else None

        if isinstance(set_ebay, dict) and set_ebay.get("available"):
            any_ebay_available = True
            avg = set_ebay.get("avg_sold_price")
            if isinstance(avg, (int, float)):
                ebay_avg_sum = (ebay_avg_sum or 0) + avg
            count = set_ebay.get("matched_count")
            if isinstance(count, int):
                ebay_count_sum += count

        if not isinstance(bricklink, dict) or bricklink.get("lookup_status") != "found":
            # Not identified in BrickLink -- keep the entry (Adam can see
            # WHICH set number failed), contribute nothing to the lot's price.
            if isinstance(bricklink, dict):
                entries.append(dict(bricklink))
            any_unpriced = True
            continue

        entry = dict(bricklink)
        used_avg = (bricklink.get("used") or {}).get("six_month_avg_sold_price")
        new_avg = (bricklink.get("new") or {}).get("six_month_avg_sold_price")
        if isinstance(used_avg, (int, float)):
            used_sum = (used_sum or 0) + used_avg
        if isinstance(new_avg, (int, float)):
            new_sum = (new_sum or 0) + new_avg

        if fee_rate is not None and allocated_cost is not None:
            # `purchase_price` on the entry is this set's ALLOCATED share of
            # landed cost -- not the raw item price, and not the whole lot's
            # cost on a multi-set listing. See legoscout-pricing/references/
            # set-listing-analysis.md's rule that `set_analysis.purchase_price`
            # must equal the cost the profit was actually computed against.
            entry["purchase_price"] = allocated_cost
            entry["fee_rate"] = fee_rate

            selected = bricklink.get("selected_condition_summary") or {}
            used_count = (bricklink.get("used") or {}).get("price_detail_count")
            new_count = (bricklink.get("new") or {}).get("price_detail_count")
            no_bricklink_evidence = used_count in (0, None) and new_count in (0, None)

            eb_available = isinstance(set_ebay, dict) and set_ebay.get("available") is True
            eb_avg = set_ebay.get("avg_sold_price") if eb_available else None
            eb_count = set_ebay.get("matched_count") if eb_available else None
            no_ebay_evidence = not profit_module.is_priced(eb_avg, eb_count)

            if no_bricklink_evidence and no_ebay_evidence:
                # BrickLink confirms this set exists but has ZERO sold comps in
                # BOTH conditions over the last 6 months, AND eBay has none
                # either -- no evidence of ANY resale demand from either
                # source, not the same as an unidentified set. Price this
                # set's resale at $0 (a real, scoreable loss) rather than
                # leaving it unpriced. See legoscout-pricing's <pricing_basis>.
                entry["potential_profit"] = -allocated_cost
                entry["blended_avg_sold_price"] = None
                entry["comp_basis"] = (
                    "bricklink: zero sold comps in both conditions; ebay: "
                    "zero sold comps -- priced at $0 loss, no market evidence")
                profit_sum += -allocated_cost
                any_priced = True
                any_zero_in_both = True
            else:
                # Blend BrickLink's selected-condition average with eBay's
                # same-condition average, weighted by comp count -- whichever
                # source backs more sold comps pulls the number toward itself.
                # A source with zero usable evidence contributes nothing, so
                # this naturally covers BrickLink-only (today's behavior),
                # eBay-only (a set BrickLink can't price but eBay can -- the
                # gap the both-conditions gate above used to force to $0), and
                # a true weighted blend when both have comps.
                blended = profit_module.blend_comp_average(
                    selected.get("six_month_avg_sold_price"),
                    selected.get("price_detail_count"),
                    eb_avg, eb_count)
                if blended["count"] > 0:
                    # blended["count"] > 0 guarantees is_priced() passes, so
                    # this is never the unpriced branch.
                    profit_result = profit_module.compute_potential_profit(
                        blended["avg"], blended["count"], allocated_cost, fee_rate)
                    entry["potential_profit"] = profit_result["potential_profit"]
                    entry["blended_avg_sold_price"] = blended["avg"]
                    entry["comp_basis"] = blended["basis"]
                    profit_sum += profit_result["potential_profit"]
                    any_priced = True
                else:
                    # This set's SELECTED condition has no BrickLink evidence,
                    # but the OTHER BrickLink condition does (so this isn't
                    # the zero-evidence-everywhere case above) and eBay has
                    # nothing either -- stays genuinely unpriced.
                    entry["potential_profit"] = None
                    entry["blended_avg_sold_price"] = None
                    entry["comp_basis"] = blended["basis"]
                    any_unpriced = True
        else:
            entry["potential_profit"] = None
            entry["blended_avg_sold_price"] = None
            entry["comp_basis"] = None
            any_unpriced = True

        entries.append(entry)

    if not entries:
        return

    merged["used_avg_6mo"] = used_sum
    merged["new_avg_6mo"] = new_sum
    if any_ebay_available:
        merged["ebay_avg_sold_price"] = round(ebay_avg_sum, 2) if ebay_avg_sum is not None else None
        merged["ebay_comp_count"] = ebay_count_sum

    # An incomplete set still gets its comps recorded for reference (Adam can
    # see what a complete one sells for), but never a computed profit --
    # BrickLink prices a COMPLETE set, so a number here would be fiction. The
    # scorer already gates on this (`_score_set` returns unscorable before
    # reading potential_profit at all), but the deals page reads the stored
    # value directly, so a fictional number here would still display as real.
    if merged.get("set_completeness") == "incomplete":
        for entry in entries:
            entry["potential_profit"] = None
        merged["potential_profit"] = None
        merged["profit_incomplete"] = True
        merged["set_analysis"] = sa.normalize(entries)
        return

    if fee_rate is not None:
        merged["potential_profit"] = round(profit_sum, 2) if any_priced else None
        # A zero-in-both-conditions $0 loss is a real number, but a weaker one
        # than an ordinary priced comp -- it rests on zero market evidence, not
        # a real average -- so it marks the lot incomplete too, matching the
        # single-set rule this generalizes.
        merged["profit_incomplete"] = any_unpriced or not any_priced or any_zero_in_both
        if any_zero_in_both:
            merged["zero_comp_note"] = (
                "one or more detected sets confirmed in BrickLink catalog but "
                "zero sold comps in both conditions and zero eBay sold comps "
                "over the last 6 months")

    merged["set_analysis"] = sa.normalize(entries)


def _apply_minifig_identification(
    merged: dict,
    identification: dict | None,
    fee_rate: float | None,
    vision: dict | None,
) -> None:
    category = merged.get("listing_category")
    if category != "minifigure":
        if identification is not None:
            raise ValueError(
                "build_deal_record: identification was supplied for a "
                "non-minifigure candidate")
        return
    if identification is None:
        raise ValueError(
            "build_deal_record: minifigure candidate has no identification "
            "result")
    validate_identification_result(
        identification, "build_deal_record identification")
    if identification.get("listing_key") != merged.get("listing_key"):
        raise ValueError(
            "build_deal_record: identification listing_key does not match "
            "candidate listing_key")
    if identification.get("blocked") is True:
        raise ValueError(
            "build_deal_record: identification is blocked: %s"
            % identification.get("blocker"))
    analysis = mfa.normalize(identification.get("minifig_analysis"))
    if not analysis:
        raise ValueError(
            "build_deal_record: identification has no minifig_analysis")

    merged["minifig_analysis"] = analysis
    count = mfa.figure_count(analysis)
    merged["figure_count"] = count
    merged["figure_count_source"] = "detection"
    subtotal = mfa.round_cents(mfa.priced_subtotal(analysis))
    complete = identification.get("pricing_complete") is True
    estimated_total = merged.get("estimated_total")
    if (fee_rate is not None
            and isinstance(estimated_total, (int, float))
            and not isinstance(estimated_total, bool)):
        merged["potential_profit"] = mfa.round_cents(
            subtotal * (1.0 - float(fee_rate)) - float(estimated_total))
    else:
        merged["potential_profit"] = None
    merged["profit_incomplete"] = not complete or fee_rate is None
    if not complete:
        merged["zero_comp_note"] = (
            "minifigure identification valuation is incomplete; "
            "potential_profit is the conservative known-value floor")

    if isinstance(vision, dict):
        vision["detection_figure_count"] = count
        stated = vision.get("stated_figure_count")
        photo = vision.get("photo_figure_count")
        if stated != count or photo != count:
            vision["figure_count_mismatch"] = {
                "stated": stated,
                "photo": photo,
                "detection": count,
            }


def build_deal_record(
    candidate: dict,
    appraisal: dict,
    *,
    first_seen_at: str,
    last_seen_at: str,
    status: str = "active",
    favorite_sellers: set[tuple[str, str]] | None = None,
    comps: dict | None = None,
    identification: dict | None = None,
    fee_rate: float | None = None,
) -> dict:
    """Assemble one deal record. `candidate` and `appraisal` may carry extra keys;
    only the fields `deal_schema.json` tags `crawl`/`appraisal` are read from them.

    `comps` is `legoscout-appraiser`'s per-candidate result
    (`legoscout pricing comps`'s shape) and `fee_rate` the configured resale fee
    rate; see `_apply_comps`. Both are optional for a bulk candidate, and
    `comps` is required for a set candidate. `identification` is required for
    every new minifigure candidate and forbidden on other categories."""
    if not isinstance(candidate, dict):
        raise ValueError(
            "build_deal_record: candidate must be an object, got %s"
            % type(candidate).__name__)
    if not isinstance(appraisal, dict):
        raise ValueError(
            "build_deal_record: appraisal must be an object, got %s"
            % type(appraisal).__name__)
    validate_appraisal_result(appraisal, "build_deal_record appraisal")
    if identification is not None and not isinstance(identification, dict):
        raise ValueError(
            "build_deal_record: identification must be an object or null")
    if comps is not None:
        # A 2026-08-20 review found this the ONE gap in the round-5 fix: the
        # duplicate-set_no guard lived in `pricing.comps.set_comps` (the CLI
        # generator) and `synthesis_coverage`'s dry-proof path, but not here
        # -- the actual production call the orchestrator's own SKILL.md
        # instructs it to make, and the one path `legoscout deals validate
        # --strict` (the mandated pre-write gate) never re-checks either.
        # Validating unconditionally here means the guard travels with the
        # computation regardless of how `comps` was assembled or which
        # caller reached this function.
        validate_comps_result(comps, "build_deal_record comps",
                              expected_category=appraisal.get("listing_category"))
    merged: dict[str, Any] = _pick(candidate, CRAWL_FIELDS)

    appraisal_observations = appraisal.get("observations") or {}
    vision = appraisal_observations.get("vision")
    if isinstance(vision, dict):
        vision = dict(vision)
    merged.update(_pick(appraisal, APPRAISAL_FIELDS))
    # Seed `observations` with the appraiser's own contribution so
    # `score_deal.build_observations` can fold it in alongside the text scan and vision.
    merged["observations"] = {
        k: v for k, v in appraisal_observations.items()
        if k in ("description", "model_score", "model_rationale")
    }

    for field in CRAWL_FIELDS + APPRAISAL_FIELDS:
        # Never defaulted: an absent/invalid value must reach `af.of()` below exactly as
        # given, so a genuinely missing answer raises `Undetermined` rather than getting
        # papered over as an empty (and therefore also-invalid, but wrongly-worded) list.
        if field == "available_fulfillment":
            continue
        if field not in merged:
            merged[field] = _typed_default(field)
    # The classifier's description-price correction runs FIRST: every downstream
    # number (landed cost, per-lb, profit, score) must be denominated in the
    # seller's real ask, never in a placeholder price the listing text
    # contradicts. See _apply_price_override.
    _apply_price_override(merged)
    # Normalize BEFORE the schema check, so a legacy artifact shape becomes
    # canonical rather than failing, and so `estimated_total` is final before
    # the scorer reads it. Both fields are owned by their own module -- an
    # appraiser that hands back the `{"sets": [...]}` wrapper or a bare per-set
    # object gets the canonical array, not a rejection.
    _resolve_shipping(merged)
    merged["set_analysis"] = sa.normalize(merged.get("set_analysis"))
    _apply_minifig_identification(merged, identification, fee_rate, vision)
    _apply_comps(merged, comps, fee_rate)
    _require_field_types(merged)

    # The classifier's exclusion gate: a book, a hardware item, a storage bin,
    # or any non-LEGO-piece listing must never appear as an active deal. Built
    # as `active` it RAISES -- the same raise-then-retry contract as the
    # pickup-radius gate -- so `synthesis_coverage` and the orchestrator rebuild
    # it as `rejected` and carry the reason into `notes`. The reason itself is
    # enforced by `validate._enum_errors` (non-empty on every excluded row).
    if merged.get("listing_category") == "excluded":
        if status != "rejected":
            raise ValueError(
                "classified as excluded: %r -- an excluded listing (book, "
                "hardware, non-brick item) can only be recorded with "
                "status: rejected, never active"
                % (merged.get("exclusion_reason") or "no reason given"))
        if isinstance(merged.get("exclusion_reason"), str) \
                and merged["exclusion_reason"].strip():
            merged["notes"] = "Excluded by classifier: %s" \
                % merged["exclusion_reason"].strip()

    if not merged.get("direct_url"):
        merged["direct_url"] = merged.get("url")

    # Never defaults to ["shipping"]: an unreadable fulfillment raises.
    merged["available_fulfillment"] = list(af.of(merged))

    # DERIVED, never copied from the candidate. `source` and the `listing_key`
    # prefix are the same fact; storing a second spelling of it is what let 1,989
    # rows hold a display name that no namespace query could ever match.
    canonical_source = source_names.canonical_for(merged.get("listing_key", ""))
    if canonical_source is None:
        raise ValueError(
            "build_deal_record: unregistered source namespace %r in listing_key %r "
            "-- register it with `legoscout sources add` before "
            "assembling this record" % (
                source_names.namespace_of(merged.get("listing_key", "")),
                merged.get("listing_key")))
    merged["source"] = canonical_source

    # A seller row only exists once a save() has upserted it, so this is a
    # no-op (False) for a seller's very first-ever sighting -- fine, since a
    # brand-new seller cannot already be favorited. On every later crawl of an
    # already-favorited seller, this is what gets the bonus applied at
    # creation instead of waiting for the next rescore sweep.
    seller_identity = (merged["source"], merged.get("seller_id"))
    if favorite_sellers is None:
        is_favorite_seller = bool(merged.get("seller_id")) and sellers_db.is_favorite(
            *seller_identity)
    else:
        is_favorite_seller = seller_identity in favorite_sellers

    scored = score_deal.score_record(merged, vision=vision, is_favorite_seller=is_favorite_seller)
    merged["scoring"] = scored["scoring"]
    merged["observations"] = scored["observations"]

    merged["id"] = merged["listing_key"]
    merged["status"] = status
    merged["last_status"] = status
    merged["first_seen_at"] = first_seen_at
    merged["last_seen_at"] = last_seen_at

    merged["score"] = merged["scoring"].get("score")
    merged["last_score"] = merged["score"]
    merged["quality_score"] = merged["scoring"].get("quality")
    merged["max_price"] = merged["scoring"].get("max_price")
    merged["model_score"] = merged["scoring"].get("model_score")

    merged["last_price"] = _fmt_money(priced_amount(merged))
    if merged.get("notes") in (None, _UNKNOWN_STRING):
        merged["notes"] = _UNKNOWN_STRING
    merged["prospect_id"] = candidate.get("prospect_id", appraisal.get("prospect_id"))
    merged["verification"] = None
    _require_semantically_valid(merged)

    return merged


if __name__ == "__main__":
    raise SystemExit(
        "build_deal_record.py is a library -- import build_deal_record() rather than "
        "running this file directly."
    )
