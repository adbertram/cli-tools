"""Price-guide scoring: lower-percentile band vs average."""

from __future__ import annotations

from typing import Any, Optional


def _f(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_price_details(raw_details: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Flatten BrickLink price_detail rows into unit_price/quantity/shipping_available."""
    out: list[dict[str, Any]] = []
    for row in raw_details or []:
        if not isinstance(row, dict):
            continue
        price = _f(row.get("unit_price"))
        if price is None:
            continue
        out.append(
            {
                "unit_price": price,
                "quantity": _i(row.get("quantity") if row.get("quantity") is not None else row.get("qunatity")),
                "shipping_available": bool(row.get("shipping_available")),
                "seller_country_code": (str(row["seller_country_code"]).upper()
                                       if row.get("seller_country_code") else None),
            }
        )
    out.sort(key=lambda d: d["unit_price"])
    return out


def lower_percentile_price(
    details: list[dict[str, Any]],
    *,
    percentile: float = 20.0,
) -> Optional[float]:
    """Qty-weighted price at the top of the lowest ``percentile`` band.

    Expands each detail row by its quantity (default 1), sorts ascending, and
    returns the price at the percentile cutoff (e.g. 20 => price at the 20th
    percentile of unit stock). That is the ceiling of the "lowest percentage"
    band — not only the single cheapest lot.
    """
    if not details:
        return None
    pct = max(0.0, min(100.0, float(percentile)))
    units: list[float] = []
    for d in details:
        qty = d.get("quantity") or 1
        qty = max(1, int(qty))
        units.extend([float(d["unit_price"])] * qty)
    units.sort()
    if not units:
        return None
    if pct <= 0:
        return units[0]
    # index of last unit still inside the lowest pct band
    idx = max(0, min(len(units) - 1, int((pct / 100.0) * len(units)) - 1))
    if pct > 0 and idx < 0:
        idx = 0
    # when pct*n < 1, still include at least the cheapest unit
    if int((pct / 100.0) * len(units)) == 0:
        return units[0]
    return units[idx]


def score_price_guide(
    payload: dict[str, Any],
    *,
    percentile: float = 20.0,
) -> dict[str, Any]:
    """Compute lower-percentile / gap metrics from a stock|sold price-guide payload."""
    details = normalize_price_details(payload.get("price_detail"))
    min_price = _f(payload.get("min_price"))
    max_price = _f(payload.get("max_price"))
    avg_price = _f(payload.get("avg_price"))
    qty_avg_price = _f(payload.get("qty_avg_price"))
    lower = lower_percentile_price(details, percentile=percentile)
    # Prefer lower-percentile band vs avg; fall back to min vs avg.
    cheap = lower if lower is not None else min_price
    gap_abs = None
    gap_ratio = None
    if cheap is not None and avg_price is not None and avg_price > 0:
        gap_abs = avg_price - cheap
        gap_ratio = gap_abs / avg_price
    return {
        "currency": payload.get("currency_code"),
        "min_price": min_price,
        "max_price": max_price,
        "avg_price": avg_price,
        "qty_avg_price": qty_avg_price,
        "unit_quantity": _i(payload.get("unit_quantity")),
        "total_quantity": _i(payload.get("total_quantity")),
        "lower_pct": float(percentile),
        "lower_pct_price": lower,
        "gap_abs": gap_abs,
        "gap_ratio": gap_ratio,
        "details": details,
    }



def sold_country_summary(details: list[dict[str, Any]]) -> dict[str, int]:
    """Count seller_country_code values from sold price_detail rows."""
    counts: dict[str, int] = {}
    for d in details or []:
        cc = d.get("seller_country_code") or d.get("country")
        if not cc:
            continue
        key = str(cc).upper()
        qty = d.get("quantity") or 1
        try:
            qty = max(1, int(qty))
        except (TypeError, ValueError):
            qty = 1
        counts[key] = counts.get(key, 0) + qty
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


# Flat per-seller shipping pad when true rates are unknown (US domestic ballpark).
DEFAULT_SHIPPING_ESTIMATE = 5.50


def landed_buy_cost(
    unit_price: float | None,
    *,
    shipping_estimate: float = DEFAULT_SHIPPING_ESTIMATE,
) -> float | None:
    """Unit price plus flat per-seller shipping estimate."""
    if unit_price is None:
        return None
    return float(unit_price) + float(shipping_estimate)


def opportunity_score(
    *,
    buy_proxy: float | None,
    sell_proxy: float | None,
    shipping_estimate: float = 0.0,
) -> dict[str, float | None]:
    """buy_proxy = stock lower-percentile or live lot; sell_proxy = sold avg (or stock avg).

    ``shipping_estimate`` is added to the buy side (per seller) so thin gaps
    that die after ~$5–6 shipping are not treated as opportunities.
    """
    landed = landed_buy_cost(buy_proxy, shipping_estimate=shipping_estimate)
    if buy_proxy is None or sell_proxy is None or sell_proxy <= 0:
        return {
            "opportunity_abs": None,
            "opportunity_ratio": None,
            "landed_buy": landed,
            "shipping_estimate": float(shipping_estimate),
        }
    assert landed is not None
    opp_abs = float(sell_proxy) - landed
    return {
        "opportunity_abs": opp_abs,
        "opportunity_ratio": opp_abs / float(sell_proxy),
        "landed_buy": landed,
        "shipping_estimate": float(shipping_estimate),
    }
