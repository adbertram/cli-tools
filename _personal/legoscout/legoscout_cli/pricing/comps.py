#!/usr/bin/env python3
"""The single comps lookup the comps-only appraiser calls.

SET mode prices every detected set number on the candidate -- ONE call per set,
looped here deterministically rather than by the calling agent, so a multi-set
listing is exactly as reliable as a single-set one. `sets` is ALWAYS an array,
even for the common one-set case: one shape, no singular/plural branch anywhere
downstream (`legoscout_cli.ledger.build_record._apply_comps` reads it the same
way regardless of length). Each entry merges BrickLink (`set_sales.summarize_set`,
comps-only -- no `--purchase-price`/`--fee-rate`) with eBay sold comps
(`ebay_comps.search_set_comps`) for that one set number. BrickLink and eBay are
independent lookups with independent failure modes -- BrickLink raises on a
genuine failure, eBay degrades to `{"available": false, ...}` on an auth lapse
(see `ebay_comps.py`'s module docstring) -- so one set's BrickLink failure, or
the eBay half of any set, never blocks pricing the others.

BULK mode has no BrickLink price guide at all (BrickLink is a set/part catalog,
not a by-weight one), so it calls only `ebay_comps.search_bulk_comps`, and there
is no multi-set concept -- a bulk lot is one undifferentiated mass, not N
detected items.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from . import ebay_comps
from . import set_sales


def _one_set(set_no: str, condition: str, description: str | None, limit: int) -> dict[str, Any]:
    try:
        bricklink = set_sales.summarize_set(set_no, condition)
    except set_sales.LookupNotFound as exc:
        bricklink = set_sales.build_not_found_result(
            set_no, condition, None, None, message=str(exc))
    except set_sales.LookupFailed as exc:
        bricklink = {"lookup_status": "failed", "set_no": set_no, "condition": condition,
                     "error": {"source": "bricklink catalog lookup", "message": str(exc)}}
    ebay = ebay_comps.search_set_comps(set_no, condition, description=description, limit=limit)
    return {"set_no": set_no, "bricklink": bricklink, "ebay": ebay}


def set_comps(set_numbers: list[str], condition: str, description: str | None = None,
              limit: int = 50) -> dict[str, Any]:
    """Price every set number in `set_numbers`, one `legoscout pricing comps`
    lookup per set. Never accepts an empty list -- a set candidate with zero
    detected set numbers is a classifier defect, not a comps decision.

    Never accepts a repeated set number either: `_apply_comps` divides
    `estimated_total` by `len(sets)` to allocate landed cost per set, but sums
    each entry's FULL resale comp into the record total -- a duplicate entry
    for the same set therefore double-counts that set's resale value while
    only fractionally allocating its cost, inflating `potential_profit`. A
    2026-08-20 review demonstrated an 85-dollar, 3.4x profit inflation from
    one repeated set number. The classifier runs text AND vision detection
    per set on a multi-set listing -- appending the same number from both
    passes without deduping is a realistic failure mode, not a hypothetical
    one.
    """
    if not set_numbers:
        raise ValueError("set_comps: set_numbers must be a non-empty list")
    duplicates = sorted({n for n in set_numbers if set_numbers.count(n) > 1})
    if duplicates:
        raise ValueError(
            "set_comps: set_numbers has duplicate entries: %s -- each set "
            "number must appear at most once, or its resale value is "
            "double-counted against a single fractional cost allocation"
            % ", ".join(duplicates))
    return {
        "mode": "set",
        "condition": condition,
        "sets": [_one_set(set_no, condition, description, limit) for set_no in set_numbers],
    }


def bulk_comps(description: str, dollars_per_lb: float | None = None,
               limit: int = 50) -> dict[str, Any]:
    ebay = ebay_comps.search_bulk_comps(description, dollars_per_lb=dollars_per_lb, limit=limit)
    return {"mode": "bulk", "bricklink": None, "ebay": ebay}


def minifigure_comps(description: str, limit: int = 50) -> dict[str, Any]:
    """eBay-only $/fig comps for a minifigure lot, mirroring bulk: no BrickLink
    price guide exists for an undifferentiated figure lot, so the search runs on
    keywords and extracts each matched listing's stated figure count."""
    ebay = ebay_comps.search_minifigure_comps(description, limit=limit)
    return {"mode": "minifigure", "bricklink": None, "ebay": ebay}


def excluded_comps(blocker: str) -> dict[str, Any]:
    """The classifier already excluded this candidate (book, hardware, non-brick
    item). Nothing to price; the blocker is the classifier's own reason."""
    return {"mode": "excluded", "blocked": True, "blocker": blocker}


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BrickLink + eBay sold comps for a LEGO set (or several, on one listing), "
                    "eBay-only for a bulk lot or a minifigure lot.")
    parser.add_argument("--set-no", action="append", dest="set_numbers", default=None,
                        help="A LEGO set number. Repeatable -- pass it once per detected set "
                             "on a multi-set listing. Required unless --bulk or --minifigure.")
    parser.add_argument("--bulk", action="store_true",
                        help="Bulk-lot mode: eBay $/lb comps only, no BrickLink.")
    parser.add_argument("--minifigure", action="store_true",
                        help="Minifigure-lot mode: eBay $/fig comps only, no BrickLink.")
    parser.add_argument("--condition", choices=["N", "U"], default=None,
                        help="N or U. Required unless --bulk or --minifigure.")
    parser.add_argument("--description", default=None,
                        help="Extra search keywords -- set name/theme, bulk lot description, "
                             "or minifigure theme/name.")
    parser.add_argument("--dollars-per-lb", type=float, default=None,
                        help="Bulk mode only: the target listing's own $/lb, for comparison.")
    parser.add_argument("--limit", type=int, default=50)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.bulk:
        if not args.description:
            return "--description is required in --bulk mode"
        result = bulk_comps(args.description, dollars_per_lb=args.dollars_per_lb, limit=args.limit)
    elif args.minifigure:
        if not args.description:
            return "--description is required in --minifigure mode"
        result = minifigure_comps(args.description, limit=args.limit)
    else:
        if not args.set_numbers or not args.condition:
            return "--set-no (repeatable) and --condition are required unless --bulk or --minifigure"
        result = set_comps(args.set_numbers, args.condition, description=args.description,
                           limit=args.limit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(None))
