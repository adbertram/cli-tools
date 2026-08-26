#!/usr/bin/env python3
"""The canonical value of the ledger's `source` column, and the display label.

`deals.source` holds the **namespace** -- the same token that prefixes
`listing_key`, that `registry.py --active-namespaces` lists, and that every
skill prompt names. One key, one spelling, everywhere.

It used to hold the display name (`"Pallet Liquidation Warehouse"` against
`listing_key` `palletliquidation|4751`). That failed silently and expensively: a
source worker told "the ledger holds N `palletliquidation` deals" queries
`WHERE source='palletliquidation'`, gets zero rows, concludes the ledger is
empty for that source, and re-reports known records as new candidates -- while
skipping the mandatory per-run availability re-check on the existing ones. No
error, just an empty result set. All 1,989 rows were affected on 2026-08-04.

The display name is NOT stored. It is derived from the registry at render time
with `display_for()`, because a label that is written into every row is a label
that can drift out of the registry. `legoscout-display` already resolves its own
label through `legoscout_cli/display/rows.py`'s source label and never read this
column.

This module has no command of its own. `legoscout deals validate` runs `check()`
over every row; import the module from the tool's own interpreter to call
`report()` or `normalize()` against one namespace.
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache

from . import db as ledger_db

from ..sources import registry  # noqa: E402


# listing_key namespace -> the canonical `source` column value, which IS the
# namespace. This is a set of registered namespaces expressed as a dict so
# `check()` can tell "unregistered source" from "wrong spelling" in one lookup.
#
# Read once, on first USE -- not at import. `registry.sources.table()` opens
# the default ledger, and this module is imported deep in `legoscout_cli.main`'s
# chain (via `ledger.build_record`), so an eager read here required the
# DEFAULT ledger path to exist before argparse even ran `--db`. That broke
# `legoscout display serve --db <other ledger>` on any machine whose default
# path holds nothing -- exactly adam-server's deployed instance, which only
# ever has `shared/found_deals.db`, never the default path. Nothing in a run
# adds a source mid-flight, so caching after the first real access is exactly
# as fresh as caching at import, just without the eager I/O.
@lru_cache(maxsize=1)
def canonical_table() -> dict[str, str]:
    return {ns: ns for ns in sorted(registry.sources.table())}


# listing_key namespace -> human-readable label, read from the source
# registry (registry.py; the `sources` tables in found_deals.db). Used by
# renderers and reports. Never written into the ledger. Same lazy-once rule
# as `canonical_table()`.
@lru_cache(maxsize=1)
def display_table() -> dict[str, str]:
    return {ns: entry["display_name"] for ns, entry in sorted(registry.sources.table().items())}


def __getattr__(name: str):
    """`CANONICAL`/`DISPLAY` stay available as plain module attributes for
    existing callers (`source_names.DISPLAY[ns]`), resolved lazily through
    the cached functions above instead of running at import time."""
    if name == "CANONICAL":
        return canonical_table()
    if name == "DISPLAY":
        return display_table()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def namespace_of(listing_key: str) -> str:
    return listing_key.split("|", 1)[0] if "|" in listing_key else listing_key


def canonical_for(listing_key: str) -> str | None:
    """The `source` column value for a listing key, or None if unregistered."""
    return canonical_table().get(namespace_of(listing_key))


def display_for(listing_key: str) -> str | None:
    """The human-readable label for a listing key, or None if unregistered."""
    return display_table().get(namespace_of(listing_key))


def check(deal: dict) -> str | None:
    """Return a description of the problem, or None when the source name is correct."""
    lk = deal.get("listing_key", "")
    ns = namespace_of(lk)
    expected = canonical_table().get(ns)
    if expected is None:
        return (f"unregistered source namespace {ns!r} -- add it to "
                f"register it with `legoscout sources add`")
    actual = deal.get("source")
    if actual != expected:
        return (f"source {actual!r} should be the namespace {expected!r}; the "
                f"display name is derived at render time, never stored")
    return None


def report(namespace: str | None = None) -> list[dict]:
    doc = ledger_db.load_document()
    out = []
    for deal in doc["deals"]:
        ns = namespace_of(deal.get("listing_key", ""))
        if namespace and ns != namespace:
            continue
        problem = check(deal)
        if problem:
            out.append(
                {
                    "listing_key": deal["listing_key"],
                    "namespace": ns,
                    "current": deal.get("source"),
                    "canonical": canonical_table().get(ns),
                    "problem": problem,
                }
            )
    return out


def apply(namespace: str | None = None) -> dict:
    """Normalize `deals.source` to the namespace, transactionally via ledger_db.save().

    `display.source` is set to the registry's display name, so the stored payload
    stays human-readable for any reader that renders it straight.
    """
    doc = ledger_db.load_document()
    changed: dict[str, int] = {}
    unregistered: dict[str, int] = {}
    for deal in doc["deals"]:
        ns = namespace_of(deal.get("listing_key", ""))
        if namespace and ns != namespace:
            continue
        expected = canonical_table().get(ns)
        if expected is None:
            unregistered[ns] = unregistered.get(ns, 0) + 1
            continue
        if deal.get("source") != expected:
            key = f"{deal.get('source')!r} -> {expected!r}"
            changed[key] = changed.get(key, 0) + 1
            deal["source"] = expected
    if changed:
        ledger_db.save(doc)
    return {"applied": bool(changed), "changed": changed, "unregistered": unregistered}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write normalized names back")
    ap.add_argument("--namespace", help="limit to one listing_key namespace")
    a = ap.parse_args()

    if a.apply:
        print(json.dumps(apply(a.namespace), indent=2))
    else:
        problems = report(a.namespace)
        by_change: dict[str, int] = {}
        for p in problems:
            by_change[f"{p['current']!r} -> {p['canonical']!r}"] = (
                by_change.get(f"{p['current']!r} -> {p['canonical']!r}", 0) + 1
            )
        print(json.dumps({"drifted": len(problems), "changes": by_change}, indent=2))
        sys.exit(1 if problems else 0)
