"""Listing commands for ShopSalvationArmy CLI."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict
import typer
from ..client import ShopSalvationArmyClient, ClientError, get_client
from ..config import get_config
from cli_tools_shared import FilterMap
from ..output import print_json, print_table, print_error, print_status, handle_error


def _create_search_filter_map() -> FilterMap:
    """Create FilterMap for search command with API parameter translations."""
    fm = FilterMap()

    # Map CLI args to standard filter fields
    fm.add_argument_mapping("min_price", "price", "gte")
    fm.add_argument_mapping("max_price", "price", "lte")
    fm.add_argument_mapping("pickup_only", "pickup_only", "eq")

    # Register API translators
    def translate_price(op: str, val: str) -> dict:
        if op == "gte":
            return {"price_min": float(val)}
        elif op == "lte":
            return {"price_max": float(val)}
        return {}

    def translate_pickup_only(op: str, val: str) -> dict:
        # When pickup_only is False (default), we filter client-side to exclude pickup-only items
        # The Salvation Army site doesn't have a direct API filter for this
        return {"_pickup_only": val.lower() == "true"}

    fm.register_api_translator("price", translate_price)
    fm.register_api_translator("pickup_only", translate_pickup_only)

    return fm


app = typer.Typer(help="Search and view Shop The Salvation Army listings")


def _get_shipping_info(
    client: ShopSalvationArmyClient,
    item_id: str,
    zip_code: str,
    state: str = "TX",
    city: str = "",
    carrier: str = "usps",
    shipping_params: Optional[Dict] = None,
) -> Optional[List[Dict]]:
    """Calculate shipping for an item to a destination zip code."""
    try:
        result = client.calculate_shipping(
            item_id=item_id,
            zip_code=zip_code,
            state=state,
            city=city,
            carrier=carrier,
            shipping_params=shipping_params,
        )
        return result
    except ClientError:
        return None


def _get_lowest_shipping_rate(shipping_rates: List[Dict]) -> Optional[Dict]:
    """Extract the lowest shipping rate from rate list."""
    if not shipping_rates:
        return None

    lowest = None
    lowest_price = float('inf')

    for rate in shipping_rates:
        price = rate.get("shipmentCost", 0)
        if price < lowest_price:
            lowest_price = price
            lowest = rate

    return lowest


@app.command("search")
def listing_search(
    query: str = typer.Argument("", help="Search keywords (leave empty for all items)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    page: int = typer.Option(1, "--page", "-p", help="Page number"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Category filter"),
    min_price: Optional[float] = typer.Option(None, "--min-price", help="Minimum price"),
    max_price: Optional[float] = typer.Option(None, "--max-price", help="Maximum price"),
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
    pickup_only: bool = typer.Option(
        False,
        "--pickup-only",
        help="Only show pickup-only items (by default, pickup-only items are excluded)",
    ),
    include_shipping: bool = typer.Option(
        False, "--include-shipping", "-S", help="Calculate shipping cost for each item (requires --zip)"
    ),
    zip_code: Optional[str] = typer.Option(
        None, "--zip", "-z", help="Destination zip code for shipping (default: 10001)"
    ),
    state: Optional[str] = typer.Option(
        None, "--state", help="Destination state code (default: NY)"
    ),
    city: str = typer.Option(
        "", "--city", help="Destination city name"
    ),
    carrier: str = typer.Option(
        "usps", "--carrier", help="Shipping carrier: usps or ups"
    ),
):
    """Search for items on Shop The Salvation Army."""
    try:
        # Use defaults from config if not provided
        config = get_config()
        if not zip_code:
            zip_code = config.default_zip
        if not state:
            state = config.default_state

        # Use FilterMap to convert CLI args to API params
        fm = _create_search_filter_map()
        filters = fm.args_to_filters(
            min_price=min_price,
            max_price=max_price,
            pickup_only=pickup_only,  # Always pass - False means exclude pickup-only
        )
        api_params = fm.to_api_params(filters)

        # Extract internal filter flags
        filter_pickup_only = api_params.pop("_pickup_only", False)

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
            listing_type=listing_type,
            status=status,
            price_min=api_params.get("price_min"),
            price_max=api_params.get("price_max"),
        )

        items = result.get("items", [])

        # Calculate shipping for each item if zip code provided (in parallel)
        if include_shipping:
            print_status(f"Calculating shipping to {zip_code}...")

            # First, fetch item details to get shipping params (in parallel)
            items_with_params = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(client.get_item, item.get("id")): item
                    for item in items
                }
                for future in as_completed(futures):
                    original_item = futures[future]
                    try:
                        item_details = future.result()
                        # Merge shipping_params into original item
                        original_item["shipping_params"] = item_details.get("shipping_params")
                        items_with_params.append(original_item)
                    except ClientError:
                        # Item doesn't support shipping (pickup only)
                        if filter_pickup_only:
                            items_with_params.append(original_item)

            items = items_with_params

            # Build lookup for items by ID
            items_by_id = {item.get("id"): item for item in items}

            # Calculate shipping in parallel
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(
                        _get_shipping_info,
                        client,
                        item.get("id"),
                        zip_code,
                        state,
                        city,
                        carrier,
                        item.get("shipping_params"),
                    ): item.get("id")
                    for item in items
                    if item.get("shipping_params")  # Only items with shipping params
                }
                for future in as_completed(futures):
                    item_id = futures[future]
                    shipping_rates = future.result()
                    if shipping_rates and item_id in items_by_id:
                        lowest = _get_lowest_shipping_rate(shipping_rates)
                        if lowest:
                            items_by_id[item_id]["shippingEstimate"] = lowest

            # Optionally filter out items without shipping if not requesting pickup-only
            if not filter_pickup_only:
                items = [
                    item for item in items
                    if item.get("shippingEstimate") or item.get("price") == "$0.00"
                ]

        if table:
            if not items:
                print("No results found.")
                raise typer.Exit(0)

            # Format items for table display
            table_data = []
            for item in items:
                row = {
                    "id": item.get("id", ""),
                    "title": _truncate(item.get("title", ""), 40),
                    "price": item.get("price", "N/A"),
                    "bids": item.get("bids", "") or "",
                    "time_left": _format_time_left(item.get("time_left", "")),
                }
                if include_shipping and item.get("shippingEstimate"):
                    estimate = item["shippingEstimate"]
                    ship_cost = estimate.get("shipmentCost", 0)
                    row["ship"] = f"${ship_cost:.2f}"
                    # Calculate total if we can parse the price
                    price_str = item.get("price", "").replace("$", "").replace(",", "")
                    try:
                        current_price = float(price_str)
                        row["total"] = f"${current_price + ship_cost:.2f}"
                    except ValueError:
                        row["total"] = "N/A"
                elif include_shipping:
                    row["ship"] = "N/A"
                    row["total"] = "N/A"
                table_data.append(row)

            columns = ["id", "title", "price", "bids", "time_left"]
            headers = ["ID", "Title", "Price", "Bids", "Time Left"]
            if include_shipping:
                columns.extend(["ship", "total"])
                headers.extend(["Ship", "Total"])

            print_status(f"Found {len(items)} items on page {page}")
            print_table(table_data, columns, headers)
        else:
            # JSON output - include metadata
            if include_shipping:
                for item in items:
                    if item.get("shippingEstimate"):
                        estimate = item["shippingEstimate"]
                        ship_cost = estimate.get("shipmentCost", 0)
                        price_str = item.get("price", "").replace("$", "").replace(",", "")
                        try:
                            current_price = float(price_str)
                            item["totalPrice"] = current_price + ship_cost
                        except ValueError:
                            pass

            output = {
                "page": page,
                "query": query,
                "category": category,
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
def listing_get(
    item_id: str = typer.Argument(..., help="Item ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    include_shipping: bool = typer.Option(
        False, "--include-shipping", "-S", help="Calculate shipping cost (requires --zip)"
    ),
    zip_code: Optional[str] = typer.Option(
        None, "--zip", "-z", help="Destination zip code for shipping (default: 10001)"
    ),
    state: Optional[str] = typer.Option(
        None, "--state", help="Destination state code (default: NY)"
    ),
    city: str = typer.Option(
        "", "--city", help="Destination city name"
    ),
    carrier: str = typer.Option(
        "usps", "--carrier", help="Shipping carrier: usps or ups"
    ),
):
    """Get detailed information for a specific listing."""
    try:
        # Use defaults from config if not provided
        config = get_config()
        if not zip_code:
            zip_code = config.default_zip
        if not state:
            state = config.default_state

        client = get_client(require_auth=False)

        print_status(f"Fetching item {item_id}...")
        item = client.get_item(item_id)

        # Calculate shipping if requested
        shipping_info = None
        if include_shipping:
            try:
                print_status(f"Calculating shipping to {zip_code}...")
                shipping_rates = _get_shipping_info(
                    client,
                    item_id,
                    zip_code,
                    state,
                    city,
                    carrier,
                    item.get("shipping_params"),
                )
                if shipping_rates:
                    shipping_info = _get_lowest_shipping_rate(shipping_rates)
            except ClientError as e:
                print_error(f"Shipping calculation unavailable: {e}")

        if table:
            # Format key details for table
            table_data = [
                {"field": "Item ID", "value": str(item.get("id", ""))},
                {"field": "Title", "value": item.get("title", "")},
                {"field": "Current Price", "value": item.get("price", "N/A")},
                {"field": "Bids", "value": item.get("bids", "") or "N/A"},
                {"field": "Time Left", "value": item.get("time_left", "") or "N/A"},
                {"field": "Description", "value": _truncate(item.get("description", ""), 100)},
                {"field": "URL", "value": item.get("url", "")},
            ]

            # Add shipping info if calculated
            if shipping_info:
                ship_cost = shipping_info.get("shipmentCost", 0)
                service = shipping_info.get("serviceName", "")
                table_data.extend([
                    {"field": "--- Shipping Estimate ---", "value": ""},
                    {"field": "Shipping Cost", "value": f"${ship_cost:.2f}"},
                    {"field": "Service", "value": service},
                ])
                # Calculate total
                price_str = item.get("price", "").replace("$", "").replace(",", "")
                try:
                    current_price = float(price_str)
                    table_data.append({"field": "Total (Price + Shipping)", "value": f"${current_price + ship_cost:.2f}"})
                except ValueError:
                    pass

            print_table(table_data, ["field", "value"], ["Field", "Value"])
        else:
            # JSON output
            output = {
                "id": item.get("id"),
                "title": item.get("title"),
                "price": item.get("price"),
                "bids": item.get("bids"),
                "time_left": item.get("time_left"),
                "description": item.get("description"),
                "url": item.get("url"),
            }

            # Add shipping estimate if calculated
            if shipping_info:
                ship_cost = shipping_info.get("shipmentCost", 0)
                output["shipping_estimate"] = {
                    "cost": ship_cost,
                    "service": shipping_info.get("serviceName"),
                    "carrier": shipping_info.get("carrierCode", "USPS"),
                }
                price_str = item.get("price", "").replace("$", "").replace(",", "")
                try:
                    current_price = float(price_str)
                    output["total_price"] = current_price + ship_cost
                except ValueError:
                    pass

            print_json(output)

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


def _truncate(text: str, max_length: int) -> str:
    """Truncate text to max length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def _format_time_left(time_left: str) -> str:
    """Format time left for display."""
    if not time_left:
        return ""
    # Shorten "X Days HH:MM:SS" to "Xd HH:MM"
    try:
        if "Days" in time_left or "Day" in time_left:
            parts = time_left.split()
            days = parts[0]
            time_part = parts[2] if len(parts) > 2 else ""
            if time_part:
                time_only = time_part[:5]  # HH:MM
                return f"{days}d {time_only}"
            return f"{days}d"
    except (ValueError, IndexError):
        pass
    return time_left[:12] if len(time_left) > 12 else time_left
