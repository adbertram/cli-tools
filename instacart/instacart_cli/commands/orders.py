"""Orders commands for Instacart CLI."""
import json
from typing import List, Optional

import typer
from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.filters import apply_filters, parse_filter_string, validate_filters
from cli_tools_shared.output import handle_error, print_json, print_success, print_table


app = typer.Typer(help="Manage Instacart orders", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            # Handle array index access like "line_items.0.product"
            try:
                idx = int(part)
                value = value[idx] if idx < len(value) else None
            except (ValueError, IndexError):
                return None
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def orders_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(
        100, "--limit", "-l", help="Maximum number of orders to return"
    ),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include (supports dot-notation)",
    ),
    status: Optional[str] = typer.Option(
        None, "--status", help="Filter by order status"
    ),
):
    """
    List orders.

    Examples:
        instacart orders list
        instacart orders list --table
        instacart orders list --limit 10
        instacart orders list --status pending
        instacart orders list --filter "status:eq:delivered"
        instacart orders list --properties "order_id,status,total.value"
    """
    try:
        client = get_client()

        # Build filters
        filters = list(filter) if filter else []
        if status:
            filters.append(f"status:eq:{status}")

        # Returns List[Order] models
        orders = client.list_orders(limit=limit, filters=filters if filters else None)

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            orders = extract_fields(orders, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(orders, fields, fields)
            else:
                # Transform orders for table display with computed fields
                table_rows = []
                for order in orders:
                    order_dict = model_to_dict(order)
                    # Calculate item count from line_items
                    line_items = order_dict.get("line_items", [])
                    item_count = len(line_items)
                    # Format total as currency
                    total = order_dict.get("total", {})
                    if isinstance(total, dict):
                        total_value = total.get("value", 0)
                    else:
                        total_value = getattr(total, "value", 0) if total else 0
                    total_formatted = f"${total_value:.2f}" if total_value else "-"

                    table_rows.append({
                        "order_id": order_dict.get("order_id"),
                        "store_name": order_dict.get("store_name") or "-",
                        "item_count": item_count,
                        "total": total_formatted,
                        "status": order_dict.get("status"),
                        "created_at": order_dict.get("created_at"),
                    })
                # Default table columns for orders
                print_table(
                    table_rows,
                    ["order_id", "store_name", "item_count", "total", "status", "created_at"],
                    ["Order ID", "Store", "Items", "Total", "Status", "Created At"],
                )
        else:
            print_json(orders)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def orders_get(
    order_id: str = typer.Argument(..., help="The order ID"),
    table: bool = typer.Option(
        False, "--table", "-t", help="Display summary as table"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include (supports dot-notation)",
    ),
):
    """
    Get details for a specific order.

    Examples:
        instacart orders get ORDER_ID
        instacart orders get ORDER_ID --table
        instacart orders get ORDER_ID --properties "order_id,status,line_items"
    """
    try:
        client = get_client()
        # Returns OrderDetail model
        order = client.get_order(order_id)

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            order = extract_fields([order], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([order], fields, fields)
            else:
                # Convert model to key-value table
                order_dict = model_to_dict(order)
                rows = [
                    {"field": k, "value": str(v)}
                    for k, v in order_dict.items()
                    if v is not None
                ]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(order)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def orders_create(
    items: str = typer.Option(
        ...,
        "--items",
        help='JSON array of line items: [{"productId":"123","quantity":2}]',
    ),
    address: Optional[str] = typer.Option(
        None,
        "--address",
        help='JSON delivery address: {"street":"123 Main","city":"NYC","state":"NY","zipCode":"10001"}',
    ),
    instructions: Optional[str] = typer.Option(
        None, "--instructions", help="Delivery instructions"
    ),
):
    """
    Create a new order.

    Examples:
        instacart orders create --items '[{"productId":"p123","quantity":2}]'
        instacart orders create --items '[{"productId":"p123","quantity":1}]' --address '{"street":"123 Main St","city":"Seattle","state":"WA","zipCode":"98101"}'
    """
    try:
        # Parse line items JSON
        try:
            line_items = json.loads(items)
        except json.JSONDecodeError as e:
            from cli_tools_shared.output import print_error

            print_error(f"Invalid JSON for --items: {e}")
            raise typer.Exit(1)

        # Build order data
        order_data = {"lineItems": line_items}

        if address:
            try:
                order_data["deliveryAddress"] = json.loads(address)
            except json.JSONDecodeError as e:
                from cli_tools_shared.output import print_error

                print_error(f"Invalid JSON for --address: {e}")
                raise typer.Exit(1)

        if instructions:
            order_data["deliveryInstructions"] = instructions

        client = get_client()
        order = client.create_order(order_data)

        print_json(order)
        print_success(f"Order {order.order_id} created successfully")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("track")
def orders_track(
    order_id: str = typer.Argument(..., help="The order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Track order delivery status.

    Examples:
        instacart orders track ORDER_ID
        instacart orders track ORDER_ID --table
    """
    try:
        client = get_client()
        tracking = client.track_order(order_id)

        if table:
            rows = [
                {"field": k, "value": str(v) if v is not None else "N/A"}
                for k, v in tracking.items()
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(tracking)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "track": [
        "custom"
    ]
}
