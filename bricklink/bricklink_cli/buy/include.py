"""Optional --include enrichment for buy CLI rows.

BrickLink OAuth price guides are anonymous (no seller/store/country).
Live catalogifs lots (stored as current_inventory) carry that granular
seller data. ``--include sellers`` joins the cheapest live lots onto
gap/opportunity rows from local SQLite — no extra network call.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .pricing import DEFAULT_SHIPPING_ESTIMATE, landed_buy_cost, opportunity_score

# Canonical flag -> accepted CLI tokens
_INCLUDE_ALIASES: dict[str, frozenset[str]] = {
    "sellers": frozenset({"sellers", "seller", "store", "country", "feedback"}),
}

_ALL_TOKENS = frozenset().union(*_INCLUDE_ALIASES.values())


def parse_include(raw: Optional[str]) -> set[str]:
    """Parse comma-separated --include into canonical flags.

    Raises ValueError on unknown tokens.
    """
    if raw is None or not str(raw).strip():
        return set()
    tokens = {t.strip().lower() for t in str(raw).split(",") if t.strip()}
    unknown = sorted(tokens - _ALL_TOKENS)
    if unknown:
        known = ", ".join(sorted(_ALL_TOKENS))
        raise ValueError(f"Unknown --include value(s): {', '.join(unknown)}. Known: {known}")
    flags: set[str] = set()
    for flag, aliases in _INCLUDE_ALIASES.items():
        if tokens & aliases:
            flags.add(flag)
    return flags


def seller_lot_summary(
    lot: dict[str, Any],
    *,
    shipping_estimate: float = DEFAULT_SHIPPING_ESTIMATE,
) -> dict[str, Any]:
    """Normalize a lot dict/row into the seller-facing cheap_lots shape."""
    price_value = lot.get("price_value")
    try:
        price_f = float(price_value) if price_value is not None else None
    except (TypeError, ValueError):
        price_f = None
    return {
        "id_inv": lot.get("id_inv") or lot.get("idInv"),
        "price": lot.get("price") or lot.get("price_display"),
        "price_value": price_f,
        "shipping_est": float(shipping_estimate),
        "landed_price": landed_buy_cost(price_f, shipping_estimate=shipping_estimate),
        "qty": lot.get("qty"),
        "condition": lot.get("condition") or lot.get("condition_code"),
        "seller": lot.get("seller") or lot.get("seller_username"),
        "store": lot.get("store") or lot.get("store_name"),
        "country": lot.get("country") or lot.get("seller_country_code"),
        "feedback": lot.get("feedback") if "feedback" in lot else lot.get("seller_feedback"),
    }


def cheap_seller_lots_from_store(
    store,
    *,
    item_type: str,
    item_no: str,
    condition: str | None = None,
    limit: int = 10,
    shipping_estimate: float = DEFAULT_SHIPPING_ESTIMATE,
) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    """Return (cheap_lots, country_counts, total_matching) from local current_inventory."""
    # Pull a wider page then slice so country summary reflects more than the cheap 10
    rows = store.query_lots(
        item_type=item_type,
        item_no=item_no,
        condition=condition,
        limit=max(limit, 100),
    )
    total = len(rows)
    countries: dict[str, int] = {}
    cheap: list[dict[str, Any]] = []
    for row in rows:
        d = row.as_dict() if hasattr(row, "as_dict") else dict(row)
        cc = (d.get("country") or "").upper()
        if cc:
            countries[cc] = countries.get(cc, 0) + 1
        if len(cheap) < limit:
            cheap.append(seller_lot_summary(d, shipping_estimate=shipping_estimate))
    countries = dict(sorted(countries.items(), key=lambda kv: -kv[1]))
    return cheap, countries, total


def attach_sellers(
    rows: Iterable[dict[str, Any]],
    store,
    *,
    condition: str | None = None,
    max_lots: int = 10,
    shipping_estimate: float = DEFAULT_SHIPPING_ESTIMATE,
    country: str | None = None,
    rescore: bool = True,
) -> list[dict[str, Any]]:
    """Copy rows and attach cheap_lots / live_countries / live_lot_count from SQLite.

    Adds per-lot ``shipping_est`` / ``landed_price``. When ``rescore`` is true and
    a usable live lot exists, opportunity is recomputed from cheapest landed buy
    vs existing sell_proxy.
    """
    country_u = country.upper() if country else None
    out: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        item_type = enriched.get("item_type")
        item_no = enriched.get("item_no")
        enriched["shipping_estimate"] = float(shipping_estimate)
        if not item_type or not item_no:
            enriched.setdefault("cheap_lots", [])
            enriched.setdefault("live_countries", {})
            enriched.setdefault("live_lot_count", 0)
            out.append(enriched)
            continue
        cond = condition or enriched.get("condition_code") or enriched.get("condition")
        cheap, countries, total = cheap_seller_lots_from_store(
            store,
            item_type=str(item_type),
            item_no=str(item_no),
            condition=cond,
            limit=max_lots,
            shipping_estimate=shipping_estimate,
        )
        if country_u:
            cheap = [L for L in cheap if (L.get("country") or "").upper() == country_u]
        # Prefer cheapest by landed_price for display order
        cheap = sorted(
            cheap,
            key=lambda L: L.get("landed_price") if L.get("landed_price") is not None else 1e18,
        )
        enriched["cheap_lots"] = cheap
        enriched["live_countries"] = countries
        enriched["live_lot_count"] = total
        if rescore:
            sell_proxy = enriched.get("sell_proxy") or enriched.get("sold_avg")
            best = cheap[0] if cheap else None
            buy_unit = best.get("price_value") if best else enriched.get("buy_proxy")
            if buy_unit is None:
                buy_unit = enriched.get("lower_pct_price")
            scored = opportunity_score(
                buy_proxy=buy_unit,
                sell_proxy=sell_proxy,
                shipping_estimate=shipping_estimate,
            )
            enriched["buy_proxy_unit"] = buy_unit
            enriched["landed_buy"] = scored["landed_buy"]
            enriched["opportunity_abs"] = scored["opportunity_abs"]
            enriched["opportunity_ratio"] = scored["opportunity_ratio"]
            if best:
                enriched["best_seller"] = best.get("seller")
                enriched["best_store"] = best.get("store")
                enriched["best_country"] = best.get("country")
        out.append(enriched)
    return out
