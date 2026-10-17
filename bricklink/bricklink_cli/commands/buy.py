"""Buyer marketplace commands (phase 1: per-item lots)."""

COMMAND_CREDENTIALS = {
    "item": ["no_auth"],
    "prices": ["oauth"],
    "gaps": ["no_auth"],
    "opportunities": ["no_auth"],
    # Nested under current_inventory (flat leaf lookup in command_registry)
    "list": ["no_auth"],
    "update": ["oauth"],
}

from typing import Optional

import typer

from ..display import print_list
from ..buy.service import BuyService
from ..buy.types import canonical_item_type
from cli_tools_shared.output import command, print_json, handle_error
from ..buy.include import attach_sellers, parse_include
from ..buy.pricing import DEFAULT_SHIPPING_ESTIMATE

app = typer.Typer(help="Browse BrickLink for-sale lots (buyer)", no_args_is_help=True)
current_inventory_app = typer.Typer(
    help="Live for-sale inventory (seller, store, country)",
    no_args_is_help=True,
)
app.add_typer(
    current_inventory_app,
    name="current_inventory",
    help="Live for-sale inventory (seller, store, country)",
)

LOT_COLUMNS = [
    "id_inv", "item_type", "item_no", "color_id", "condition",
    "qty", "price", "store", "seller", "country",
]
LOT_HEADERS = [
    "Inv", "Type", "No", "Color", "Cond", "Qty", "Price", "Store", "Seller", "CC",
]


@app.command("item")
@command
def buy_item(
    item_type: str = typer.Argument(..., help="Item type (PART, MINIFIG, SET, P, M, S, ...)"),
    item_no: str = typer.Argument(..., help="Catalog item number (e.g. 3001, sw0936)"),
    color: Optional[int] = typer.Option(None, "--color", help="BrickLink color id"),
    condition: Optional[str] = typer.Option(None, "--condition", help="N or U"),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Bypass idItem/lots TTL caches"),
    table: bool = typer.Option(False, "--table", "-t", help="Display lots as table"),
    limit: int = typer.Option(25, "--limit", "-l", help="Max lots to fetch and display (caps BrickLink pagination)"),
):
    """Resolve idItem and refresh live lots into local current_inventory."""
    try:
        service = BuyService()
        result = service.fetch_lots(
            item_type,
            item_no,
            color_id=color,
            condition=condition,
            force_refresh=force_refresh,
            max_lots=limit,
        )
        lots = result.get("lots") or []
        summary = {
            "item_type": result["item_type"],
            "item_no": result["item_no"],
            "id_item": result["id_item"],
            "count": result["count"],
            "cached": result.get("cached", False),
            "reported_total": result.get("reported_total"),
        }
        if table:
            print_json(summary)
            print_list(lots[:limit], True, None, LOT_COLUMNS, LOT_HEADERS)
        else:
            print_json({**summary, "lots": lots[:limit]})
    except Exception as e:
        raise typer.Exit(handle_error(e))


@current_inventory_app.command("list")
@command
def current_inventory_list(
    item_type: Optional[str] = typer.Option(None, "--type", help="Filter by item type"),
    item_no: Optional[str] = typer.Option(None, "--no", help="Filter by item number"),
    category: Optional[int] = typer.Option(
        None,
        "--category",
        help="Filter by BrickBuddy/BrickLink category id (joins seeded items). Requires --limit.",
    ),
    color: Optional[int] = typer.Option(None, "--color", help="BrickLink color id"),
    country: Optional[str] = typer.Option(None, "--country", help="Seller country code"),
    condition: Optional[str] = typer.Option(None, "--condition", help="N or U"),
    max_price: Optional[float] = typer.Option(None, "--max-price", help="Maximum unit price"),
    min_qty: Optional[int] = typer.Option(None, "--min-qty", help="Minimum quantity"),
    store: Optional[str] = typer.Option(None, "--store", help="Store name substring"),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Max rows (required when --category is set; default 100 otherwise)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List/filter live lots already stored in local current_inventory."""
    try:
        if category is not None and limit is None:
            raise typer.BadParameter("--limit is required when filtering by --category")
        effective_limit = 100 if limit is None else limit
        if effective_limit < 1:
            raise typer.BadParameter("--limit must be a positive integer")
        service = BuyService()
        canonical = canonical_item_type(item_type) if item_type else None
        rows = service.list_lots(
            item_type=canonical,
            item_no=item_no,
            category_id=category,
            color_id=color,
            country=country,
            condition=condition,
            max_price=max_price,
            min_qty=min_qty,
            store=store,
            limit=effective_limit,
        )
        data = [r.as_dict() for r in rows]
        print_list(data, table, properties, LOT_COLUMNS, LOT_HEADERS)
    except Exception as e:
        raise typer.Exit(handle_error(e))


PRICE_COLUMNS = [
    "item_type", "item_no", "condition_code", "min_price", "lower_pct_price",
    "avg_price", "gap_abs", "gap_ratio", "unit_quantity",
]
PRICE_HEADERS = [
    "Type", "No", "Cond", "Min", "Low%", "Avg", "Gap$", "Gap%", "Lots",
]


@app.command("prices")
@command
def buy_prices(
    item_type: str = typer.Argument(..., help="Item type to refresh (e.g. MINIFIG, PART)"),
    limit: int = typer.Option(..., "--limit", "-l", help="Max catalog items to refresh (required)"),
    condition: str = typer.Option("U", "--condition", help="N or U (default U)"),
    guide: str = typer.Option("stock", "--guide", help="stock or sold"),
    percentile: float = typer.Option(
        20.0,
        "--percentile",
        help="Lowest percentage band of listing prices (e.g. 20 = bottom 20%)",
    ),
    prefix: Optional[str] = typer.Option(None, "--prefix", help="Only item numbers with this prefix (e.g. sw)"),
    category: Optional[int] = typer.Option(None, "--category", help="BrickBuddy category id filter"),
    color: Optional[int] = typer.Option(None, "--color", help="BrickLink color id"),
    offset: int = typer.Option(0, "--offset", help="Skip this many seeded items"),
    table: bool = typer.Option(False, "--table", "-t", help="Show top gaps as table"),
    top: int = typer.Option(25, "--top", help="How many top gaps to display"),
):
    """Refresh OAuth price guides and score lowest-percentile vs average gaps."""
    try:
        if limit < 1:
            raise typer.BadParameter("--limit must be a positive integer")
        if not (0 < percentile <= 100):
            raise typer.BadParameter("--percentile must be in (0, 100]")
        service = BuyService()
        result = service.refresh_prices(
            item_type,
            limit=limit,
            condition=condition,
            guide_type=guide,
            percentile=percentile,
            category_id=category,
            item_no_prefix=prefix,
            color_id=color,
            offset=offset,
        )
        summary = {
            "item_type": result["item_type"],
            "condition": result["condition"],
            "guide_type": result["guide_type"],
            "percentile": result["percentile"],
            "requested": result["requested"],
            "ok": result["ok"],
            "skipped": result.get("skipped", 0),
            "failed": result["failed"],
        }
        top_rows = result["results"][:top]
        if table:
            print_json(summary)
            print_list(
                [
                    {
                        **r,
                        "condition_code": r.get("condition"),
                        "gap_ratio": None if r.get("gap_ratio") is None else round(r["gap_ratio"] * 100, 1),
                    }
                    for r in top_rows
                ],
                True,
                None,
                PRICE_COLUMNS,
                PRICE_HEADERS,
            )
        else:
            print_json({**summary, "top": top_rows, "errors": result["errors"][:10]})
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("gaps")
@command
def buy_gaps(
    item_type: Optional[str] = typer.Option(None, "--type", help="Filter by item type"),
    item_no: Optional[str] = typer.Option(None, "--no", help="Filter by item number"),
    condition: Optional[str] = typer.Option(None, "--condition", help="N or U"),
    prefix: Optional[str] = typer.Option(None, "--prefix", help="Item number prefix"),
    min_gap_ratio: Optional[float] = typer.Option(
        None,
        "--min-gap-ratio",
        help="Minimum (avg-lower%)/avg, e.g. 0.3 = 30% below avg",
    ),
    min_gap_abs: Optional[float] = typer.Option(None, "--min-gap-abs", help="Minimum avg-lower% in currency"),
    guide: str = typer.Option("stock", "--guide", help="stock or sold"),
    include: Optional[str] = typer.Option(
        None,
        "--include",
        help="Enrichment missing from OAuth guides (sellers=seller/store/country/feedback from local current_inventory)",
    ),
    shipping: float = typer.Option(
        DEFAULT_SHIPPING_ESTIMATE,
        "--shipping",
        help=f"Flat per-seller shipping estimate added to buy side (default {DEFAULT_SHIPPING_ESTIMATE})",
    ),
    country: Optional[str] = typer.Option(
        None, "--country", help="When --include sellers, only keep lots from this country (e.g. US)"
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Max rows"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List stored price-guide rows with largest lowest-percentile vs avg gaps."""
    try:
        if limit < 1:
            raise typer.BadParameter("--limit must be a positive integer")
        flags = parse_include(include)
        service = BuyService()
        rows = service.list_price_gaps(
            item_type=item_type,
            item_no=item_no,
            condition_code=condition,
            guide_type=guide,
            min_gap_ratio=min_gap_ratio,
            min_gap_abs=min_gap_abs,
            item_no_prefix=prefix,
            limit=limit,
        )
        if shipping < 0:
            raise typer.BadParameter("--shipping must be >= 0")
        if "sellers" in flags:
            rows = attach_sellers(
                rows,
                service.store,
                condition=condition,
                max_lots=10,
                shipping_estimate=shipping,
                country=country,
                rescore=True,
            )
        data = []
        for r in rows:
            d = dict(r)
            if d.get("gap_ratio") is not None:
                d["gap_ratio_pct"] = round(float(d["gap_ratio"]) * 100, 1)
            if isinstance(d.get("live_countries"), dict) and table:
                d["live_countries"] = ",".join(
                    f"{k}:{v}" for k, v in list(d["live_countries"].items())[:5]
                )
            data.append(d)
        cols = PRICE_COLUMNS + ["gap_ratio_pct"]
        headers = PRICE_HEADERS + ["Gap%"]
        if table:
            print_list(data, True, properties, cols, headers)
            if "sellers" in flags:
                flat = []
                for r in rows:
                    for lot in r.get("cheap_lots") or []:
                        flat.append({
                            "item_no": r.get("item_no"),
                            "price": lot.get("price"),
                            "qty": lot.get("qty"),
                            "seller": lot.get("seller"),
                            "store": lot.get("store"),
                            "country": lot.get("country"),
                            "feedback": lot.get("feedback"),
                        })
                if flat:
                    print_list(
                        flat[:50], True, None,
                        ["item_no", "price", "qty", "seller", "store", "country", "feedback"],
                        ["No", "Price", "Qty", "Seller", "Store", "CC", "FB"],
                    )
        else:
            print_json(data)
    except Exception as e:
        raise typer.Exit(handle_error(e))


OPP_COLUMNS = [
    "item_type", "item_no", "buy_proxy", "sell_proxy", "opportunity_ratio",
    "live_lot_count", "live_countries",
]
OPP_HEADERS = ["Type", "No", "Buy~", "Sell~", "Opp%", "LiveLots", "Countries"]


@app.command("opportunities")
@command
def buy_opportunities(
    item_type: Optional[str] = typer.Option(None, "--type", help="Filter by item type"),
    condition: str = typer.Option("U", "--condition", help="N or U"),
    prefix: Optional[str] = typer.Option(None, "--prefix", help="Item number prefix"),
    min_gap_ratio: Optional[float] = typer.Option(0.4, "--min-gap-ratio", help="Min stock Low% vs avg gap"),
    min_opportunity_ratio: Optional[float] = typer.Option(
        None, "--min-opp-ratio", help="Min (sell_proxy-buy_proxy)/sell_proxy"
    ),
    include: Optional[str] = typer.Option(
        None,
        "--include",
        help="Enrichment missing from OAuth guides (sellers=seller/store/country/feedback from local current_inventory)",
    ),
    shipping: float = typer.Option(
        DEFAULT_SHIPPING_ESTIMATE,
        "--shipping",
        help=f"Flat per-seller shipping estimate added to buy side (default {DEFAULT_SHIPPING_ESTIMATE})",
    ),
    country: Optional[str] = typer.Option(
        None, "--country", help="When --include sellers, only keep lots from this country (e.g. US)"
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Max rows"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List buy-low/sell-high candidates from stored stock (+ sold when present)."""
    try:
        from ..buy.opportunities import OpportunityService
        flags = parse_include(include)
        service = OpportunityService(BuyService())
        if shipping < 0:
            raise typer.BadParameter("--shipping must be >= 0")
        rows = service.list_opportunities(
            item_type=item_type,
            condition=condition,
            min_gap_ratio=min_gap_ratio,
            min_opportunity_ratio=min_opportunity_ratio,
            item_no_prefix=prefix,
            limit=limit,
            include=include,
            shipping_estimate=shipping,
            country=country,
        )
        data = []
        for r in rows:
            d = dict(r)
            if d.get("opportunity_ratio") is not None:
                d["opportunity_ratio"] = round(float(d["opportunity_ratio"]) * 100, 1)
            if isinstance(d.get("live_countries"), dict) and table:
                d["live_countries"] = ",".join(
                    f"{k}:{v}" for k, v in list(d["live_countries"].items())[:5]
                )
            data.append(d)
        if table:
            print_list(data, True, None, OPP_COLUMNS, OPP_HEADERS)
            if "sellers" in flags:
                flat = []
                for r in rows:
                    for lot in r.get("cheap_lots") or []:
                        flat.append({
                            "item_no": r.get("item_no"),
                            "price": lot.get("price"),
                            "qty": lot.get("qty"),
                            "seller": lot.get("seller"),
                            "store": lot.get("store"),
                            "country": lot.get("country"),
                            "feedback": lot.get("feedback"),
                        })
                if flat:
                    print_list(
                        flat[:50], True, None,
                        ["item_no", "price", "qty", "seller", "store", "country", "feedback"],
                        ["No", "Price", "Qty", "Seller", "Store", "CC", "FB"],
                    )
        else:
            print_json(data)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@current_inventory_app.command("update")
@command
def current_inventory_update(
    item_type: str = typer.Argument(..., help="Item type (e.g. MINIFIG)"),
    min_gap_ratio: float = typer.Option(0.4, "--min-gap-ratio", help="Only update items whose stock gap is at least this large"),
    limit: int = typer.Option(25, "--limit", "-l", help="Max items to update (keep small — uses catalogifs)"),
    max_lots: int = typer.Option(40, "--max-lots", help="Max live lots to store per item"),
    condition: str = typer.Option("U", "--condition", help="N or U"),
    percentile: float = typer.Option(20.0, "--percentile", help="Lowest % band when refreshing sold guide"),
    prefix: Optional[str] = typer.Option(None, "--prefix", help="Item number prefix"),
    no_sold: bool = typer.Option(False, "--no-sold", help="Skip OAuth sold-guide enrich"),
    table: bool = typer.Option(False, "--table", "-t", help="Show summary table"),
):
    """Refresh live current_inventory for high-gap items (seller/store/country via catalogifs)."""
    try:
        if limit < 1:
            raise typer.BadParameter("--limit must be a positive integer")
        if limit > 100:
            raise typer.BadParameter("--limit max 100 per update run (soft-throttle protection)")
        from ..buy.opportunities import OpportunityService
        service = OpportunityService(BuyService())
        result = service.update_lots(
            item_type=item_type,
            min_gap_ratio=min_gap_ratio,
            limit=limit,
            max_lots=max_lots,
            condition=condition,
            percentile=percentile,
            fetch_sold=not no_sold,
            item_no_prefix=prefix,
        )
        summary = {k: result[k] for k in ("item_type", "min_gap_ratio", "requested", "ok", "failed")}
        rows = []
        for r in result["results"]:
            d = dict(r)
            if d.get("opportunity_ratio") is not None:
                d["opportunity_ratio"] = round(float(d["opportunity_ratio"]) * 100, 1)
            if isinstance(d.get("live_countries"), dict):
                d["live_countries"] = ",".join(f"{k}:{v}" for k, v in list(d["live_countries"].items())[:5])
            rows.append(d)
        # Always include cheap_lots (seller/store/country) in JSON
        if table:
            print_json(summary)
            print_list(rows, True, None, OPP_COLUMNS, OPP_HEADERS)
            # also print a flat seller table from cheap_lots
            flat = []
            for r in result["results"]:
                for lot in r.get("cheap_lots") or []:
                    flat.append({
                        "item_no": r.get("item_no"),
                        "price": lot.get("price"),
                        "qty": lot.get("qty"),
                        "seller": lot.get("seller"),
                        "store": lot.get("store"),
                        "country": lot.get("country"),
                    })
            if flat:
                print_list(
                    flat[:50], True, None,
                    ["item_no", "price", "qty", "seller", "store", "country"],
                    ["No", "Price", "Qty", "Seller", "Store", "CC"],
                )
        else:
            print_json({**summary, "results": rows, "errors": result["errors"][:10]})
    except Exception as e:
        raise typer.Exit(handle_error(e))
