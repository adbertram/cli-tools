"""Buyer marketplace orchestration: resolve idItem, fetch lots, query store."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from cli_tools_shared.data_cache import cached, invalidate

from ..config import get_config
from .http_client import BrickLinkBuyHttpClient
from .seed import ensure_item_index
from .store import BuyStore, LotRow
from .types import canonical_item_type, normalize_item_type
from .pricing import score_price_guide

logger = logging.getLogger("bricklink.buy.service")

IDITEM_CACHE_TTL = 14 * 24 * 3600
LOTS_CACHE_TTL = 4 * 3600


def _default_db_path() -> Path:
    config = get_config()
    storage = Path(getattr(config, "storage_dir", None) or Path.home() / ".local/share/cli-tools/bricklink")
    return Path(storage).parent / "buy" / "buy.sqlite3" if "authentication_profiles" in str(storage) else Path(storage) / "buy" / "buy.sqlite3"


def _default_cookie_jar() -> Path:
    config = get_config()
    storage = Path(getattr(config, "storage_dir", None) or Path.home() / ".local/share/cli-tools/bricklink")
    base = Path(storage).parent if "authentication_profiles" in str(storage) else Path(storage)
    return base / "buy" / "bricklink-cookies.txt"


def lot_from_ajax(row: dict[str, Any], *, id_item: int) -> dict[str, Any]:
    """Normalize a catalogifs list row into BuyStore lot dict keys."""
    return {
        "id_inv": int(row.get("idInv") or row.get("id_inv")),
        "id_item": id_item,
        "color_id": row.get("idColor", row.get("color_id")),
        "color_name": row.get("strColor") or row.get("color_name"),
        "condition_code": row.get("codeNew") or row.get("condition_code"),
        "qty": row.get("n4Qty", row.get("qty")),
        "price_display": row.get("mDisplaySalePrice") or row.get("price_display"),
        "store_name": row.get("strStorename") or row.get("store_name"),
        "seller_username": row.get("strSellerUsername") or row.get("seller_username"),
        "seller_country_code": row.get("strSellerCountryCode") or row.get("seller_country_code"),
        "seller_feedback": row.get("n4SellerFeedbackScore") or row.get("seller_feedback"),
        "description": row.get("strDesc") or row.get("description") or "",
    }


class BuyService:
    """High-level buy operations used by CLI commands."""

    def __init__(
        self,
        *,
        store: BuyStore | None = None,
        client: BrickLinkBuyHttpClient | None = None,
        db_path: Path | str | None = None,
    ):
        self.config = get_config()
        self.store = store or BuyStore(db_path or _default_db_path())
        self.client = client or BrickLinkBuyHttpClient(
            cookie_jar_path=str(_default_cookie_jar()),
        )

    def ensure_seeded(self) -> int:
        return ensure_item_index(self.store)

    @cached(ttl=IDITEM_CACHE_TTL)
    def resolve_id_item(self, item_type: str, item_no: str, *, force_refresh: bool = False) -> int:
        ajax_type = normalize_item_type(item_type)
        canonical = canonical_item_type(item_type)
        if not force_refresh:
            cached_id = self.store.get_id_item(canonical, item_no)
            if cached_id is not None:
                return cached_id

        payload = self.client.search_product(query=item_no, item_type=ajax_type)
        id_item = self._pick_id_item(payload, ajax_type=ajax_type, item_no=item_no)
        self.store.put_id_item(canonical, item_no, id_item)
        return id_item

    def _pick_id_item(self, payload: dict[str, Any], *, ajax_type: str, item_no: str) -> int:
        result = payload.get("result") or {}
        type_list = result.get("typeList") or result.get("type_list") or []
        candidates: list[dict[str, Any]] = []
        for bucket in type_list:
            if not isinstance(bucket, dict):
                continue
            btype = str(bucket.get("type") or "").upper()
            items = bucket.get("items") or []
            if btype and btype != ajax_type:
                continue
            for item in items:
                if isinstance(item, dict):
                    candidates.append(item)
        if not candidates:
            raise ValueError(f"No searchproduct matches for {ajax_type} {item_no}")

        item_no_u = item_no.upper()
        exact = [
            c for c in candidates
            if str(c.get("strItemNo") or c.get("strItemNo") or c.get("item_no") or "").upper() == item_no_u
        ]
        chosen = exact[0] if exact else candidates[0]
        raw_id = chosen.get("idItem") or chosen.get("id_item")
        if raw_id is None:
            raise ValueError(f"searchproduct match for {item_no} missing idItem")
        return int(raw_id)

    def fetch_lots(
        self,
        item_type: str,
        item_no: str,
        *,
        color_id: int | None = None,
        condition: str | None = None,
        force_refresh: bool = False,
        rpp: int = 500,
        max_lots: int | None = None,
    ) -> dict[str, Any]:
        self.ensure_seeded()
        canonical = canonical_item_type(item_type)
        display_limit = max_lots if max_lots is not None else 100_000
        if not force_refresh and self.store.lots_fresh(canonical, item_no, color_id=color_id):
            lots = self.store.query_lots(
                item_type=canonical, item_no=item_no, color_id=color_id, limit=display_limit
            )
            return {
                "item_type": canonical,
                "item_no": item_no,
                "id_item": lots[0].id_item if lots else self.store.get_id_item(canonical, item_no),
                "count": len(lots),
                "cached": True,
                "lots": [lot.as_dict() for lot in lots],
            }

        if force_refresh:
            invalidate(self, "resolve_id_item", item_type, item_no)

        id_item = self.resolve_id_item(item_type, item_no, force_refresh=force_refresh)
        all_lots: list[dict[str, Any]] = []
        page = 1
        total_count: int | None = None
        # Page size: do not request more than max_lots when capped.
        page_rpp = rpp
        if max_lots is not None and max_lots > 0:
            page_rpp = min(rpp, max_lots)
        while True:
            payload = self.client.catalogifs(
                item_id=id_item,
                page=page,
                rpp=page_rpp,
                color_id=color_id,
                condition=condition,
            )
            if total_count is None:
                total_count = int(payload.get("total_count") or payload.get("totalCount") or 0)
            rows = payload.get("list") or payload.get("lots") or []
            for row in rows:
                if isinstance(row, dict):
                    all_lots.append(lot_from_ajax(row, id_item=id_item))
                    if max_lots is not None and len(all_lots) >= max_lots:
                        break
            hit_cap = max_lots is not None and len(all_lots) >= max_lots
            if hit_cap or not rows or len(all_lots) >= (total_count or 0) or len(rows) < page_rpp:
                break
            page += 1

        if max_lots is not None:
            all_lots = all_lots[:max_lots]

        stored = self.store.replace_lots_for_item(
            item_type=canonical,
            item_no=item_no,
            id_item=id_item,
            lots=all_lots,
            color_id=color_id,
        )
        return {
            "item_type": canonical,
            "item_no": item_no,
            "id_item": id_item,
            "count": stored,
            "reported_total": total_count,
            "cached": False,
            "truncated": bool(max_lots is not None and (total_count or 0) > len(all_lots)),
            "lots": all_lots,
        }

    def list_lots(self, **filters) -> list[LotRow]:
        self.ensure_seeded()
        return self.store.query_lots(**filters)


    def list_items(
        self,
        *,
        item_type: str | None = None,
        category_id: int | None = None,
        item_no_prefix: str | None = None,
        limit: int,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self.ensure_seeded()
        canonical = canonical_item_type(item_type) if item_type else None
        return self.store.list_items(
            item_type=canonical,
            category_id=category_id,
            item_no_prefix=item_no_prefix,
            limit=limit,
            offset=offset,
        )

    def refresh_items(
        self,
        item_type: str,
        *,
        limit: int,
        category_id: int | None = None,
        item_no_prefix: str | None = None,
        color_id: int | None = None,
        condition: str | None = None,
        force_refresh: bool = False,
        offset: int = 0,
        max_lots: int | None = 50,
    ) -> dict[str, Any]:
        """Fetch lots for up to ``limit`` seeded items (optional type/category_id filter).

        ``limit`` is required and caps how many catalog items are processed.
        """
        if limit is None or int(limit) < 1:
            raise ValueError("limit must be a positive integer")
        self.ensure_seeded()
        canonical = canonical_item_type(item_type)
        items = self.store.list_items(
            item_type=canonical,
            category_id=category_id,
            item_no_prefix=item_no_prefix,
            limit=limit,
            offset=offset,
        )
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for idx, item in enumerate(items, start=1):
            item_no = item["item_no"]
            try:
                logger.info(
                    "item refresh %s/%s %s %s",
                    idx,
                    len(items),
                    canonical,
                    item_no,
                )
                result = self.fetch_lots(
                    canonical,
                    item_no,
                    color_id=color_id,
                    condition=condition,
                    force_refresh=force_refresh,
                    max_lots=max_lots,
                )
                results.append(
                    {
                        "item_type": canonical,
                        "item_no": item_no,
                        "id_item": result.get("id_item"),
                        "count": result.get("count"),
                        "cached": result.get("cached", False),
                    }
                )
            except Exception as exc:
                logger.warning("item refresh failed for %s %s: %s", canonical, item_no, exc)
                errors.append({"item_type": canonical, "item_no": item_no, "error": str(exc)})
        return {
            "item_type": canonical,
            "category_id": category_id,
            "limit": limit,
            "requested": len(items),
            "ok": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }

    def refresh_prices(
        self,
        item_type: str,
        *,
        limit: int,
        condition: str = "U",
        guide_type: str = "stock",
        percentile: float = 20.0,
        category_id: int | None = None,
        item_no_prefix: str | None = None,
        color_id: int | None = None,
        offset: int = 0,
        force_refresh: bool = False,
        ttl_seconds: int = 24 * 3600,
    ) -> dict[str, Any]:
        """Bulk-fetch OAuth price guides and score lower-percentile gaps vs avg."""
        if limit is None or int(limit) < 1:
            raise ValueError("limit must be a positive integer")
        self.ensure_seeded()
        canonical = canonical_item_type(item_type)
        items = self.store.list_items(
            item_type=canonical,
            category_id=category_id,
            item_no_prefix=item_no_prefix,
            limit=limit,
            offset=offset,
        )
        from ..client import get_client
        import time as _time

        client = get_client()
        ok = 0
        skipped = 0
        errors: list[dict[str, Any]] = []
        scored: list[dict[str, Any]] = []
        for idx, item in enumerate(items, start=1):
            item_no = item["item_no"]
            try:
                if not force_refresh:
                    existing = self.store.query_price_guides(
                        item_type=canonical,
                        item_no=item_no,
                        condition_code=condition,
                        guide_type=guide_type,
                        limit=1,
                    )
                    if existing and (_time.time() - float(existing[0].get("fetched_at") or 0)) <= ttl_seconds:
                        skipped += 1
                        scored.append({
                            "item_type": canonical,
                            "item_no": item_no,
                            "condition": condition,
                            "min_price": existing[0].get("min_price"),
                            "avg_price": existing[0].get("avg_price"),
                            "lower_pct": existing[0].get("lower_pct"),
                            "lower_pct_price": existing[0].get("lower_pct_price"),
                            "gap_abs": existing[0].get("gap_abs"),
                            "gap_ratio": existing[0].get("gap_ratio"),
                            "unit_quantity": existing[0].get("unit_quantity"),
                            "cached": True,
                        })
                        continue
                payload = client.get_price_guide(
                    item_type=canonical,
                    item_no=item_no,
                    color_id=color_id,
                    guide_type=guide_type if guide_type != "stock" else None,
                    condition=condition,
                )
                metrics = score_price_guide(payload, percentile=percentile)
                self.store.replace_price_guide(
                    item_type=canonical,
                    item_no=item_no,
                    condition_code=condition,
                    guide_type=guide_type,
                    color_id=color_id,
                    currency=metrics["currency"],
                    min_price=metrics["min_price"],
                    max_price=metrics["max_price"],
                    avg_price=metrics["avg_price"],
                    qty_avg_price=metrics["qty_avg_price"],
                    unit_quantity=metrics["unit_quantity"],
                    total_quantity=metrics["total_quantity"],
                    lower_pct=metrics["lower_pct"],
                    lower_pct_price=metrics["lower_pct_price"],
                    gap_abs=metrics["gap_abs"],
                    gap_ratio=metrics["gap_ratio"],
                    details=metrics["details"],
                )
                row = {
                    "item_type": canonical,
                    "item_no": item_no,
                    "condition": condition,
                    "min_price": metrics["min_price"],
                    "avg_price": metrics["avg_price"],
                    "lower_pct": metrics["lower_pct"],
                    "lower_pct_price": metrics["lower_pct_price"],
                    "gap_abs": metrics["gap_abs"],
                    "gap_ratio": metrics["gap_ratio"],
                    "unit_quantity": metrics["unit_quantity"],
                }
                scored.append(row)
                ok += 1
                if idx % 50 == 0:
                    logger.info("price refresh %s/%s ok=%s skipped=%s", idx, len(items), ok, skipped)
            except Exception as exc:
                logger.warning("price refresh failed for %s %s: %s", canonical, item_no, exc)
                errors.append({"item_type": canonical, "item_no": item_no, "error": str(exc)})
        scored.sort(key=lambda r: (r.get("gap_ratio") is None, -(r.get("gap_ratio") or 0)))
        return {
            "item_type": canonical,
            "condition": condition,
            "guide_type": guide_type,
            "percentile": percentile,
            "requested": len(items),
            "ok": ok,
            "skipped": skipped,
            "failed": len(errors),
            "results": scored,
            "errors": errors,
        }

    def list_price_gaps(self, **filters) -> list[dict[str, Any]]:
        self.ensure_seeded()
        if filters.get("item_type"):
            filters["item_type"] = canonical_item_type(filters["item_type"])
        return self.store.query_price_guides(**filters)

