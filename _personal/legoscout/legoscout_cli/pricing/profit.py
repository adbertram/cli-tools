#!/usr/bin/env python3
"""Net-of-fees profit math, extracted from `set_sales.summarize_set()`.

`potential_profit` is denominated in landed dollars:
`(avg_price * (1 - fee_rate)) - estimated_total`. `avg_price` comes from a comps
lookup and `estimated_total` from a landed-cost calc -- two different producers
under the split appraiser/classifier design, neither of which can compute this
alone. This module is the one place that does, so both `set_sales.py` (which has
both inputs when a caller passes `--purchase-price`/`--fee-rate`) and
`ledger/build_record.py` (which has them only after `_resolve_shipping` finalizes
`estimated_total`) call the same two functions rather than each re-deriving the
zero-comp guard.
"""
from __future__ import annotations

import argparse
import json
from typing import Any


def is_priced(avg_price: float | None, price_detail_count: int | None) -> bool:
    """Whether a comp average is real evidence, not BrickLink's "no sales" shape.

    BrickLink returns a fully-populated summary with avg 0.0 and
    `price_detail_count` 0 when a condition has NO sales in the window -- it does
    not return null. Scoring that as a real $0.00 comp makes profit come out as
    exactly minus the purchase price, which reads as a large loss and wrongly
    rejects the set.
    """
    return (
        avg_price is not None
        and not (avg_price == 0 and price_detail_count in (0, None))
    )


def net_profit(avg_price: float, estimated_total: float, fee_rate: float) -> float:
    """Resale net of the selling fee, less what the lot landed at."""
    return round((avg_price * (1 - fee_rate)) - estimated_total, 2)


def compute_potential_profit(
    avg_price: float | None,
    price_detail_count: int | None,
    estimated_total: float,
    fee_rate: float,
) -> dict[str, Any]:
    """`{"priced": bool, "potential_profit": float | None}` for one comp average.

    Does NOT implement the separate "zero comps in BOTH conditions" business
    rule (`potential_profit = -estimated_total`, `profit_incomplete: true`,
    `zero_comp_note` set) -- that depends on the used AND new summaries together,
    not the single selected-condition average this function receives, and stays
    the caller's decision. See `legoscout-pricing`'s `<pricing_basis>`.
    """
    priced = is_priced(avg_price, price_detail_count)
    return {
        "priced": priced,
        "potential_profit": net_profit(avg_price, estimated_total, fee_rate) if priced else None,
    }


def blend_comp_average(
    bricklink_avg: float | None,
    bricklink_count: int | None,
    ebay_avg: float | None,
    ebay_count: int | None,
) -> dict[str, Any]:
    """Comp-count-weighted average of BrickLink's (selected-condition) and eBay's
    sold averages for one set's ONE condition -- `legoscout pricing comps`
    always queries both sources at the same N/U condition, so this blends two
    same-condition numbers, never used against new or vice versa.

    Whichever source backs more sold comps pulls the blended number toward
    itself. A source with no usable evidence (per `is_priced`) contributes
    nothing, and the other source prices the set alone. A priced average
    whose count came back non-numeric gets a weight of 1 rather than being
    silently under-weighted to zero -- BrickLink's `avg_price` and
    `price_detail_count` are parsed from independent raw keys, so a real
    average with an unset count is rare but not structurally impossible.

    Returns `{"avg": None, "count": 0, "basis": ...}` only when NEITHER source
    has usable evidence. Rounds to cents here (not just for display) so the
    same number that displays as `blended_avg_sold_price` is the number that
    actually priced the set -- the exact drift class `set_analysis.py`'s own
    docstring warns about ($20.59 drift on `shopgoodwill|271135286`).
    """
    def _term(avg, count):
        if not is_priced(avg, count):
            return 0.0, 0
        weight = count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 1
        return float(avg) * weight, weight

    bl_weighted, bl_weight = _term(bricklink_avg, bricklink_count)
    eb_weighted, eb_weight = _term(ebay_avg, ebay_count)
    total_weight = bl_weight + eb_weight
    if total_weight == 0:
        return {"avg": None, "count": 0, "basis": "no usable comps from bricklink or ebay"}

    avg = round((bl_weighted + eb_weighted) / total_weight, 2)
    if bl_weight and eb_weight:
        basis = "bricklink (%d sold) + ebay (%d sold), comp-count-weighted average" % (bl_weight, eb_weight)
    elif bl_weight:
        basis = "bricklink only (%d sold) -- no usable ebay comps" % bl_weight
    else:
        basis = "ebay only (%d sold) -- no usable bricklink comps in this condition" % eb_weight
    return {"avg": avg, "count": total_weight, "basis": basis}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Net-of-fees profit from a comp average, landed cost, and fee rate."
    )
    parser.add_argument("--avg-price", type=float, default=None,
                        help="Selected-condition six-month avg sold price; omit for 'no comp'.")
    parser.add_argument("--price-detail-count", type=int, default=None,
                        help="How many sold listings backed --avg-price.")
    parser.add_argument("--estimated-total", type=float, required=True,
                        help="Landed cost.")
    parser.add_argument("--fee-rate", type=float, required=True,
                        help="Resale fee rate, as a decimal.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = compute_potential_profit(
        args.avg_price, args.price_detail_count, args.estimated_total, args.fee_rate)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(None))
