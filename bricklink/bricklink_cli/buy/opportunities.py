"""Opportunity shortlist + paced live-lot deepen (country/store)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from .pricing import (
    DEFAULT_SHIPPING_ESTIMATE,
    opportunity_score,
    score_price_guide,
    sold_country_summary,
)
from .include import attach_sellers, parse_include
from .types import canonical_item_type

logger = logging.getLogger("bricklink.buy.opportunities")


def build_opportunity_row(
    stock: dict[str, Any],
    sold: dict[str, Any] | None,
    *,
    shipping_estimate: float = DEFAULT_SHIPPING_ESTIMATE,
) -> dict[str, Any]:
    buy_proxy = stock.get("lower_pct_price")
    sell_proxy = None
    sold_avg = None
    sold_countries = None
    sell_proxy_source = None
    if sold:
        sold_avg = sold.get("avg_price")
        sell_proxy = sold_avg
        sell_proxy_source = "sold_avg"
        # country mix stored as JSON in a side channel when present
        raw = sold.get("country_summary_json") or sold.get("country_summary")
        if raw:
            try:
                sold_countries = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                sold_countries = None
    # Do NOT fall back to stock (for-sale) average — that is ask price, not
    # last-6-months sold avg, and massively overstates flip opportunity.
    opp = opportunity_score(
        buy_proxy=buy_proxy,
        sell_proxy=sell_proxy,
        shipping_estimate=shipping_estimate,
    )
    return {
        "item_type": stock.get("item_type"),
        "item_no": stock.get("item_no"),
        "condition_code": stock.get("condition_code"),
        "buy_proxy": buy_proxy,
        "landed_buy": opp.get("landed_buy"),
        "shipping_estimate": shipping_estimate,
        "stock_avg": stock.get("avg_price"),
        "stock_gap_ratio": stock.get("gap_ratio"),
        "sold_avg": sold_avg,
        "sell_proxy": sell_proxy,
        "sell_proxy_source": sell_proxy_source,
        "opportunity_abs": opp["opportunity_abs"],
        "opportunity_ratio": opp["opportunity_ratio"],
        "unit_quantity": stock.get("unit_quantity"),
        "sold_countries": sold_countries,
    }


class OpportunityService:
    """Depends on BuyService for store/client/fetch_lots."""

    def __init__(self, buy_service):
        self.buy = buy_service

    def list_opportunities(
        self,
        *,
        item_type: str | None = None,
        condition: str = "U",
        min_gap_ratio: float | None = None,
        min_opportunity_ratio: float | None = None,
        item_no_prefix: str | None = None,
        limit: int = 50,
        include: str | None = None,
        seller_lot_limit: int = 10,
        shipping_estimate: float = DEFAULT_SHIPPING_ESTIMATE,
        country: str | None = None,
        require_sold: bool = True,
    ) -> list[dict[str, Any]]:
        stocks = self.buy.list_price_gaps(
            item_type=item_type,
            condition_code=condition,
            guide_type="stock",
            min_gap_ratio=min_gap_ratio,
            item_no_prefix=item_no_prefix,
            limit=max(limit * 5, limit),  # over-fetch then filter by opportunity
        )
        rows: list[dict[str, Any]] = []
        for stock in stocks:
            sold_rows = self.buy.store.query_price_guides(
                item_type=stock["item_type"],
                item_no=stock["item_no"],
                condition_code=condition,
                guide_type="sold",
                limit=1,
            )
            sold = sold_rows[0] if sold_rows else None
            row = build_opportunity_row(stock, sold, shipping_estimate=shipping_estimate)
            if require_sold and sold is None:
                continue
            if min_opportunity_ratio is not None:
                ratio = row.get("opportunity_ratio")
                if ratio is None or ratio < min_opportunity_ratio:
                    continue
            rows.append(row)
        rows.sort(key=lambda r: (r.get("opportunity_ratio") is None, -(r.get("opportunity_ratio") or 0)))
        trimmed = rows[:limit]
        flags = parse_include(include)
        if "sellers" in flags:
            return attach_sellers(
                trimmed,
                self.buy.store,
                condition=condition,
                max_lots=seller_lot_limit,
                shipping_estimate=shipping_estimate,
                country=country,
                rescore=True,
            )
        return trimmed

    def ensure_sold_guide(
        self,
        item_type: str,
        item_no: str,
        *,
        condition: str = "U",
        percentile: float = 20.0,
        force_refresh: bool = False,
        ttl_seconds: int = 24 * 3600,
    ) -> dict[str, Any]:
        canonical = canonical_item_type(item_type)
        if not force_refresh:
            existing = self.buy.store.query_price_guides(
                item_type=canonical, item_no=item_no, condition_code=condition,
                guide_type="sold", limit=1,
            )
            if existing and (time.time() - float(existing[0].get("fetched_at") or 0)) <= ttl_seconds:
                return existing[0]
        from ..client import get_client
        client = get_client()
        payload = client.get_price_guide(
            item_type=canonical, item_no=item_no, guide_type="sold", condition=condition,
        )
        metrics = score_price_guide(payload, percentile=percentile)
        # attach country summary into details path via extra store field: reuse currency? 
        # Store country summary JSON in a detail-less side: put on price_guides via hacking description - better add column.
        countries = sold_country_summary(
            [
                {
                    "seller_country_code": d.get("seller_country_code"),
                    "quantity": d.get("quantity"),
                }
                for d in metrics["details"]
            ]
        )
        # Temporarily stash as fake detail meta by storing JSON in currency? No — use replace and set currency normally;
        # write country summary into price_details is wrong. Add optional note via replacing max_price unused - ugly.
        # Store as JSON file? Prefer ALTER: country_summary TEXT column.
        self.buy.store.replace_price_guide(
            item_type=canonical,
            item_no=item_no,
            condition_code=condition,
            guide_type="sold",
            color_id=None,
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
            country_summary=countries,
        )
        rows = self.buy.store.query_price_guides(
            item_type=canonical, item_no=item_no, condition_code=condition, guide_type="sold", limit=1,
        )
        return rows[0] if rows else {}

    def update_lots(
        self,
        *,
        item_type: str,
        min_gap_ratio: float = 0.4,
        limit: int = 25,
        max_lots: int = 40,
        condition: str = "U",
        percentile: float = 20.0,
        fetch_sold: bool = True,
        item_no_prefix: str | None = None,
    ) -> dict[str, Any]:
        """Paced catalogifs update for high stock-gap items; attaches seller/store/country lots."""
        canonical = canonical_item_type(item_type)
        shortlist = self.buy.list_price_gaps(
            item_type=canonical,
            condition_code=condition,
            guide_type="stock",
            min_gap_ratio=min_gap_ratio,
            item_no_prefix=item_no_prefix,
            limit=limit,
        )
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for idx, stock in enumerate(shortlist, start=1):
            item_no = stock["item_no"]
            try:
                sold = None
                if fetch_sold:
                    sold = self.ensure_sold_guide(
                        canonical, item_no, condition=condition, percentile=percentile,
                    )
                lot_result = self.buy.fetch_lots(
                    canonical, item_no, condition=condition, max_lots=max_lots,
                )
                lots = lot_result.get("lots") or []
                # summarize countries from live lots
                countries: dict[str, int] = {}
                for lot in lots:
                    cc = (lot.get("country") or lot.get("seller_country_code") or "").upper()
                    if not cc:
                        continue
                    countries[cc] = countries.get(cc, 0) + 1
                # cheapest live lots with seller/store/country for buy-low action
                def _price_key(lot: dict[str, Any]) -> float:
                    v = lot.get("price_value")
                    if v is None:
                        return 1e18
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return 1e18
                cheap_lots = []
                for lot in sorted(lots, key=_price_key)[:10]:
                    cheap_lots.append({
                        "id_inv": lot.get("id_inv") or lot.get("idInv"),
                        "price": lot.get("price") or lot.get("price_display"),
                        "price_value": lot.get("price_value"),
                        "qty": lot.get("qty"),
                        "condition": lot.get("condition") or lot.get("condition_code"),
                        "seller": lot.get("seller") or lot.get("seller_username"),
                        "store": lot.get("store") or lot.get("store_name"),
                        "country": lot.get("country") or lot.get("seller_country_code"),
                    })
                opp = build_opportunity_row(stock, sold, shipping_estimate=DEFAULT_SHIPPING_ESTIMATE)
                results.append({
                    **opp,
                    "id_item": lot_result.get("id_item"),
                    "live_lot_count": lot_result.get("count"),
                    "live_countries": dict(sorted(countries.items(), key=lambda kv: -kv[1])),
                    "cheap_lots": cheap_lots,
                    "cached_lots": lot_result.get("cached", False),
                })
                logger.info(
                    "update %s/%s %s %s lots=%s countries=%s",
                    idx, len(shortlist), canonical, item_no,
                    lot_result.get("count"), countries,
                )
                # polite pacing beyond host queue recovery
                time.sleep(0.5)
            except Exception as exc:
                logger.warning("update failed %s %s: %s", canonical, item_no, exc)
                errors.append({"item_type": canonical, "item_no": item_no, "error": str(exc)})
        results.sort(key=lambda r: (r.get("opportunity_ratio") is None, -(r.get("opportunity_ratio") or 0)))
        return {
            "item_type": canonical,
            "min_gap_ratio": min_gap_ratio,
            "requested": len(shortlist),
            "ok": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }
