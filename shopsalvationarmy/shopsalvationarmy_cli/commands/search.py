"""Search commands for ShopSalvationArmy CLI."""
from typing import Optional
import typer
from ..client import ShopSalvationArmyClient, ClientError, get_client
from ..output import print_json, print_table, print_error, print_status, handle_error

app = typer.Typer(help="Search Shop The Salvation Army listings")


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
        "custom"
    ],
    "get": [
        "custom"
    ],
    "query": [
        "custom"
    ]
}
