"""Search commands for ShopSalvationArmy CLI."""
from typing import Dict, List, Optional
import typer
from ..client import get_client, ClientError
from ..output import print_json, print_table, print_status
from cli_tools_shared.output import command

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
@command
def search_query(
    query: str = typer.Argument("", help="Search keywords (leave empty for all items)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    page: int = typer.Option(1, "--page", "-p", help="Page number"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Category filter (art, jewelry, clothing, etc.)"),
    sort: str = typer.Option(
        "newest",
        "--sort",
        "-s",
        help="Sort field: newest (default), price, ending",
    ),
    desc: bool = typer.Option(
        False,
        "--desc",
        "-d",
        help="Reverse the sort field's natural direction (e.g. price high->low). Not supported with 'ending'.",
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
    client = get_client(require_auth=False)

    search_desc = "Searching Shop The Salvation Army"
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
        desc=desc,
        listing_type=listing_type,
        status=status,
        price_min=price_min,
        price_max=price_max,
        limit=limit,
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


@app.command("categories")
@command
def list_categories():
    """List available categories."""
    client = get_client(require_auth=False)
    categories = client.list_categories()

    # Display as table
    print_table(
        categories,
        ["name", "id"],
        ["Category", "ID"],
    )


@app.command("get")
@command
def search_get(
    item_id: str = typer.Argument(..., help="Item listing ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific item."""
    client = get_client(require_auth=False)

    print_status(f"Fetching item {item_id}...")

    item = client.get_item(item_id)
    has_bin = item.get("buy_it_now_price") is not None and item.get("buy_it_now_price") > 0
    item["available"] = item.get("auction_status", "active") != "ended" or has_bin
    if item.get("shipping_params"):
        # The shipping quote is an OPTIONAL secondary request. A failed or
        # unparseable quote must NOT abort the whole `get` -- the item detail
        # (title, price, availability, images, url) was already retrieved
        # successfully. Surface the failure via shipping_quote_status and leave
        # the shipping numeric fields at their null defaults; never fabricate
        # shipping numbers. The item fetch itself (client.get_item above) still
        # fails fast if the ITEM detail request fails.
        try:
            shipping_rates = client.calculate_shipping(
                item_id=item_id,
                zip_code=DEFAULT_SHIPPING_ZIP,
                state=DEFAULT_SHIPPING_STATE,
                city=DEFAULT_SHIPPING_CITY,
                country=DEFAULT_SHIPPING_COUNTRY,
                carrier=DEFAULT_SHIPPING_CARRIER,
                shipping_params=item["shipping_params"],
            )
        except ClientError:
            shipping_rates = None
            item["shipping_quote_status"] = "unavailable"

        lowest = _get_lowest_shipping_rate(shipping_rates) if shipping_rates else None
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
        elif item.get("shipping_quote_status") != "unavailable":
            # Quote request succeeded but returned no usable rate.
            item["shipping_quote_status"] = "unavailable"

    if table:
        # Format key details for table
        table_data = [{
            "field": "Item ID",
            "value": str(item.get("id", "")),
        }, {
            "field": "Title",
            "value": item.get("title", ""),
        }, {
            "field": "Seller",
            "value": item.get("seller_name", "") or "N/A",
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
            "field": "Fulfillment",
            "value": _format_fulfillment(item),
        }, {
            "field": "Description",
            "value": _truncate(item.get("description", ""), 100),
        }, {
            "field": "Images",
            "value": str(len(item.get("image_urls", []))),
        }, {
            "field": "URL",
            "value": item.get("url", ""),
        }]
        print_table(table_data, ["field", "value"], ["Field", "Value"])
    else:
        print_json(item)


def _format_fulfillment(item: Dict) -> str:
    """Render the listing's Shipping Options panel as one readable line.

    Which options exist comes from `shipping_options`; the cost of each is
    reported alongside but never used to decide whether the option is offered.
    """
    options = item["shipping_options"]
    parts = []
    if options["local_pickup"]:
        price = item["local_pickup_price"]
        parts.append(f"local pickup (${price:.2f})" if price is not None else "local pickup")
    if options["flat_rate"]:
        parts.append(f"{item['standard_shipping_label']} (${item['standard_shipping_price']:.2f})")
    if options["carrier_calculator"]:
        carriers = ", ".join(item["shipping_carriers"])
        quoted = item.get("shipping_total")
        priced = f", quoted ${quoted:.2f}" if quoted is not None else ""
        parts.append(f"carrier calculator [{carriers}]{priced}")
    if not parts:
        return "none listed"
    return "; ".join(parts)


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
