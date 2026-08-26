#!/usr/bin/env python3
"""Compute per-source "last listing date" watermarks from the ledger.

Each source's watermark is the newest listing date the ledger already holds for
that source (keyed by listing_key namespace, e.g. `shopgoodwill`, `craigslist`).
LEGO Scout uses it to crawl newest-first and only pull listings *newer* than the
watermark, instead of re-scanning inventory it already has.

Per-deal listing date basis (best available):
  1. `posted_date`  when present and parseable (the real listed date) -> basis "posted_date"
  2. `first_seen_at` otherwise (crawl time, always present)           -> basis "first_seen_at"

The watermark for a source is the max best-date across its deals; the reported
`basis` and `newest_listing_key` come from that max deal.

Usage:
    legoscout sources watermarks            # read-only; print per-namespace watermark JSON
    legoscout sources watermarks --apply    # also write the `source_watermarks` block
                                            # (and bump schema_version) back to the ledger
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

from . import db as ledger_db

LEDGER = ledger_db.DB_PATH
SCHEMA_VERSION = 5
UNKNOWN_DATE_VALUES = {"", "unknown", "not-an-auction", "n/a", "none", "null"}


def namespace(listing_key: str) -> str:
    return (listing_key or "").split("|", 1)[0].lower()


def parse_dt(value: str | None) -> datetime | None:
    """Parse a date-only (YYYY-MM-DD) or ISO-8601 datetime into an aware UTC datetime."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in UNKNOWN_DATE_VALUES:
        return None
    iso = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
        if not m:
            return None
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def deal_best_date(deal: dict[str, Any]) -> tuple[datetime, str] | None:
    """Return (best_date, basis) for a deal, preferring real posted_date."""
    posted = parse_dt(deal.get("posted_date"))
    if posted is not None:
        return posted, "posted_date"
    seen = parse_dt(deal.get("first_seen_at"))
    if seen is not None:
        return seen, "first_seen_at"
    return None


def active_namespaces() -> list[str]:
    """Every source the registry calls active, read through the registry."""
    from ..sources import registry

    return registry.active_namespaces()


def compute_watermarks(ledger: dict[str, Any],
                       namespaces: list[str] | None = None
                       ) -> dict[str, dict[str, Any]]:
    """A watermark row for every ACTIVE source, plus every source with a deal.

    The namespace list used to be derived from the deals alone, so a registered
    source the ledger holds nothing for produced no row at all. An orchestrator
    reading the watermarks then had nothing to bound that source's crawl with,
    and Nextdoor and StockX crawled unbounded on 2026-08-06. A source with no
    deal answers `last_listing_date: null`, which is the instruction to crawl
    from the beginning -- it is not the same as saying nothing.

    `namespaces` is a parameter so a caller can compute against a stated list
    rather than the live registry.
    """
    best: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {ns: 0 for ns in (
        active_namespaces() if namespaces is None else namespaces)}
    for deal in ledger.get("deals", []):
        key = deal.get("listing_key")
        if not key:
            continue
        ns = namespace(key)
        counts[ns] = counts.get(ns, 0) + 1
        resolved = deal_best_date(deal)
        if resolved is None:
            continue
        best_date, basis = resolved
        current = best.get(ns)
        if current is None or best_date > current["_dt"]:
            best[ns] = {
                "_dt": best_date,
                "last_listing_date": best_date.isoformat(),
                "basis": basis,
                "newest_listing_key": key,
            }
    watermarks: dict[str, dict[str, Any]] = {}
    for ns in sorted(counts):
        entry = best.get(ns)
        if entry is None:
            watermarks[ns] = {
                "last_listing_date": None,
                "basis": "none",
                "newest_listing_key": None,
                "deal_count": counts[ns],
            }
        else:
            watermarks[ns] = {
                "last_listing_date": entry["last_listing_date"],
                "basis": entry["basis"],
                "newest_listing_key": entry["newest_listing_key"],
                "deal_count": counts[ns],
            }
    return watermarks


def apply_watermarks(ledger: dict[str, Any], watermarks: dict[str, dict[str, Any]], now: datetime) -> None:
    now_iso = now.isoformat()
    stamped = {ns: {**data, "updated_at": now_iso} for ns, data in watermarks.items()}
    ledger["source_watermarks"] = stamped
    ledger["schema_version"] = SCHEMA_VERSION
    ledger["updated_at"] = now_iso
    contract = ledger.get("ledger_contract")
    if isinstance(contract, dict):
        fields = contract.get("required_top_level_fields")
        if isinstance(fields, list) and "source_watermarks" not in fields:
            fields.append("source_watermarks")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the source_watermarks block (and bump schema_version) back to the ledger",
    )
    args = parser.parse_args()

    ledger = ledger_db.load_document()
    watermarks = compute_watermarks(ledger)

    if args.apply:
        now = datetime.now(timezone.utc)
        apply_watermarks(ledger, watermarks, now)
        ledger_db.save(ledger)

    json.dump(watermarks, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
