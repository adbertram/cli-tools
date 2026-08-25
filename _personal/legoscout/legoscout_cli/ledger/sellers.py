#!/usr/bin/env python3
"""Access layer for the sellers table inside the deal ledger database.

A seller is identified by `(source, seller_id)` -- `seller_id` is only unique
within one marketplace, so ShopGoodwill's seller 8 and eBay's seller 8 are two
different rows here. `ledger_db.save()` calls `upsert_seen_bulk()` after every
full-ledger write, so this table populates itself from every deal that carries
a `seller_id`; nothing else writes to it except a favorite toggle. A deal whose
source publishes no seller identity (Craigslist, StockX) never produces a row --
see the source's `seller_id()` reader, or its `NEEDS_PAGE_READ` note
(``legoscout sources``).

`is_favorite` carries no DDL default, the same convention `prospects_db.py`
uses for `status`/`state`: every insert sets it explicitly, so a default can
never quietly stand in for a value the caller forgot.

    legoscout sellers              # favorite count, total seller count
    legoscout sellers shopgoodwill 267022330   # one seller's row
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any

from . import db as ledger_db  # bare sibling import: this file sits next to ledger_db.py

DB_PATH = ledger_db.DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sellers (
    source TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    seller_name TEXT,
    is_favorite INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (source, seller_id)
);
CREATE INDEX IF NOT EXISTS idx_sellers_favorite ON sellers(is_favorite);
"""

# Every object _SCHEMA creates. sqlite_master is checked against this list
# before the script runs, so a database already at the current shape takes no
# write lock -- the same idempotent-connect pattern prospects_db.py uses.
_SCHEMA_OBJECTS: tuple[str, ...] = ("sellers", "idx_sellers_favorite")


class SellerError(ValueError):
    """A sellers-table write was refused.

    Deliberately loud: a favorite toggle against a seller nobody has crawled
    yet is a caller mistake, not something to paper over with a new row built
    from whatever scraps the caller happened to pass.
    """


def _ensure_sellers_schema(conn: sqlite3.Connection) -> None:
    """Create the table and its index if this database predates them.

    Idempotent -- runs on every connect, including against the live ledger.
    sqlite_master is read FIRST so a reader never takes a write lock for a
    migration it does not need; see the identical comment in prospects_db.py.
    """
    have = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    if all(name in have for name in _SCHEMA_OBJECTS):
        return
    conn.executescript(_SCHEMA)
    conn.commit()


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    """A ledger_db connection with the sellers schema guaranteed present."""
    conn = ledger_db.connect(path)
    _ensure_sellers_schema(conn)
    return conn


def _now() -> str:
    """UTC, ISO-8601, with the offset -- matches prospects_db._now()."""
    return datetime.now(timezone.utc).isoformat()


def upsert_seen_bulk(deals: list[dict[str, Any]], path: str = DB_PATH) -> int:
    """Record every seller named on `deals`. Returns how many rows were touched.

    One INSERT ... ON CONFLICT DO UPDATE per deal that carries a non-empty
    `seller_id`. `seller_name` and `last_seen_at` move to the newest value seen;
    `first_seen_at` is set only on the first sighting -- `excluded` is never
    read for it, so a later crawl can never push it forward.

    A deal with no `seller_id` is skipped outright: a null there means either
    an anonymous source (Craigslist, StockX) or a field the worker did not
    read, and neither case has an identity to key a row on.
    """
    conn = connect(path)
    touched = 0
    try:
        with conn:
            for deal in deals:
                seller_id = deal.get("seller_id")
                if not isinstance(seller_id, str) or not seller_id.strip():
                    continue
                source = deal.get("source")
                if not isinstance(source, str) or not source.strip():
                    continue
                seen_at = deal.get("last_seen_at") or deal.get("first_seen_at") or _now()
                conn.execute(
                    "INSERT INTO sellers "
                    "(source, seller_id, seller_name, is_favorite, first_seen_at, last_seen_at) "
                    "VALUES (?, ?, ?, 0, ?, ?) "
                    "ON CONFLICT(source, seller_id) DO UPDATE SET "
                    "  seller_name = excluded.seller_name, "
                    "  last_seen_at = excluded.last_seen_at",
                    (source, seller_id, deal.get("seller_name"), seen_at, seen_at),
                )
                touched += 1
    finally:
        conn.close()
    return touched


def set_favorite(source: str, seller_id: str, is_favorite: bool, path: str = DB_PATH) -> None:
    """Flip one seller's favorite flag. Raises `SellerError` if the seller has
    no row yet -- a seller must have appeared on at least one saved deal before
    it can be favorited; there is no silent creation from a favorite click."""
    if not isinstance(source, str) or not source.strip():
        raise SellerError("source must be a non-empty string, got %r" % (source,))
    if not isinstance(seller_id, str) or not seller_id.strip():
        raise SellerError("seller_id must be a non-empty string, got %r" % (seller_id,))
    if not isinstance(is_favorite, bool):
        raise SellerError("is_favorite must be a bool, got %r" % (is_favorite,))
    conn = connect(path)
    try:
        with conn:
            cur = conn.execute(
                "UPDATE sellers SET is_favorite = ? WHERE source = ? AND seller_id = ?",
                (int(is_favorite), source, seller_id),
            )
            if cur.rowcount == 0:
                raise SellerError(
                    "no seller %r/%r -- it must appear on at least one saved deal "
                    "(ledger_db.save() upserts sellers automatically) before it can "
                    "be favorited" % (source, seller_id))
    finally:
        conn.close()


def is_favorite(source: str, seller_id: str | None, path: str = DB_PATH) -> bool:
    """Whether one seller is favorited. `False` for a missing or null seller_id --
    there is nothing to have favorited."""
    if not seller_id:
        return False
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT is_favorite FROM sellers WHERE source = ? AND seller_id = ?",
            (source, seller_id),
        ).fetchone()
        return bool(row["is_favorite"]) if row is not None else False
    finally:
        conn.close()


def favorite_set(path: str = DB_PATH) -> set[tuple[str, str]]:
    """Every currently-favorited `(source, seller_id)` pair, for a bulk lookup
    during a full-ledger rescore -- one query instead of one per record."""
    conn = ledger_db.connect_readonly(path)
    try:
        return {
            (r["source"], r["seller_id"])
            for r in conn.execute("SELECT source, seller_id FROM sellers WHERE is_favorite = 1")
        }
    finally:
        conn.close()


def get_seller(source: str, seller_id: str, path: str = DB_PATH) -> dict[str, Any] | None:
    """One seller row, or None."""
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT * FROM sellers WHERE source = ? AND seller_id = ?",
            (source, seller_id),
        ).fetchone()
        return None if row is None else dict(row)
    finally:
        conn.close()


def summary(path: str = DB_PATH) -> dict[str, Any]:
    conn = connect(path)
    try:
        total = conn.execute("SELECT count(*) FROM sellers").fetchone()[0]
        favorites = conn.execute(
            "SELECT count(*) FROM sellers WHERE is_favorite = 1").fetchone()[0]
        return {"sellers": total, "favorites": favorites}
    finally:
        conn.close()


def main() -> int:
    if len(sys.argv) == 1:
        print(json.dumps(summary(), indent=1))
        return 0
    if len(sys.argv) != 3:
        sys.exit("usage: sellers_db.py [<source> <seller_id>]")
    row = get_seller(sys.argv[1], sys.argv[2])
    if row is None:
        sys.exit("sellers_db: no seller %r/%r" % (sys.argv[1], sys.argv[2]))
    print(json.dumps(row, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
