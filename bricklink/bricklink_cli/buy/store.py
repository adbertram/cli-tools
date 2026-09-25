"""SQLite store for BrickLink buyer item index, idItem map, and lots."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

IDITEM_TTL_SECONDS = 14 * 24 * 3600
LOTS_TTL_SECONDS = 4 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_type TEXT NOT NULL,
    item_no TEXT NOT NULL,
    name TEXT,
    category_id INTEGER,
    PRIMARY KEY (item_type, item_no)
);
CREATE TABLE IF NOT EXISTS id_map (
    item_type TEXT NOT NULL,
    item_no TEXT NOT NULL,
    id_item INTEGER NOT NULL,
    resolved_at REAL NOT NULL,
    PRIMARY KEY (item_type, item_no)
);
CREATE TABLE IF NOT EXISTS lots (
    id_inv INTEGER PRIMARY KEY,
    id_item INTEGER NOT NULL,
    item_type TEXT NOT NULL,
    item_no TEXT NOT NULL,
    color_id INTEGER,
    color_name TEXT,
    condition_code TEXT,
    qty INTEGER,
    price_display TEXT,
    price_value REAL,
    currency TEXT,
    store_name TEXT,
    seller_username TEXT,
    seller_country_code TEXT,
    seller_feedback INTEGER,
    description TEXT,
    fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lots_item ON lots(item_type, item_no);
CREATE INDEX IF NOT EXISTS idx_lots_price ON lots(price_value);
CREATE INDEX IF NOT EXISTS idx_lots_color ON lots(color_id);
CREATE INDEX IF NOT EXISTS idx_lots_country ON lots(seller_country_code);
CREATE INDEX IF NOT EXISTS idx_lots_condition ON lots(condition_code);
CREATE INDEX IF NOT EXISTS idx_lots_store ON lots(store_name);
CREATE INDEX IF NOT EXISTS idx_lots_fetched ON lots(fetched_at);
CREATE TABLE IF NOT EXISTS price_guides (
    item_type TEXT NOT NULL,
    item_no TEXT NOT NULL,
    condition_code TEXT NOT NULL,
    guide_type TEXT NOT NULL,
    color_id INTEGER,
    currency TEXT,
    min_price REAL,
    max_price REAL,
    avg_price REAL,
    qty_avg_price REAL,
    unit_quantity INTEGER,
    total_quantity INTEGER,
    lower_pct REAL,
    lower_pct_price REAL,
    gap_abs REAL,
    gap_ratio REAL,
    country_summary TEXT,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (item_type, item_no, condition_code, guide_type, color_id)
);
CREATE INDEX IF NOT EXISTS idx_pg_gap ON price_guides(gap_ratio DESC);
CREATE INDEX IF NOT EXISTS idx_pg_type ON price_guides(item_type, item_no);
CREATE TABLE IF NOT EXISTS price_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type TEXT NOT NULL,
    item_no TEXT NOT NULL,
    condition_code TEXT NOT NULL,
    guide_type TEXT NOT NULL,
    color_id INTEGER,
    unit_price REAL NOT NULL,
    quantity INTEGER,
    shipping_available INTEGER,
    fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pd_item ON price_details(item_type, item_no, condition_code, guide_type);
CREATE INDEX IF NOT EXISTS idx_pd_price ON price_details(unit_price);
"""


def parse_price_display(display: str | None) -> tuple[Optional[float], Optional[str]]:
    if not display:
        return None, None
    cleaned = display.strip().replace(",", "")
    parts = cleaned.split()
    if not parts:
        return None, None
    if parts[0] in {"US", "CA", "AU"} and len(parts) >= 2:
        currency = {"US": "USD", "CA": "CAD", "AU": "AUD"}[parts[0]]
        try:
            return float(parts[1].lstrip("$")), currency
        except ValueError:
            return None, currency
    if len(parts) >= 2:
        try:
            return float(parts[1].lstrip("$")), parts[0]
        except ValueError:
            return None, parts[0]
    if cleaned.startswith("$"):
        try:
            return float(cleaned.lstrip("$")), "USD"
        except ValueError:
            return None, None
    return None, None


@dataclass
class LotRow:
    id_inv: int
    id_item: int
    item_type: str
    item_no: str
    color_id: Optional[int]
    color_name: Optional[str]
    condition_code: Optional[str]
    qty: Optional[int]
    price_display: Optional[str]
    price_value: Optional[float]
    currency: Optional[str]
    store_name: Optional[str]
    seller_username: Optional[str]
    seller_country_code: Optional[str]
    seller_feedback: Optional[int]
    description: Optional[str]
    fetched_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "id_inv": self.id_inv,
            "id_item": self.id_item,
            "item_type": self.item_type,
            "item_no": self.item_no,
            "color_id": self.color_id,
            "color_name": self.color_name,
            "condition": self.condition_code,
            "qty": self.qty,
            "price": self.price_display,
            "price_value": self.price_value,
            "currency": self.currency,
            "store": self.store_name,
            "seller": self.seller_username,
            "country": self.seller_country_code,
            "feedback": self.seller_feedback,
            "description": self.description,
            "fetched_at": self.fetched_at,
        }


class BuyStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(price_guides)").fetchall()}
            if "country_summary" not in cols:
                conn.execute("ALTER TABLE price_guides ADD COLUMN country_summary TEXT")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def item_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"])

    def list_items(
        self,
        *,
        item_type: str | None = None,
        category_id: int | None = None,
        item_no_prefix: str | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List catalog items from the local seed index. ``limit`` is required."""
        if limit is None or int(limit) < 1:
            raise ValueError("limit must be a positive integer")
        clauses: list[str] = []
        params: list[Any] = []
        if item_type:
            clauses.append("item_type=?")
            params.append(item_type.upper())
        if category_id is not None:
            clauses.append("category_id=?")
            params.append(int(category_id))
        if item_no_prefix:
            clauses.append("item_no LIKE ?")
            params.append(f"{item_no_prefix}%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([int(limit), int(offset)])
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT item_type, item_no, name, category_id FROM items"
                + where
                + " ORDER BY item_type, item_no LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [
            {
                "item_type": r["item_type"],
                "item_no": r["item_no"],
                "name": r["name"],
                "category_id": r["category_id"],
            }
            for r in rows
        ]


    def upsert_items(self, items: Sequence[dict[str, Any]]) -> int:
        if not items:
            return 0
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO items(item_type, item_no, name, category_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(item_type, item_no) DO UPDATE SET
                    name=excluded.name, category_id=excluded.category_id
                """,
                [
                    (str(it["item_type"]).upper(), str(it["item_no"]), it.get("name"), it.get("category_id"))
                    for it in items
                ],
            )
        return len(items)

    def get_id_item(self, item_type: str, item_no: str, *, now: float | None = None, ttl: int = IDITEM_TTL_SECONDS) -> Optional[int]:
        now = time.time() if now is None else now
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id_item, resolved_at FROM id_map WHERE item_type=? AND item_no=?",
                (item_type.upper(), item_no),
            ).fetchone()
        if row is None or now - float(row["resolved_at"]) > ttl:
            return None
        return int(row["id_item"])

    def put_id_item(self, item_type: str, item_no: str, id_item: int, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO id_map(item_type, item_no, id_item, resolved_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(item_type, item_no) DO UPDATE SET
                    id_item=excluded.id_item, resolved_at=excluded.resolved_at
                """,
                (item_type.upper(), item_no, int(id_item), now),
            )

    def lots_fresh(self, item_type: str, item_no: str, *, color_id: int | None = None, now: float | None = None, ttl: int = LOTS_TTL_SECONDS) -> bool:
        now = time.time() if now is None else now
        sql = "SELECT MAX(fetched_at) AS ts FROM lots WHERE item_type=? AND item_no=?"
        params: list[Any] = [item_type.upper(), item_no]
        if color_id is not None:
            sql += " AND color_id=?"; params.append(color_id)
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return row is not None and row["ts"] is not None and (now - float(row["ts"])) <= ttl

    def replace_lots_for_item(self, *, item_type: str, item_no: str, id_item: int, lots: Sequence[dict[str, Any]], color_id: int | None = None, now: float | None = None) -> int:
        now = time.time() if now is None else now
        item_type_u = item_type.upper()
        with self._connect() as conn:
            if color_id is None:
                conn.execute("DELETE FROM lots WHERE item_type=? AND item_no=?", (item_type_u, item_no))
            else:
                conn.execute("DELETE FROM lots WHERE item_type=? AND item_no=? AND color_id=?", (item_type_u, item_no, color_id))
            rows = []
            for lot in lots:
                price_display = lot.get("price_display")
                price_value, currency = parse_price_display(price_display)
                rows.append((
                    int(lot["id_inv"]), int(id_item), item_type_u, item_no,
                    lot.get("color_id"), lot.get("color_name"), lot.get("condition_code"),
                    lot.get("qty"), price_display, price_value, currency,
                    lot.get("store_name"), lot.get("seller_username"),
                    lot.get("seller_country_code"), lot.get("seller_feedback"),
                    lot.get("description"), now,
                ))
            conn.executemany(
                """
                INSERT OR REPLACE INTO lots(
                    id_inv, id_item, item_type, item_no, color_id, color_name,
                    condition_code, qty, price_display, price_value, currency,
                    store_name, seller_username, seller_country_code, seller_feedback,
                    description, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def query_lots(self, *, item_type: str | None = None, item_no: str | None = None, category_id: int | None = None, color_id: int | None = None, country: str | None = None, condition: str | None = None, max_price: float | None = None, min_qty: int | None = None, store: str | None = None, limit: int = 100) -> list[LotRow]:
        if limit is None or int(limit) < 1:
            raise ValueError("limit must be a positive integer")
        clauses: list[str] = []; params: list[Any] = []
        use_items_join = category_id is not None
        prefix = "lots." if use_items_join else ""
        if item_type: clauses.append(f"{prefix}item_type=?"); params.append(item_type.upper())
        if item_no: clauses.append(f"{prefix}item_no=?"); params.append(item_no)
        if category_id is not None: clauses.append("items.category_id=?"); params.append(int(category_id))
        if color_id is not None: clauses.append(f"{prefix}color_id=?"); params.append(color_id)
        if country: clauses.append(f"UPPER({prefix}seller_country_code)=?"); params.append(country.upper())
        if condition: clauses.append(f"UPPER({prefix}condition_code)=?"); params.append(condition.upper())
        if max_price is not None: clauses.append(f"{prefix}price_value IS NOT NULL AND {prefix}price_value <= ?"); params.append(max_price)
        if min_qty is not None: clauses.append(f"{prefix}qty IS NOT NULL AND {prefix}qty >= ?"); params.append(min_qty)
        if store: clauses.append(f"LOWER({prefix}store_name) LIKE ?"); params.append(f"%{store.lower()}%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(int(limit))
        if use_items_join:
            sql = (
                "SELECT lots.* FROM lots "
                "INNER JOIN items ON items.item_type = lots.item_type AND items.item_no = lots.item_no"
                + where
                + f" ORDER BY lots.price_value IS NULL, lots.price_value ASC, lots.qty DESC LIMIT ?"
            )
        else:
            sql = "SELECT * FROM lots" + where + " ORDER BY price_value IS NULL, price_value ASC, qty DESC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [LotRow(
            id_inv=int(r["id_inv"]), id_item=int(r["id_item"]), item_type=r["item_type"], item_no=r["item_no"],
            color_id=r["color_id"], color_name=r["color_name"], condition_code=r["condition_code"], qty=r["qty"],
            price_display=r["price_display"], price_value=r["price_value"], currency=r["currency"],
            store_name=r["store_name"], seller_username=r["seller_username"],
            seller_country_code=r["seller_country_code"], seller_feedback=r["seller_feedback"],
            description=r["description"], fetched_at=float(r["fetched_at"]),
        ) for r in rows]

    def replace_price_guide(
        self,
        *,
        item_type: str,
        item_no: str,
        condition_code: str,
        guide_type: str,
        color_id: int | None,
        currency: str | None,
        min_price: float | None,
        max_price: float | None,
        avg_price: float | None,
        qty_avg_price: float | None,
        unit_quantity: int | None,
        total_quantity: int | None,
        lower_pct: float,
        lower_pct_price: float | None,
        gap_abs: float | None,
        gap_ratio: float | None,
        details: Sequence[dict[str, Any]],
        country_summary: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> int:
        now = time.time() if now is None else now
        item_type_u = item_type.upper()
        cond = (condition_code or "A").upper()
        guide = (guide_type or "stock").lower()
        color_key = -1 if color_id is None else int(color_id)
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM price_details
                WHERE item_type=? AND item_no=? AND condition_code=? AND guide_type=?
                  AND IFNULL(color_id, -1)=?
                """,
                (item_type_u, item_no, cond, guide, color_key),
            )
            conn.execute(
                """
                INSERT INTO price_guides(
                    item_type, item_no, condition_code, guide_type, color_id, currency,
                    min_price, max_price, avg_price, qty_avg_price, unit_quantity, total_quantity,
                    lower_pct, lower_pct_price, gap_abs, gap_ratio, country_summary, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_type, item_no, condition_code, guide_type, color_id) DO UPDATE SET
                    currency=excluded.currency,
                    min_price=excluded.min_price,
                    max_price=excluded.max_price,
                    avg_price=excluded.avg_price,
                    qty_avg_price=excluded.qty_avg_price,
                    unit_quantity=excluded.unit_quantity,
                    total_quantity=excluded.total_quantity,
                    lower_pct=excluded.lower_pct,
                    lower_pct_price=excluded.lower_pct_price,
                    gap_abs=excluded.gap_abs,
                    gap_ratio=excluded.gap_ratio,
                    country_summary=excluded.country_summary,
                    fetched_at=excluded.fetched_at
                """,
                (
                    item_type_u, item_no, cond, guide, color_key, currency,
                    min_price, max_price, avg_price, qty_avg_price, unit_quantity, total_quantity,
                    float(lower_pct), lower_pct_price, gap_abs, gap_ratio,
                    (__import__("json").dumps(country_summary) if country_summary is not None else None),
                    now,
                ),
            )
            rows = []
            for d in details:
                rows.append((
                    item_type_u, item_no, cond, guide, color_key,
                    float(d["unit_price"]),
                    d.get("quantity"),
                    1 if d.get("shipping_available") else 0,
                    now,
                ))
            conn.executemany(
                """
                INSERT INTO price_details(
                    item_type, item_no, condition_code, guide_type, color_id,
                    unit_price, quantity, shipping_available, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def query_price_guides(
        self,
        *,
        item_type: str | None = None,
        item_no: str | None = None,
        condition_code: str | None = None,
        guide_type: str = "stock",
        min_gap_ratio: float | None = None,
        min_gap_abs: float | None = None,
        item_no_prefix: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit is None or int(limit) < 1:
            raise ValueError("limit must be a positive integer")
        clauses: list[str] = ["guide_type=?"]
        params: list[Any] = [(guide_type or "stock").lower()]
        if item_type:
            clauses.append("item_type=?"); params.append(item_type.upper())
        if item_no:
            clauses.append("item_no=?"); params.append(item_no)
        if condition_code:
            clauses.append("condition_code=?"); params.append(condition_code.upper())
        if item_no_prefix:
            clauses.append("item_no LIKE ?"); params.append(f"{item_no_prefix}%")
        if min_gap_ratio is not None:
            clauses.append("gap_ratio IS NOT NULL AND gap_ratio >= ?"); params.append(float(min_gap_ratio))
        if min_gap_abs is not None:
            clauses.append("gap_abs IS NOT NULL AND gap_abs >= ?"); params.append(float(min_gap_abs))
        where = " WHERE " + " AND ".join(clauses)
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM price_guides" + where +
                " ORDER BY gap_ratio IS NULL, gap_ratio DESC, lower_pct_price ASC LIMIT ?",
                params,
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("country_summary") is not None:
                d["country_summary_json"] = d["country_summary"]
            out.append(d)
        return out

