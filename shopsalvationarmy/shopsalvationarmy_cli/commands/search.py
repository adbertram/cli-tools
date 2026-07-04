"""Search commands for ShopSalvationArmy CLI."""
from typing import Dict, List, Optional
import typer
from ..client import ShopSalvationArmyClient, ClientError, get_client
from ..output import print_json, print_table, print_error, print_status, handle_error

app = typer.Typer(help="Search Shop The Salvation Army listings")
DEFAULT_SHIPPING_ZIP = "47725"
DEFAULT_SHIPPING_STATE = "IN"
DEFAULT_SHIPPING_CITY = "Evansville"
DEFAULT_SHIPPING_COUNTRY = "US"
DEFAULT_SHIPPING_CARRIER = "usps"


def _get_lowest_shipping_rate(shipping_rates: List[Dict]) -> Optional[Dict]:
    """Extract the lowest shipping rate from rate list."""
    if not shipping_rates:
        return None
    return min(shipping_rates, key=lambda rate: rate.get("shipmentCost", 0) + rate.get("otherCost", 0))


@app.command("query")
def search_query(
    query: str = typer.Argument("", help="Search keywords (leave empty for all items)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    page: int = typer.Option(1, "--page", "-p", help="Page number"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Category filter (art, jewelry, clothing, etc.)"),
    sort: str = typer.Option(
        "ending",
        "--sort",
        "-s",
        help="Sort by: ending, newest, oldest, price_low, price_high",
    ),
    listing_type: Optional[str] = typer.Option(
        None,
        "--type",
        help="Listing type: auction or fixed_price",
    ),
    status: str = typer.Option(
        "active",
        "--status",
        help="Listing status: active, completed, or any",
    ),
    price_min: Optional[float] = typer.Option(None, "--min-price", help="Minimum price filter"),
    price_max: Optional[float] = typer.Option(None, "--max-price", help="Maximum price filter"),
):
    """Search for items on Shop The Salvation Army."""
    try:
        client = get_client(require_auth=False)

        search_desc = f"Searching Shop The Salvation Army"
        if category:
            search_desc += f" in {category}"
        if query:
            search_desc += f" for '{query}'"
        print_status(f"{search_desc}...")

        result = client.search(
            query=query,
            category=category,
            page=page,
            sort=sort,
            listing_type=listing_type,
            status=status,
            price_min=price_min,
            price_max=price_max,
        )

        items = result.get("items", [])

        if table:
            if not items:
                print("No results found.")
                raise typer.Exit(0)

            # Format items for table display
            table_data = []
            for item in items:
                table_data.append({
                    "id": item.get("id", ""),
                    "title": _truncate(item.get("title", ""), 50),
                    "price": item.get("price", "N/A"),
                    "bids": item.get("bids", "") or "",
                    "time_left": item.get("time_left", "") or "",
                })

            print_status(f"Found {len(items)} items on page {page}")
            print_table(
                table_data,
                ["id", "title", "price", "bids", "time_left"],
                ["ID", "Title", "Price", "Bids", "Time Left"],
            )
        else:
            # JSON output - include metadata
            print_json(result)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("categories")
def list_categories():
    """List available categories."""
    try:
        client = get_client(require_auth=False)
        categories = client.list_categories()

        # Display as table
        print_table(
            categories,
            ["name", "id"],
            ["Category", "ID"],
        )

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def search_get(
    item_id: str = typer.Argument(..., help="Item listing ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific item."""
    try:
        client = get_client(require_auth=False)

        print_status(f"Fetching item {item_id}...")

        item = client.get_item(item_id)
        has_bin = item.get("buy_it_now_price") is not None and item.get("buy_it_now_price") > 0
        item["available"] = item.get("auction_status", "active") != "ended" or has_bin
        if item.get("shipping_params"):
            shipping_rates = client.calculate_shipping(
                item_id=item_id,
                zip_code=DEFAULT_SHIPPING_ZIP,
                state=DEFAULT_SHIPPING_STATE,
                city=DEFAULT_SHIPPING_CITY,
                country=DEFAULT_SHIPPING_COUNTRY,
                carrier=DEFAULT_SHIPPING_CARRIER,
                shipping_params=item["shipping_params"],
            )
            lowest = _get_lowest_shipping_rate(shipping_rates)
            if lowest:
                shipping_cost = lowest.get("shipmentCost", 0)
                handling_cost = lowest.get("otherCost", 0)
                shipping_total = shipping_cost + handling_cost
                item["shipping_quote_status"] = "quoted"
                item["shipping_cost"] = shipping_cost
                item["handling_cost"] = handling_cost
                item["shipping_total"] = shipping_total
                item["shipping_price"] = shipping_total
                item["shipping_service"] = lowest.get("serviceName")
                item["shipping_carrier"] = lowest.get("carrierCode", DEFAULT_SHIPPING_CARRIER.upper())
                item_price = item.get("buy_it_now_price") if has_bin else item.get("current_price")
                if item_price is not None:
                    item["total_price"] = round(item_price + shipping_total, 2)

        if table:
            # Format key details for table
            table_data = [{
                "field": "Item ID",
                "value": str(item.get("id", "")),
            }, {
                "field": "Title",
                "value": item.get("title", ""),
            }, {
                "field": "Price",
                "value": item.get("price", "N/A"),
            }, {
                "field": "Bids",
                "value": item.get("bids", "") or "N/A",
            }, {
                "field": "Time Left",
                "value": item.get("time_left", "") or "N/A",
            }, {
                "field": "Description",
                "value": _truncate(item.get("description", ""), 100),
            }, {
                "field": "URL",
                "value": item.get("url", ""),
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


COMMAND_CREDENTIALS = {
    "categories": [
        "no_auth"
    ],
    "get": [
        "no_auth"
    ],
    "query": [
        "no_auth"
    ]
}
