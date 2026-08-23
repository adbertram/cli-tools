"""Search commands for ShopGoodwill CLI."""
from typing import Optional
import typer
from ..client import ShopGoodwillClient, ClientError
from ..output import print_json, print_table, print_status, command

app = typer.Typer(help="Search ShopGoodwill listings")


# Source-CLI Sort Standard: sort field -> (API sortColumn int, natural sortDescending).
# Integer sortColumn values were verified from the live ShopGoodwill sort dropdown
# (value = "<sortColumn>|<descending>"): Ending Soonest=1|0, Newly Listed=1|1,
# Bids Most=3|1 / Least=3|0, Price Lowest=4|0 / Highest=4|1. The API silently
# ignores the legacy string column names. --desc reverses the natural direction.
# ShopGoodwill has NO true listing-date column, so "newest" uses the "Newly Listed"
# window (sortColumn 1 desc) refined client-side by startTime (see client.search_recency_window).
SORT_FIELDS = {
    "newest": (1, True),    # "Newly Listed" (EndingDate desc); refined by startTime
    "price": (4, False),    # BidPrice ascending = low -> high
    "ending": (1, False),   # EndingDate ascending = ending soonest
    "bids": (3, False),     # NumberofBids ascending = fewest first
}


def _validate_sort_field(value: str) -> str:
    """Typer callback: reject unknown --sort values with a usage error.

    Runs during option parsing, so an invalid field is reported as a clean
    Click usage error (non-zero exit) instead of silently falling back to a
    default sort field.
    """
    key = value.lower()
    if key not in SORT_FIELDS:
        valid = ", ".join(SORT_FIELDS)
        raise typer.BadParameter(f"Invalid --sort '{value}'. Valid values: {valid}")
    return key


def _resolve_sort(sort: str, descending: bool) -> tuple:
    """Resolve a --sort field + --desc flag into the API (sortColumn, sortDescending) pair.

    --desc reverses the field's natural direction. Unknown fields raise
    typer.BadParameter (no silent fallback).
    """
    key = _validate_sort_field(sort)
    sort_column, natural_descending = SORT_FIELDS[key]
    sort_descending = (not natural_descending) if descending else natural_descending
    return sort_column, sort_descending


@app.command("query")
@command
def search_query(
    query: str = typer.Argument(..., help="Search text"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    page: int = typer.Option(1, "--page", "-p", help="Page number"),
    limit: int = typer.Option(
        40, "--limit", "-l",
        help=(
            "Results per page. Default --sort newest: up to 200 "
            "(recency-window fetch is capped at 200 items). "
            "--sort price/ending/bids: max 40 (single API page)."
        ),
    ),
    min_price: Optional[float] = typer.Option(None, "--min-price", help="Minimum price"),
    max_price: Optional[float] = typer.Option(None, "--max-price", help="Maximum price"),
    sort: str = typer.Option(
        "newest",
        "--sort",
        "-s",
        help="Sort field: newest (default), price, ending, bids. --desc reverses each field's natural order.",
        callback=_validate_sort_field,
    ),
    descending: bool = typer.Option(
        False, "--desc", "-d", help="Reverse the sort field's natural direction"
    ),
    buy_now: bool = typer.Option(False, "--buy-now", help="Only buy-now items"),
    shipping: bool = typer.Option(False, "--shipping", help="Only items that ship"),
    pickup: bool = typer.Option(False, "--pickup", help="Only pickup items"),
    closed: bool = typer.Option(False, "--closed", help="Include closed auctions"),
):
    """Search for items on ShopGoodwill."""
    sort_column, sort_descending = _resolve_sort(sort, descending)
    client = ShopGoodwillClient(require_auth=False)

    filters = dict(
        low_price=min_price,
        high_price=max_price,
        buy_now_only=buy_now,
        shipping_only=shipping,
        pickup_only=pickup,
        closed_auctions=closed,
    )

    out_page = page
    if sort == "newest":
        # No server-side listing-date sort exists; fetch the "Newly Listed"
        # window, refine by startTime client-side, then slice out the
        # requested page ourselves (the window is fetched once, sorted, and
        # paged in-memory).
        offset = (page - 1) * limit
        window_items, total_count = client.search_recency_window(
            query=query,
            limit=limit,
            offset=offset,
            sort_descending=sort_descending,
            **filters,
        )
        items = window_items[offset:offset + limit]
    else:
        result = client.search(
            query=query,
            page=page,
            page_size=limit,
            sort_column=sort_column,
            sort_descending=sort_descending,
            **filters,
        )
        search_results = result.get("searchResults", {})
        items = search_results.get("items", [])
        total_count = search_results.get("itemCount", 0)
        # API caps pages at 40 items, so slice to the requested limit ourselves
        items = items[:limit]

    if table:
        if not items:
            print("No results found.")
            raise typer.Exit(0)

        # Format items for table display
        table_data = []
        for item in items:
            table_data.append({
                "id": item.get("itemId", ""),
                "title": _truncate(item.get("title", ""), 40),
                "price": f"${item.get('currentPrice', 0):.2f}",
                "bids": item.get("numBids", 0),
                "ends": _format_end_time(item.get("endTime", "")),
                "location": _truncate(item.get("sellerCity", "") + ", " + item.get("sellerState", ""), 20),
            })

        print_status(f"Found {total_count} items (showing {len(items)})")
        print_table(
            table_data,
            ["id", "title", "price", "bids", "ends", "location"],
            ["ID", "Title", "Price", "Bids", "Ends", "Location"],
        )
    else:
        # JSON output - include metadata
        output = {
            "total_count": total_count,
            "page": out_page,
            "page_size": limit,
            "items": items,
        }
        print_json(output)


@app.command("get")
@command
def search_get(
    item_id: int = typer.Argument(..., help="Item ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific item."""
    client = ShopGoodwillClient(require_auth=False)
    item = client.get_item(item_id)
    if item.get("allowShippingCalculation"):
        try:
            item["shippingEstimate"] = client.calculate_shipping(item)
        except ClientError as shipping_error:
            item["shippingEstimate"] = None
            item["shippingEstimateUnavailable"] = True
            item["shippingEstimateError"] = str(shipping_error)

    item["buy_it_now_price"] = item.get("buyNowPrice")
    auction_expired = item.get("isItemEndTimeExpire", False)
    remaining_time_ended = "ended" in str(item.get("remainingTime", "")).lower()
    item["available"] = not (auction_expired or remaining_time_ended)

    if table:
        buy_now_price = item.get("buyNowPrice")
        shipping_estimate = item.get("shippingEstimate")
        # Format key details for table
        table_data = [{
            "field": "Item ID",
            "value": str(item.get("itemId", "")),
        }, {
            "field": "Title",
            "value": item.get("title", ""),
        }, {
            "field": "Current Price",
            "value": f"${item.get('currentPrice', 0):.2f}",
        }]
        if buy_now_price:
            table_data.append({
                "field": "Buy Now Price",
                "value": f"${buy_now_price:.2f}",
            })
        table_data.extend([{
            "field": "Bids",
            "value": str(item.get("numBids", 0)),
        }, {
            "field": "End Time",
            "value": item.get("endTime", ""),
        }, {
            "field": "Seller",
            "value": item.get("sellerName", ""),
        }, {
            "field": "Location",
            "value": f"{item.get('sellerCity', '')}, {item.get('sellerState', '')}",
        }, {
            "field": "Shipping",
            "value": f"${item.get('shippingPrice', 0):.2f}" if item.get("shippingPrice") else "Not calculated",
        }, {
            "field": "URL",
            "value": f"https://shopgoodwill.com/item/{item.get('itemId', '')}",
        }])
        if shipping_estimate:
            table_data.extend([{
                "field": "Destination ZIP",
                "value": shipping_estimate["destinationZip"],
            }, {
                "field": "Destination Shipping",
                "value": f"${shipping_estimate['shippingPrice']:.2f}",
            }, {
                "field": "Destination Handling",
                "value": f"${shipping_estimate['handlingPrice']:.2f}",
            }, {
                "field": "Shipping + Handling",
                "value": f"${shipping_estimate['total']:.2f}",
            }, {
                "field": "Shipping Service",
                "value": shipping_estimate["serviceDescription"],
            }])
        print_table(table_data, ["field", "value"], ["Field", "Value"])
    else:
        print_json(item)


def _truncate(text: str, max_length: int) -> str:
    """Truncate text to max length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def _format_end_time(end_time: str) -> str:
    """Format end time for display."""
    if not end_time:
        return ""
    # Just show date and time portion
    try:
        # Format: "2025-12-25T10:30:00" -> "12/25 10:30"
        if "T" in end_time:
            date_part, time_part = end_time.split("T")
            year, month, day = date_part.split("-")
            time_only = time_part.split(".")[0][:5]  # HH:MM
            return f"{month}/{day} {time_only}"
    except (ValueError, IndexError):
        pass
    return end_time[:16] if len(end_time) > 16 else end_time


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "query": [
        "custom"
    ]
}
