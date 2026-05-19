"""Order commands for Brickowl CLI."""
COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
    "items": ["api_key"],
    "status": ["api_key"],
    "ship": ["api_key"],
    "tracking": ["api_key"],
    "note": ["api_key"],
}

import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client, ClientError, ENRICH_FIELDS
from cli_tools_shared.output import print_json, print_table, print_error, print_success, print_info, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit, parse_filter_string
from ..parsers import format_local_time

app = typer.Typer(help="Manage Brick Owl orders", no_args_is_help=True)


# ==================== Helpers ====================


def _extract_field(item: dict, field: str):
    """Extract a nested field using dot notation."""
    parts = field.split(".")
    value = item
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _apply_properties(data, properties_str):
    """Apply field selection to data using dot notation."""
    if not properties_str:
        return data
    fields = [f.strip() for f in properties_str.split(",")]
    if isinstance(data, list):
        return [
            {f: _extract_field(d if isinstance(d, dict) else d.model_dump(mode="json"), f) for f in fields}
            for d in data
        ]
    d = data if isinstance(data, dict) else data.model_dump(mode="json")
    return {f: _extract_field(d, f) for f in fields}


def _to_dicts(data):
    """Convert list of models/dicts to list of dicts."""
    result = []
    for item in data:
        if isinstance(item, BaseModel):
            result.append(item.model_dump(mode="json"))
        elif isinstance(item, dict):
            result.append(item)
        else:
            result.append({"value": item})
    return result


# ==================== Commands ====================


@app.command("list")
def order_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (name, ID, or comma-separated)"),
    type: Optional[str] = typer.Option("store", "--type", help="Order type: 'store' (received) or 'customer' (placed)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of orders to return"),
    sort: Optional[str] = typer.Option(None, "--sort", help="Sort by: 'created' or 'updated'"),
    shipped: bool = typer.Option(False, "--shipped", help="Show only shipped orders"),
    not_shipped: bool = typer.Option(False, "--not-shipped", help="Show only not-shipped orders"),
    not_picked: bool = typer.Option(False, "--not-picked", help="Show only not-picked orders"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List orders from the Brick Owl store.

    Examples:
        brickowl order list
        brickowl order list --status "payment received"
        brickowl order list --status 2,3,4
        brickowl order list --not-picked --table
        brickowl order list --shipped --limit 10
        brickowl order list --filter "buyer_name:contains:John"
        brickowl order list --properties "order_id,status,buyer_name"
    """
    try:
        client = get_client()

        # Resolve shipped flag
        shipped_flag = None
        if shipped:
            shipped_flag = True
        elif not_shipped:
            shipped_flag = False

        # Determine if enrichment is needed by checking whether filters
        # or properties reference fields that only /order/view provides.
        # The default table columns include buyer_name, so enrich by default.
        needs_enrich = True
        if properties:
            # Only enrich if requested properties include enrichment fields
            prop_fields = {f.strip() for f in properties.split(",")}
            needs_enrich = bool(prop_fields & ENRICH_FIELDS)
        if filter:
            # Also enrich if any filter references enrichment fields
            for fs in filter:
                for field, _op, _val in parse_filter_string(fs):
                    if field in ENRICH_FIELDS:
                        needs_enrich = True
        # Default table columns include buyer_name, so enrich unless
        # properties explicitly restricts to non-enrichment fields
        if not properties and not filter:
            needs_enrich = True

        orders = client.list_orders(
            status=status,
            list_type=type or "store",
            limit=limit,
            sort_by=sort,
            shipped=shipped_flag,
            not_picked=not_picked,
            enrich=needs_enrich,
        )

        # Convert to dicts for filtering
        data = _to_dicts(orders)

        # Apply client-side filters
        if filter:
            data = apply_filters(data, filter)

        # Apply limit (client-side, in case API doesn't enforce)
        if limit:
            data = apply_limit(data, limit)

        # Apply properties selection
        if properties:
            data = _apply_properties(data, properties)

        if table:
            # Format timestamps for display
            for item in data:
                if "order_date" in item:
                    item["order_date"] = format_local_time(item["order_date"])
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(data, fields, fields)
            else:
                print_table(
                    data,
                    ["order_id", "order_date", "status", "buyer_name", "base_order_total", "total_lots"],
                    ["Order ID", "Date", "Status", "Buyer", "Total", "Lots"],
                )
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def order_get(
    order_id: str = typer.Argument(..., help="The order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific order.

    Examples:
        brickowl order get 12345678
        brickowl order get 12345678 --table
    """
    try:
        client = get_client()
        order = client.get_order(order_id)

        if table:
            order_dict = order.model_dump(mode="json")
            rows = [{"field": k, "value": str(v)} for k, v in order_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(order)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("items")
def order_items(
    order_id: str = typer.Argument(..., help="The order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get items in an order.

    Examples:
        brickowl order items 12345678
        brickowl order items 12345678 --table
    """
    try:
        client = get_client()
        items = client.get_order_items(order_id)

        if table:
            print_table(
                items,
                ["boid", "name", "color", "ordered_quantity", "base_price", "condition"],
                ["BOID", "Name", "Color", "Qty", "Price", "Condition"],
            )
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("status")
def order_status(
    order_id: str = typer.Argument(..., help="The order ID"),
    status_id: int = typer.Argument(..., help="Status ID (0-8)"),
):
    """
    Set the status of an order.

    Status IDs:
        0 = Pending, 1 = Payment Submitted, 2 = Payment Received,
        3 = Processing, 4 = Processed, 5 = Shipped,
        6 = Received, 7 = On Hold, 8 = Cancelled

    Examples:
        brickowl order status 12345678 4
        brickowl order status 12345678 5
    """
    try:
        client = get_client()
        result = client.set_order_status(order_id, status_id)
        print_success(f"Order {order_id} status set to {status_id}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("ship")
def order_ship(
    order_id: str = typer.Argument(..., help="The order ID"),
    tracking: Optional[str] = typer.Option(None, "--tracking", "-t", help="Tracking number"),
):
    """
    Mark an order as shipped, optionally with tracking.

    Examples:
        brickowl order ship 12345678
        brickowl order ship 12345678 --tracking 9400111899223456789012
    """
    try:
        client = get_client()
        result = client.mark_shipped(order_id, tracking_id=tracking)
        msg = f"Order {order_id} marked as shipped"
        if tracking:
            msg += f" with tracking {tracking}"
        print_success(msg)
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("tracking")
def order_tracking(
    order_id: str = typer.Argument(..., help="The order ID"),
    tracking_id: str = typer.Argument(..., help="Tracking number"),
):
    """
    Add tracking information to an order.

    Examples:
        brickowl order tracking 12345678 9400111899223456789012
    """
    try:
        client = get_client()
        result = client.add_tracking(order_id, tracking_id)
        print_success(f"Tracking {tracking_id} added to order {order_id}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("note")
def order_note(
    order_id: str = typer.Argument(..., help="The order ID"),
    note: str = typer.Argument(..., help="Note text"),
):
    """
    Set seller note on an order.

    Examples:
        brickowl order note 12345678 "Shipped via USPS Priority"
    """
    try:
        client = get_client()
        result = client.update_note(order_id, note)
        print_success(f"Note updated on order {order_id}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
