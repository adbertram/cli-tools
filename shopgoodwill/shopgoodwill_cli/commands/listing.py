"""Listing commands for ShopGoodwill CLI."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
import typer
from ..client import ShopGoodwillClient, ClientError
from ..config import get_config
from cli_tools_shared import FilterMap
from ..output import print_json, print_table, print_error, print_status, handle_error


def _create_search_filter_map() -> FilterMap:
    """Create FilterMap for search command with API parameter translations."""
    fm = FilterMap()

    # Map CLI args to standard filter fields
    fm.add_argument_mapping("min_price", "price", "gte")
    fm.add_argument_mapping("max_price", "price", "lte")
    fm.add_argument_mapping("buy_now", "buy_now", "eq")
    fm.add_argument_mapping("shipping", "shipping", "eq")
    fm.add_argument_mapping("pickup_only", "pickup_only", "eq")
    fm.add_argument_mapping("closed", "closed", "eq")

    # Register API translators
    def translate_price(op: str, val: str) -> dict:
        if op == "gte":
            return {"low_price": float(val)}
        elif op == "lte":
            return {"high_price": float(val)}
        return {}

    def translate_buy_now(op: str, val: str) -> dict:
        return {"buy_now_only": val.lower() == "true"}

    def translate_shipping(op: str, val: str) -> dict:
        return {"shipping_only": val.lower() == "true"}

    def translate_pickup_only(op: str, val: str) -> dict:
        is_pickup = val.lower() == "true"
        if is_pickup:
            return {"pickup_only": True, "shipping_only": False}
        else:
            # Exclude pickup-only items by requesting shipping only
            return {"pickup_only": False, "shipping_only": True}

    def translate_closed(op: str, val: str) -> dict:
        return {"closed_auctions": val.lower() == "true"}

    fm.register_api_translator("price", translate_price)
    fm.register_api_translator("buy_now", translate_buy_now)
    fm.register_api_translator("shipping", translate_shipping)
    fm.register_api_translator("pickup_only", translate_pickup_only)
    fm.register_api_translator("closed", translate_closed)

    return fm

app = typer.Typer(help="Search and view ShopGoodwill listings")


def _get_shipping_info(client: ShopGoodwillClient, item_id: int, seller_id: int) -> Optional[dict]:
    """Calculate shipping for an item using configured address."""
    config = get_config()
    if not config.has_shipping_address():
        return None

    try:
        result = client.calculate_shipping(
            item_id=item_id,
            seller_id=seller_id,
            zip_code=config.shipping_zip,
            country=config.shipping_country,
        )
        return result
    except ClientError:
        return None


@app.command("search")
def listing_search(
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
    pickup_only: bool = typer.Option(False, "--pickup-only", help="Only show pickup-only items (by default, pickup-only items are excluded)"),
    closed: bool = typer.Option(False, "--closed", help="Include closed auctions"),
    include_shipping: bool = typer.Option(
        False, "--include-shipping", help="Calculate shipping cost for each item"
    ),
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

        # Use FilterMap to convert CLI args to API params
        fm = _create_search_filter_map()
        filters = fm.args_to_filters(
            min_price=min_price,
            max_price=max_price,
            buy_now=buy_now if buy_now else None,
            shipping=shipping if shipping else None,
            pickup_only=pickup_only,  # Always pass - False means exclude pickup-only
            closed=closed if closed else None,
        )
        api_params = fm.to_api_params(filters)

        client = ShopGoodwillClient(require_auth=False)
        result = client.search(
            query=query,
            page=page,
            page_size=limit,
            sort_by=sort_by,
            sort_order=sort_order,
            **api_params,
        )

        search_results = result.get("searchResults", {})
        items = search_results.get("items", [])
        total_count = search_results.get("itemCount", 0)

        # API doesn't respect pageSize, so slice results ourselves
        items = items[:limit]

        # Calculate shipping for each item if requested (in parallel)
        if include_shipping:
            config = get_config()
            if not config.has_shipping_address():
                print_error("No shipping address configured. Set SHOPGOODWILL_SHIPPING_ZIP in .env")
                raise typer.Exit(1)

            # Build lookup for items by ID
            items_by_id = {item.get("itemId"): item for item in items}

            # Calculate shipping in parallel
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(
                        _get_shipping_info, client, item.get("itemId"), item.get("sellerId")
                    ): item.get("itemId")
                    for item in items
                }
                for future in as_completed(futures):
                    item_id = futures[future]
                    shipping_info = future.result()
                    if shipping_info and item_id in items_by_id:
                        items_by_id[item_id]["shippingEstimate"] = shipping_info

        if table:
            if not items:
                print("No results found.")
                raise typer.Exit(0)

            # Format items for table display
            table_data = []
            for item in items:
                # Build location from available fields
                city = item.get("sellerCity", "")
                state = item.get("sellerState", "")
                location = f"{city}, {state}".strip(", ") if city or state else "-"

                row = {
                    "id": item.get("itemId", ""),
                    "title": _truncate(item.get("title", ""), 40),
                    "price": f"${item.get('currentPrice', 0):.2f}",
                    "bids": item.get("numBids", 0),
                    "ends": _format_end_time(item.get("endTime", "")),
                    "location": _truncate(location, 20),
                }
                if include_shipping and item.get("shippingEstimate"):
                    estimate = item["shippingEstimate"]
                    ship_total = estimate.get("shippingPrice", 0) + estimate.get("handlingPrice", 0)
                    row["ship"] = f"${ship_total:.2f}"
                    total_price = item.get("currentPrice", 0) + ship_total
                    row["total"] = f"${total_price:.2f}"
                table_data.append(row)

            columns = ["id", "title", "price", "bids", "ends", "location"]
            headers = ["ID", "Title", "Price", "Bids", "Ends", "Location"]
            if include_shipping:
                columns.extend(["ship", "total"])
                headers.extend(["Ship", "Total"])

            print_status(f"Found {total_count} items (showing {len(items)})")
            print_table(table_data, columns, headers)
        else:
            # JSON output - include metadata
            # Add total_price to items with shipping estimates
            if include_shipping:
                for item in items:
                    if item.get("shippingEstimate"):
                        estimate = item["shippingEstimate"]
                        ship_total = estimate.get("shippingPrice", 0) + estimate.get("handlingPrice", 0)
                        item["totalPrice"] = item.get("currentPrice", 0) + ship_total

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
def listing_get(
    item_id: int = typer.Argument(..., help="Item ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    include_shipping: bool = typer.Option(
        False, "--include-shipping", help="Calculate shipping cost"
    ),
):
    """Get detailed information for a specific listing."""
    try:
        client = ShopGoodwillClient(require_auth=False)
        item = client.get_item(item_id)

        # Calculate shipping if requested
        shipping_info = None
        if include_shipping:
            config = get_config()
            if not config.has_shipping_address():
                print_error("No shipping address configured. Set SHOPGOODWILL_SHIPPING_ZIP in .env")
                raise typer.Exit(1)

            shipping_info = _get_shipping_info(client, item_id, item.get("sellerId"))

        if table:
            # Format key details for table
            table_data = [
                {"field": "Item ID", "value": str(item.get("itemId", ""))},
                {"field": "Title", "value": item.get("title", "")},
                {"field": "Current Price", "value": f"${item.get('currentPrice', 0):.2f}"},
                {"field": "Starting Price", "value": f"${item.get('startingPrice', 0):.2f}"},
                {"field": "Bid Increment", "value": f"${item.get('bidIncrement', 0):.2f}"},
                {"field": "Minimum Bid", "value": f"${item.get('minimumBid', 0):.2f}"},
                {"field": "Number of Bids", "value": str(item.get("numberOfBids", 0))},
                {"field": "End Time", "value": item.get("endTime", "")},
                {"field": "Time Remaining", "value": item.get("remainingTime", "")},
                {"field": "Seller", "value": item.get("sellerCompanyName", "")},
                {"field": "Seller ID", "value": str(item.get("sellerId", ""))},
                {"field": "Location", "value": f"{item.get('pickupCity', '')}, {item.get('pickupState', '')} {item.get('pickupZip', '')}"},
                {"field": "Carrier", "value": item.get("sellerShipperName", "")},
                {"field": "Handling", "value": f"${item.get('handlingPrice', 0):.2f}"},
                {"field": "Weight", "value": f"{item.get('displayWeight', 0)} lb"},
                {"field": "Pickup Only", "value": "Yes" if item.get("pickupOnly") else "No"},
                {"field": "Category", "value": " > ".join([c.get("name", "") for c in item.get("categoryBreadCrumbs", [])])},
                {"field": "URL", "value": f"https://shopgoodwill.com/item/{item.get('itemId', '')}"},
            ]

            # Add shipping info if calculated
            if shipping_info:
                ship_price = shipping_info.get("shippingPrice", 0)
                handling = shipping_info.get("handlingPrice", 0)
                ship_total = ship_price + handling
                total_price = item.get("currentPrice", 0) + ship_total
                table_data.extend([
                    {"field": "--- Shipping Estimate ---", "value": ""},
                    {"field": "Shipping", "value": f"${ship_price:.2f}"},
                    {"field": "Handling", "value": f"${handling:.2f}"},
                    {"field": "Total Shipping", "value": f"${ship_total:.2f}"},
                    {"field": "Service", "value": shipping_info.get("serviceDescription", "")},
                    {"field": "--- Total Price ---", "value": ""},
                    {"field": "Total (Price + Shipping)", "value": f"${total_price:.2f}"},
                ])

            print_table(table_data, ["field", "value"], ["Field", "Value"])
        else:
            # JSON output with enhanced structure
            output = {
                "item_id": item.get("itemId"),
                "title": item.get("title"),
                "url": f"https://shopgoodwill.com/item/{item.get('itemId', '')}",
                "pricing": {
                    "current_price": item.get("currentPrice"),
                    "starting_price": item.get("startingPrice"),
                    "bid_increment": item.get("bidIncrement"),
                    "minimum_bid": item.get("minimumBid"),
                    "buy_now_price": item.get("buyNowPrice") if item.get("buyNowPrice") else None,
                },
                "auction": {
                    "num_bids": item.get("numberOfBids"),
                    "end_time": item.get("endTime"),
                    "remaining_time": item.get("remainingTime"),
                    "start_time": item.get("startTime"),
                    "is_closed": item.get("isItemEndTimeExpire", False),
                },
                "description": _strip_html(item.get("description", "")),
                "category": {
                    "id": item.get("categoryId"),
                    "path": [c.get("name") for c in item.get("categoryBreadCrumbs", [])],
                },
                "shipping": {
                    "carrier": item.get("sellerShipperName"),
                    "handling_price": item.get("handlingPrice"),
                    "weight": item.get("displayWeight"),
                    "pickup_only": item.get("pickupOnly", False),
                    "allows_calculation": item.get("allowShippingCalculation", False),
                },
                "pickup": {
                    "address": {
                        "street": item.get("pickupStreet"),
                        "city": item.get("pickupCity"),
                        "state": item.get("pickupState"),
                        "zip": item.get("pickupZip"),
                        "country": item.get("pickupCountry"),
                    },
                    "hours": item.get("pickupHours"),
                    "policy": _strip_html(item.get("pickupPolicy", "")),
                },
                "seller": {
                    "id": item.get("sellerId"),
                    "name": item.get("sellerCompanyName"),
                    "landing_page": item.get("sellerLandingPageName"),
                    "shipping_policy": _strip_html(item.get("shippingPolicy", "")),
                    "customer_service": _strip_html(item.get("sellerCustomerService", "")),
                },
                "images": _parse_images(item.get("imageServer"), item.get("imageUrlString")),
                "bid_history": _format_bid_history(item.get("bidHistory")),
            }

            # Add shipping estimate if calculated
            if shipping_info:
                ship_total = shipping_info.get("shippingPrice", 0) + shipping_info.get("handlingPrice", 0)
                output["shipping_estimate"] = {
                    "shipping_price": shipping_info.get("shippingPrice"),
                    "handling_price": shipping_info.get("handlingPrice"),
                    "total": ship_total,
                    "service": shipping_info.get("serviceDescription"),
                    "carrier": shipping_info.get("carrier"),
                    "destination_zip": get_config().shipping_zip,
                }
                output["total_price"] = item.get("currentPrice", 0) + ship_total

            print_json(output)

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


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    import re
    if not text:
        return ""
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Normalize whitespace
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


def _parse_images(image_server: str, image_url_string: str) -> list:
    """Parse image URLs from server and path string."""
    if not image_server or not image_url_string:
        return []
    paths = image_url_string.split(";")
    return [f"{image_server}{path.replace(chr(92), '/')}" for path in paths if path]


def _format_bid_history(bid_history: dict) -> list:
    """Format bid history for output."""
    if not bid_history:
        return []
    bids = bid_history.get("bidSummary", [])
    return [
        {
            "bidder": bid.get("bidderName"),
            "amount": bid.get("amount"),
            "time": bid.get("time"),
            "is_buy_now": bid.get("buyNow", False),
        }
        for bid in bids
    ]
