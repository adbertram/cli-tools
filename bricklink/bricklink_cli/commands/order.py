"""Order commands for Bricklink CLI."""
COMMAND_CREDENTIALS = {
    "file": ["oauth"],
    "get": ["oauth", "browser_session"],
    "items": ["oauth"],
    "list": ["oauth"],
    "search": ["browser_session"],
    "ship": ["oauth"],
    "update-status": ["oauth"],
}

import typer
from typing import Optional, List

from ..client import get_client
from ..display import print_detail, print_list
from ..models import is_shipped_status, is_not_picked_status
from .messages import _normalize_api_message
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit, get_nested_value
from cli_tools_shared.output import print_json, print_table, print_error, print_success, handle_error
from . import run_browser

app = typer.Typer(help="Manage orders", no_args_is_help=True)


# ==================== Default Table Columns ====================

ORDER_LIST_COLUMNS = ["order_id", "date_ordered", "buyer_name", "status", "shipped"]
ORDER_LIST_HEADERS = ["Order ID", "Date Ordered", "Buyer", "Status", "Shipped"]

ORDER_ITEMS_COLUMNS = ["inventory_id", "item.no", "item.name", "color_name", "quantity", "unit_price"]
ORDER_ITEMS_HEADERS = ["Inv ID", "Item No", "Name", "Color", "Qty", "Price"]


# ==================== Helpers ====================


def _flatten_order_items(batches: list) -> list:
    """Flatten nested batch lists into a single item list.

    The Bricklink API returns order items as [[batch1_items], [batch2_items]].
    This flattens them into a single list of item dicts.
    """
    items = []
    for batch in batches:
        if isinstance(batch, list):
            items.extend(batch)
        else:
            items.append(batch)
    return items


def _flatten_nested_keys(items: list, columns: list) -> list:
    """Flatten nested dot-notation keys into top-level dict keys for table display."""
    result = []
    for item in items:
        row = {}
        if isinstance(item, dict):
            row.update(item)
        for col in columns:
            if "." in col and col not in row:
                row[col] = get_nested_value(item, col)
        result.append(row)
    return result


# ==================== Commands ====================


@app.command("list")
def order_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (e.g., PAID,PACKED)"),
    direction: Optional[str] = typer.Option(None, "--direction", "-d", help="'in' (received) or 'out' (placed)"),
    filed: Optional[bool] = typer.Option(None, "--filed", help="Filter by filed status"),
    shipped: Optional[bool] = typer.Option(None, "--shipped", help="Filter shipped orders"),
    not_shipped: Optional[bool] = typer.Option(None, "--not-shipped", help="Filter not shipped orders"),
    not_picked: Optional[bool] = typer.Option(None, "--not-picked", help="Filter not picked orders"),
    include_messages: bool = typer.Option(False, "--include-messages", help="Include order messages (API-based)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Fields to include"),
):
    """
    List orders with optional filters.

    Examples:
        bricklink order list
        bricklink order list --status PAID,PACKED
        bricklink order list --direction in --not-shipped
        bricklink order list --not-picked --table
        bricklink order list --include-messages
        bricklink order list --filter "buyer_name:contains:John" --limit 10
        bricklink order list --properties "order_id,status,buyer_name"
    """
    try:
        client = get_client()
        raw_orders = client.list_orders(direction=direction, status=status, filed=filed)

        orders = [
            {**o, "shipped": is_shipped_status(o.get("status", ""))}
            for o in raw_orders
        ]

        # Apply client-side shipped/not_shipped/not_picked filters
        if shipped:
            orders = [o for o in orders if o["shipped"]]
        elif not_shipped:
            orders = [o for o in orders if not o["shipped"]]

        if not_picked:
            orders = [o for o in orders if is_not_picked_status(o.get("status", ""))]

        data = orders

        # Apply standard filters
        if filter:
            data = apply_filters(data, filter)

        # Apply properties selection
        if properties:
            data = apply_properties_filter(data, properties)

        # Apply limit
        if limit:
            data = apply_limit(data, limit)

        # Fetch messages for each order if requested
        if include_messages:
            for order_data in data:
                oid = order_data.get("order_id")
                if oid:
                    raw_msgs = client.get_order_messages(str(oid))
                    order_data["messages"] = [_normalize_api_message(m, str(oid)) for m in raw_msgs]

        print_list(data, table, properties, ORDER_LIST_COLUMNS, ORDER_LIST_HEADERS)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def order_get(
    order_id: str = typer.Argument(..., help="Order ID"),
    include_messages: bool = typer.Option(False, "--include-messages", help="Include order messages (API-based)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get order details by ID.

    Examples:
        bricklink order get 12345678
        bricklink order get 12345678 --include-messages
        bricklink order get 12345678 --table
    """
    try:
        client = get_client()
        raw_order = client.get_order(order_id)
        messages = None
        if include_messages:
            raw_msgs = client.get_order_messages(order_id)
            messages = [_normalize_api_message(m, order_id) for m in raw_msgs]
        
        nss_alert = None
        if raw_order.get("status", "") == "NSS":
            nss_alert = run_browser(lambda browser: browser.get_nss_alert(order_id))

        order = {
            **raw_order,
            "shipped": is_shipped_status(raw_order.get("status", "")),
            "messages": messages,
            "nss_alert": nss_alert,
        }

        print_detail(order, table)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("items")
def order_items(
    order_id: str = typer.Argument(..., help="Order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Fields to include"),
):
    """
    Get items in an order.

    The API returns items in nested batch lists. This command flattens
    them into a single list.

    Examples:
        bricklink order items 12345678
        bricklink order items 12345678 --table
        bricklink order items 12345678 --filter "quantity:gte:2"
        bricklink order items 12345678 --properties "item.no,item.name,quantity"
    """
    try:
        client = get_client()
        raw_batches = client.get_order_items(order_id)

        # Flatten nested batch lists: [[batch1_items], [batch2_items]] -> [items]
        raw_items = _flatten_order_items(raw_batches)

        data = raw_items

        # Apply standard filters
        if filter:
            data = apply_filters(data, filter)

        # Apply properties selection
        if properties:
            data = apply_properties_filter(data, properties)

        # Apply limit
        if limit:
            data = apply_limit(data, limit)

        if table and not properties:
            # Flatten nested keys for table display (e.g., item.no, item.name)
            data = _flatten_nested_keys(data, ORDER_ITEMS_COLUMNS)
        print_list(data, table, properties, ORDER_ITEMS_COLUMNS, ORDER_ITEMS_HEADERS)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update-status")
def order_update_status(
    order_id: str = typer.Argument(..., help="Order ID"),
    status: str = typer.Argument(..., help="New status (PENDING,UPDATED,PROCESSING,READY,PAID,PACKED,SHIPPED,RECEIVED,COMPLETED)"),
):
    """
    Update order status.

    Valid statuses: PENDING, UPDATED, PROCESSING, READY, PAID, PACKED,
    SHIPPED, RECEIVED, COMPLETED, OCR, NPB, NPX, NRS, NSS, CANCELLED

    Examples:
        bricklink order update-status 12345678 PACKED
        bricklink order update-status 12345678 SHIPPED
    """
    try:
        client = get_client()
        result = client.update_order_status(order_id, status.upper())
        print_success(f"Order {order_id} status updated to {status.upper()}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("ship")
def order_ship(
    order_id: str = typer.Argument(..., help="Order ID"),
    tracking: Optional[str] = typer.Option(None, "--tracking", help="Tracking number"),
    link: Optional[str] = typer.Option(None, "--link", help="Tracking URL"),
):
    """
    Mark order as shipped, optionally with tracking info.

    Updates shipping details first (if provided), then sets status to SHIPPED.

    Examples:
        bricklink order ship 12345678
        bricklink order ship 12345678 --tracking 9400111899223456789012
        bricklink order ship 12345678 --tracking 9400111899223456789012 --link "https://tools.usps.com/go/TrackConfirmAction?tLabels=9400111899223456789012"
    """
    try:
        client = get_client()
        result = client.mark_shipped(order_id, tracking_no=tracking, tracking_link=link)
        msg = f"Order {order_id} marked as shipped"
        if tracking:
            msg += f" with tracking {tracking}"
        print_success(msg)
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("file")
def order_file(
    order_id: str = typer.Argument(..., help="Order ID"),
):
    """
    File an order (set is_filed to true).

    Examples:
        bricklink order file 12345678
    """
    try:
        client = get_client()
        result = client.file_order(order_id)
        print_success(f"Order {order_id} filed")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def order_search(
    item_no: str = typer.Argument(..., help="Item number to search for"),
    type: Optional[str] = typer.Option(None, "--type", help="Item type (PART, SET, MINIFIG, etc.)"),
    color: Optional[int] = typer.Option(None, "--color", "-c", help="Color ID"),
    condition: Optional[str] = typer.Option(None, "--condition", help="Condition (N=new, U=used)"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Order status filter"),
    direction: str = typer.Option("out", "--direction", "-d", help="'in' (received) or 'out' (placed)"),
    from_date: Optional[str] = typer.Option(None, "--from", help="From date (MM/DD/YYYY)"),
    to_date: Optional[str] = typer.Option(None, "--to", help="To date (MM/DD/YYYY)"),
    ids_only: bool = typer.Option(False, "--ids-only", help="Output only order IDs"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Search orders by item number (browser-based).

    Finds all orders containing the specified item. Uses browser
    automation since this feature is not available via the API.

    Examples:
        bricklink order search 3001
        bricklink order search 3001 --type PART --color 11
        bricklink order search 3001 --direction in
        bricklink order search 75192 --type SET --table
        bricklink order search 3001 --from "01/01/2024" --to "12/31/2024"
        bricklink order search 3001 --ids-only
    """
    try:
        orders = run_browser(
            lambda browser: browser.search_orders_by_item(
                item_no=item_no,
                item_type=type,
                color_id=color,
                condition=condition,
                status=status,
                from_date=from_date,
                to_date=to_date,
                direction=direction,
            )
        )

        if ids_only:
            ids = [o.get("order_id", "") for o in orders]
            print_json(ids)
        elif table:
            print_table(
                orders,
                ["order_id", "date", "buyer"],
                ["Order ID", "Date", "Buyer"],
            )
        else:
            print_json(orders)

    except Exception as e:
        raise typer.Exit(handle_error(e))
