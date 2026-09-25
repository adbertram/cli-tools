"""Auto-seed the local item index from BrickBuddy on first use."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from .store import BuyStore
from .types import canonical_item_type

logger = logging.getLogger("bricklink.buy.seed")


class BrickBuddySeedError(RuntimeError):
    """Raised when BrickBuddy seeding fails."""


def _run_brickbuddy(args: list[str], *, runner: Callable[..., subprocess.CompletedProcess] | None = None) -> str:
    runner = runner or subprocess.run
    binary = shutil.which("brickbuddy")
    if not binary:
        raise BrickBuddySeedError(
            "brickbuddy CLI not found on PATH; cannot auto-seed the buy item index."
        )
    result = runner(
        [binary, *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BrickBuddySeedError(
            f"brickbuddy {' '.join(args)} failed ({result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()}"
        )
    return result.stdout or ""


def _parse_items_payload(raw: str) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]], int]:
    text = raw.strip()
    if not text:
        return [], None, 0
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BrickBuddySeedError(f"brickbuddy output is not JSON: {exc}") from exc

    pagination = None
    if isinstance(data, dict):
        meta = data.get("meta") or {}
        if isinstance(meta, dict) and isinstance(meta.get("pagination"), dict):
            pagination = meta["pagination"]
        if data.get("success") is False:
            err = (meta.get("error") if isinstance(meta, dict) else None) or data
            raise BrickBuddySeedError(f"brickbuddy API error: {err}")
        for key in ("items", "data", "results", "result"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
        else:
            rows = [data]
    elif isinstance(data, list):
        rows = data
    else:
        raise BrickBuddySeedError(f"Unexpected brickbuddy JSON type: {type(data).__name__}")

    raw_count = len(rows) if isinstance(rows, list) else 0
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_no = row.get("no") or row.get("number") or row.get("item_no") or row.get("itemNo")
        item_type = row.get("type") or row.get("item_type") or row.get("itemType")
        if not item_no or not item_type:
            continue
        try:
            canonical = canonical_item_type(str(item_type))
        except ValueError:
            continue
        parsed.append(
            {
                "item_type": canonical,
                "item_no": str(item_no),
                "name": row.get("name") or row.get("item_name"),
                "category_id": row.get("category_id") or row.get("categoryId") or row.get("cat_id"),
            }
        )
    return parsed, pagination, raw_count


def seed_items_from_brickbuddy(
    store: BuyStore,
    *,
    page_size: int = 500,
    max_pages: int = 10_000,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> int:
    """Paginate ``brickbuddy get /items`` into the local SQLite item index.

    BrickBuddy CLI pagination must ride on the URL query string
    (``/items?limit=&offset=``). ``-p`` JSON offsets are ignored by the API.

    Returns the number of rows upserted.
    """
    total = 0
    offset = 0
    page = 0
    total_items: Optional[int] = None
    while page < max_pages:
        page += 1
        qs = urlencode({"limit": page_size, "offset": offset})
        endpoint = f"/items?{qs}"
        raw = _run_brickbuddy(["get", endpoint], runner=runner)
        batch, pagination, raw_count = _parse_items_payload(raw)
        if pagination and total_items is None:
            raw_total = pagination.get("total_items")
            if raw_total is not None:
                total_items = int(raw_total)
        # Advance by API page size, not filtered row count (unknown types are skipped).
        if raw_count == 0:
            break
        if batch:
            total += store.upsert_items(batch)
        offset += raw_count
        logger.info(
            "BrickBuddy seed page %s: api=%s kept=%s (upserted=%s, offset=%s%s)",
            page,
            raw_count,
            len(batch),
            total,
            offset,
            f", total_items={total_items}" if total_items is not None else "",
        )
        if raw_count < page_size:
            break
        if total_items is not None and offset >= total_items:
            break
    logger.info("BrickBuddy seed finished: upserted %s item rows across %s page(s)", total, page)
    return total


def ensure_item_index(store: BuyStore, *, force: bool = False, **kwargs) -> int:
    """Seed from BrickBuddy when the local item index is empty (or force=True)."""
    if not force and store.item_count() > 0:
        return 0
    return seed_items_from_brickbuddy(store, **kwargs)
