#!/usr/bin/env python3
"""One-time backfill: seed the sellers table from deal history already in the ledger.

`ledger_db.save()` upserts a seller row automatically on every write going
forward, but that started only once the sellers table existed -- every deal
saved before today never touched it. This reads every distinct
`(source, seller_id)` already in `deals` and writes one row per seller,
carrying the EARLIEST `first_seen_at` and the LATEST `last_seen_at` across all
of that seller's deals, plus the `seller_name` from the most-recently-seen one.

Run with --dry-run first.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


from . import db as ledger_db  # noqa: E402
from . import sellers as sellers_db  # noqa: E402


def _distinct_sellers(path: str) -> dict[tuple[str, str], dict[str, Any]]:
    """One entry per `(source, seller_id)`: earliest `first_seen_at`, latest
    `last_seen_at`, and the `seller_name` off the most-recently-seen row."""
    rows = ledger_db.query(
        "SELECT source, seller_id, seller_name, first_seen_at, last_seen_at "
        "FROM deals WHERE seller_id IS NOT NULL AND seller_id != ''",
        path=path,
    )
    sellers: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        source, seller_id = row["source"], row["seller_id"]
        # A deal missing `source` cannot be keyed -- see build_deal_record.py,
        # which always derives it, so this only guards a pre-derivation row.
        if not source:
            continue
        key = (source, seller_id)
        entry = sellers.setdefault(key, {
            "source": source,
            "seller_id": seller_id,
            "seller_name": row["seller_name"],
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
        })
        if row["first_seen_at"] and (
                not entry["first_seen_at"] or row["first_seen_at"] < entry["first_seen_at"]):
            entry["first_seen_at"] = row["first_seen_at"]
        if row["last_seen_at"] and (
                not entry["last_seen_at"] or row["last_seen_at"] > entry["last_seen_at"]):
            entry["last_seen_at"] = row["last_seen_at"]
            entry["seller_name"] = row["seller_name"]
    return sellers


def backfill(apply: bool, path: str = sellers_db.DB_PATH) -> dict[str, Any]:
    sellers = _distinct_sellers(path)
    if not apply:
        return {"applied": False, "sellers_found": len(sellers)}

    # Pass 1 establishes first_seen_at. upsert_seen_bulk's INSERT branch
    # stamps both columns from whichever of last_seen_at/first_seen_at it is
    # handed, so this pass hands it ONLY first_seen_at.
    seed = [
        {"source": s["source"], "seller_id": s["seller_id"], "seller_name": None,
         "first_seen_at": s["first_seen_at"]}
        for s in sellers.values()
    ]
    sellers_db.upsert_seen_bulk(seed, path=path)

    # Pass 2 carries the real seller_name and the LATEST last_seen_at. Every
    # row from pass 1 already exists, so this always takes the ON CONFLICT
    # branch, which touches only seller_name/last_seen_at -- first_seen_at
    # from pass 1 survives untouched.
    update = [
        {"source": s["source"], "seller_id": s["seller_id"], "seller_name": s["seller_name"],
         "last_seen_at": s["last_seen_at"]}
        for s in sellers.values()
    ]
    touched = sellers_db.upsert_seen_bulk(update, path=path)
    return {"applied": True, "sellers_found": len(sellers), "sellers_written": touched}


def main() -> int:
    """The argparse surface, lifted out of the `__main__` guard so the CLI can
    reach it. A guarded block never runs on import, so the ported module had no
    entry point at all."""
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the sellers table")
    parser.add_argument("--dry-run", action="store_true", help="report only (default)")
    parser.add_argument("--db", default=sellers_db.DB_PATH, help="ledger path (tests)")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("--apply and --dry-run are mutually exclusive")
    print(json.dumps(backfill(apply=args.apply, path=args.db), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
