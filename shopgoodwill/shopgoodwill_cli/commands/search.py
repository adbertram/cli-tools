"""Search commands for ShopGoodwill CLI."""
from typing import Optional
import typer
from ..client import ShopGoodwillClient, ClientError
from ..output import print_json, print_table, print_error, print_status, handle_error

app = typer.Typer(help="Search ShopGoodwill listings")


@app.command("query")
def search_query(
    query: str = typer.Argument(..., help="Search text"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    page: int = typer.Option(1, "--page", "-p", help="Page number"),
    limit: int = typer.Option(40, "--limit", "-l", help="Results per page (max 40)"),
    min_price: Optional[float] = typer.Option(None, "--min-price", help="Minimum price"),
    max_price: Optional[float] = typer.Option(None, "--max-price", help="Maximum price"),
    sort: str = typer.Option(
        "ending",
        "--sort",
        "-s",
        help="Sort by: ending, bids, price, newest",
    ),
    descending: bool = typer.Option(False, "--desc", "-d", help="Sort descending"),
    buy_now: bool = typer.Option(False, "--buy-now", help="Only buy-now items"),
    shipping: bool = typer.Option(False, "--shipping", help="Only items that ship"),
    pickup: bool = typer.Option(False, "--pickup", help="Only pickup items"),
    closed: bool = typer.Option(False, "--closed", help="Include closed auctions"),
):
    """Search for items on ShopGoodwill."""
    try:
        # Map sort options to API values
        sort_map = {
            "ending": "EndingSoonest",
            "bids": "BidCount",
            "price": "Price",
            "newest": "ListedDate",
        }
        sort_by = sort_map.get(sort.lower(), "EndingSoonest")
        sort_order = "d" if descending else "a"

        client = ShopGoodwillClient(require_auth=False)
        result = client.search(
            query=query,
            page=page,
            page_size=limit,
            low_price=min_price,
            high_price=max_price,
            sort_by=sort_by,
            sort_order=sort_order,
            buy_now_only=buy_now,
            shipping_only=shipping,
            pickup_only=pickup,
            closed_auctions=closed,
        )

        search_results = result.get("searchResults", {})
        items = search_results.get("items", [])
        total_count = search_results.get("itemCount", 0)

        # API doesn't respect pageSize, so slice results ourselves
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
                "page": page,
                "page_size": limit,
                "items": items,
            }
            print_json(output)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def search_get(
    item_id: int = typer.Argument(..., help="Item ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific item."""
    try:
        client = ShopGoodwillClient(require_auth=False)
        item = client.get_item(item_id)

        if table:
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
            }, {
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
                "value": f"${item.get('shippingPrice', 0):.2f}" if item.get("shippingPrice") else "Pickup Only",
            }, {
                "field": "URL",
                "value": f"https://shopgoodwill.com/item/{item.get('itemId', '')}",
            }]
            print_table(table_data, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


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
