"""Inventory commands for Bricklink CLI."""
COMMAND_CREDENTIALS = {
    "create": ["oauth"],
    "delete": ["oauth"],
    "get": ["oauth"],
    "list": ["oauth"],
    "search": ["oauth"],
    "stats": ["oauth"],
    "stockroom": ["oauth"],
    "update": ["oauth"],
    "update-qty": ["oauth"],
}

import typer
from typing import Optional, List

from ..client import get_client
from ..display import print_detail, print_list
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit
from cli_tools_shared.output import print_json, print_table, print_error, print_success, handle_error

app = typer.Typer(help="Manage store inventory", no_args_is_help=True)


# ==================== Helpers ====================


def _item_display(item_dict: Optional[dict]) -> str:
    """Format an item dict as 'no - name' for table display."""
    if not item_dict:
        return ""
    no = item_dict.get("no", "")
    name = item_dict.get("name", "")
    if no and name:
        return f"{no} - {name}"
    return no or name or ""


def _prepare_table_rows(data: list) -> list:
    """Add a flat 'item' string column for table display."""
    rows = []
    for entry in data:
        row = dict(entry)
        row["item"] = _item_display(entry.get("item"))
        rows.append(row)
    return rows


TABLE_COLUMNS = ["inventory_id", "item", "color_name", "quantity", "unit_price", "new_or_used"]
TABLE_HEADERS = ["ID", "Item", "Color", "Qty", "Price", "Cond"]


# ==================== Commands ====================


@app.command("list")
def inventory_list(
    type: Optional[str] = typer.Option(None, "--type", help="Item type (PART,SET,MINIFIG,etc.)"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Status (Y=available,S=stockroomA,B,C,N=unavailable,R=reserved)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Fields to include"),
):
    """
    List store inventories.

    Examples:
        bricklink inventory list
        bricklink inventory list --type PART
        bricklink inventory list --status Y --limit 50
        bricklink inventory list --table
        bricklink inventory list --filter "quantity:gt:5"
        bricklink inventory list --properties "inventory_id,quantity,unit_price"
    """
    try:
        client = get_client()
        inventories = client.list_inventories(item_type=type, status=status)

        data = list(inventories)

        # Apply client-side filters
        if filter:
            data = apply_filters(data, filter)

        # Apply properties selection
        if properties:
            data = apply_properties_filter(data, properties)

        # Apply limit
        data = apply_limit(data, limit)

        if not properties:
            data = _prepare_table_rows(data)
        print_list(data, table, properties, TABLE_COLUMNS, TABLE_HEADERS)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def inventory_get(
    inventory_id: str = typer.Argument(..., help="Inventory ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get inventory item by ID.

    Examples:
        bricklink inventory get 123456
        bricklink inventory get 123456 --table
    """
    try:
        client = get_client()
        result = client.get_inventory(inventory_id)
        print_detail(result, table)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("stats")
def inventory_stats(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get inventory statistics.

    Computes totals for lots, items, and value across all available inventory,
    broken down by item type.

    Examples:
        bricklink inventory stats
        bricklink inventory stats --table
    """
    try:
        client = get_client()
        inventories = client.list_inventories(status="Y")

        # Compute stats
        total_lots = 0
        total_items = 0
        total_value = 0.0
        by_type: dict = {}

        for inv in inventories:
            item_obj = inv.get("item", {}) or {}
            item_type = item_obj.get("type", "UNKNOWN")
            qty = inv.get("quantity", 0) or 0
            price = float(inv.get("unit_price", "0") or "0")
            line_value = qty * price

            total_lots += 1
            total_items += qty
            total_value += line_value

            if item_type not in by_type:
                by_type[item_type] = {"lots": 0, "items": 0, "value": 0.0}
            by_type[item_type]["lots"] += 1
            by_type[item_type]["items"] += qty
            by_type[item_type]["value"] += line_value

        stats = {
            "total_lots": total_lots,
            "total_items": total_items,
            "total_value": round(total_value, 2),
            "by_type": by_type,
        }

        if table:
            summary = {
                "total_lots": stats["total_lots"],
                "total_items": stats["total_items"],
                "total_value": f"${stats['total_value']:.2f}",
            }
            print_table(
                [summary],
                ["total_lots", "total_items", "total_value"],
                ["Total Lots", "Total Items", "Total Value"],
            )
            if stats.get("by_type"):
                type_rows = []
                for type_name, type_data in stats["by_type"].items():
                    type_rows.append({
                        "type": type_name,
                        "lots": type_data["lots"],
                        "items": type_data["items"],
                        "value": f"${type_data['value']:.2f}",
                    })
                print_table(
                    type_rows,
                    ["type", "lots", "items", "value"],
                    ["Type", "Lots", "Items", "Value"],
                    title="By Type",
                )
        else:
            print_json(stats)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def inventory_update(
    inventory_id: str = typer.Argument(..., help="Inventory ID"),
    price: Optional[str] = typer.Option(None, "--price", help="New unit price"),
    quantity: Optional[str] = typer.Option(None, "--quantity", "-q", help="Quantity change (+5, -3, or absolute with --absolute-qty)"),
    absolute_qty: bool = typer.Option(False, "--absolute-qty", help="Treat quantity as absolute value"),
    sale: Optional[int] = typer.Option(None, "--sale", help="Sale percentage (0-99)"),
    remarks: Optional[str] = typer.Option(None, "--remarks", help="Remarks/notes (typically location)"),
    stockroom: Optional[str] = typer.Option(None, "--stockroom", help="Move to stockroom (A, B, C, or 'none' to remove)"),
):
    """
    Update an inventory item.

    Examples:
        bricklink inventory update 123456 --price 0.15
        bricklink inventory update 123456 --quantity +5
        bricklink inventory update 123456 --quantity -3
        bricklink inventory update 123456 --quantity 10 --absolute-qty
        bricklink inventory update 123456 --sale 20
        bricklink inventory update 123456 --remarks G-0283
        bricklink inventory update 123456 --stockroom A
        bricklink inventory update 123456 --stockroom none
    """
    try:
        client = get_client()
        updates: dict = {}

        if price is not None:
            updates["unit_price"] = price

        if quantity is not None:
            if absolute_qty:
                # Bypass cache for accurate delta computation
                current = client._make_request("GET", f"/inventories/{inventory_id}")
                current_qty = current.get("quantity", 0) or 0
                target_qty = int(quantity)
                delta = target_qty - current_qty
                updates["quantity"] = delta
            else:
                updates["quantity"] = int(quantity)

        if sale is not None:
            updates["sale_rate"] = sale

        if remarks is not None:
            updates["remarks"] = remarks

        if stockroom is not None:
            if stockroom.lower() == "none":
                updates["is_stock_room"] = False
                updates["stock_room_id"] = ""
            else:
                updates["is_stock_room"] = True
                updates["stock_room_id"] = stockroom.upper()

        if not updates:
            print_error("No updates specified")
            raise typer.Exit(1)

        result = client.update_inventory(inventory_id, updates)
        print_success(f"Inventory {inventory_id} updated")
        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update-qty")
def inventory_update_qty(
    input_file: Optional[str] = typer.Option(None, "--input", help="JSON file with items"),
    stdin: bool = typer.Option(False, "--stdin", help="Read from stdin"),
    set_qty: bool = typer.Option(False, "--set-qty", help="Set absolute quantity"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without executing"),
    concurrency: int = typer.Option(5, "--concurrency", help="Max parallel operations"),
    delay: int = typer.Option(0, "--delay", help="Delay between requests (ms)"),
):
    """
    Bulk update inventory quantities.

    Expects input as JSON array of objects with inventory_id and quantity fields.
    By default, quantity is treated as a relative change (+/-). Use --set-qty for absolute.

    Examples:
        bricklink inventory update-qty --input items.json
        bricklink inventory update-qty --stdin < items.json
        bricklink inventory update-qty --input items.json --set-qty
        bricklink inventory update-qty --input items.json --dry-run
        echo '[{"inventory_id":123,"quantity":5}]' | bricklink inventory update-qty --stdin
    """
    try:
        from cli_tools_shared.bulk import BulkProcessor

        processor = BulkProcessor(concurrency=concurrency, delay=delay)
        items = processor.parse_input(file=input_file, stdin=stdin)

        if dry_run:
            print_json({"dry_run": True, "items": items, "set_qty": set_qty})
            return

        client = get_client()

        def _update_item(item: dict, index: int):
            inv_id = item.get("inventory_id")
            qty = item.get("quantity")
            if inv_id is None or qty is None:
                raise ValueError(f"Item at index {index} missing inventory_id or quantity")

            if set_qty:
                # Bypass cache for accurate delta computation
                current = client._make_request("GET", f"/inventories/{inv_id}")
                current_qty = current.get("quantity", 0) or 0
                delta = int(qty) - current_qty
                return client.update_inventory(inv_id, {"quantity": delta})
            else:
                return client.update_inventory(inv_id, {"quantity": int(qty)})

        result = processor.process(items, _update_item)
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def inventory_create(
    type: Optional[str] = typer.Argument(None, help="Item type (PART,SET,MINIFIG)"),
    item_no: Optional[str] = typer.Argument(None, help="Item number"),
    color: Optional[int] = typer.Option(None, "--color", "-c", help="Color ID"),
    quantity: Optional[int] = typer.Option(None, "--quantity", "-q", help="Quantity"),
    price: Optional[str] = typer.Option(None, "--price", help="Unit price"),
    condition: Optional[str] = typer.Option(None, "--condition", help="N=new, U=used"),
    remarks: Optional[str] = typer.Option(None, "--remarks", "-r", help="Remarks"),
    input_file: Optional[str] = typer.Option(None, "--input", help="JSON file for bulk create"),
    stdin: bool = typer.Option(False, "--stdin", help="Read from stdin"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without executing"),
):
    """
    Create inventory item(s).

    Single item: provide type, item_no, and options.
    Bulk: provide --input or --stdin with JSON array.

    Examples:
        bricklink inventory create PART 3001 --color 11 --quantity 10 --price 0.05 --condition N
        bricklink inventory create --input items.json
        bricklink inventory create --stdin < items.json
        bricklink inventory create PART 3001 --color 11 --quantity 5 --price 0.10 --condition N --dry-run
    """
    try:
        client = get_client()

        if input_file or stdin:
            # Bulk create from file or stdin
            from cli_tools_shared.bulk import BulkProcessor

            processor = BulkProcessor(concurrency=1, delay=0)
            items = processor.parse_input(file=input_file, stdin=stdin)

            if dry_run:
                print_json({"dry_run": True, "items": items})
                return

            result = client.create_inventory(items)
            print_success(f"Created {len(items)} inventory item(s)")
            print_json(result)
        else:
            # Single item creation
            if not type or not item_no:
                print_error("Item type and item number are required for single item creation")
                raise typer.Exit(1)

            entry: dict = {
                "item": {
                    "no": item_no,
                    "type": type.upper(),
                },
                "quantity": quantity or 1,
                "unit_price": price or "0",
                "new_or_used": (condition or "N").upper(),
            }

            if color is not None:
                entry["color_id"] = color

            if remarks is not None:
                entry["remarks"] = remarks

            if dry_run:
                print_json({"dry_run": True, "items": [entry]})
                return

            result = client.create_inventory([entry])
            print_success("Inventory item created")
            print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def inventory_delete(
    inventory_id: str = typer.Argument(..., help="Inventory ID"),
):
    """
    Delete an inventory item.

    Examples:
        bricklink inventory delete 123456
    """
    try:
        client = get_client()
        result = client.delete_inventory(inventory_id)
        print_success(f"Inventory {inventory_id} deleted")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def inventory_search(
    part_no: str = typer.Argument(..., help="Part number to search for"),
    color: Optional[int] = typer.Option(None, "--color", "-c", help="Filter by color ID"),
    type: Optional[str] = typer.Option(None, "--type", help="Filter by item type"),
    condition: Optional[str] = typer.Option(None, "--condition", "-n", help="Filter by condition (N=new, U=used)"),
    prefix: bool = typer.Option(False, "--prefix", help="Match items starting with part_no (e.g., 2495 matches 2495c01)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Search inventory by part number.

    Fetches all inventories and filters client-side by item number.

    Examples:
        bricklink inventory search 3001
        bricklink inventory search 3001 --color 11
        bricklink inventory search 3001 --type PART
        bricklink inventory search 3001 --condition U
        bricklink inventory search 3001 --table
        bricklink inventory search 2495 --prefix
    """
    try:
        client = get_client()
        inventories = client.list_inventories(item_type=type)

        # Filter by part number (and optionally color, condition) client-side
        matches = []
        for inv in inventories:
            item_obj = inv.get("item", {}) or {}
            item_no = item_obj.get("no", "")
            if prefix:
                if not item_no.startswith(part_no):
                    continue
            else:
                if item_no != part_no:
                    continue
            if color is not None and inv.get("color_id") != color:
                continue
            if condition is not None and inv.get("new_or_used") != condition.upper():
                continue
            matches.append(inv)

        data = list(matches)

        if table:
            rows = _prepare_table_rows(data)
            print_table(rows, TABLE_COLUMNS, TABLE_HEADERS)
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("stockroom")
def inventory_stockroom(
    room: Optional[str] = typer.Option(None, "--room", help="Stockroom ID (A, B, or C)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Max results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Fields to include"),
):
    """
    List stockroom items.

    Shows items in stockroom A, B, C, or all stockrooms.

    Examples:
        bricklink inventory stockroom
        bricklink inventory stockroom --room A
        bricklink inventory stockroom --room B --table
        bricklink inventory stockroom --limit 20
    """
    try:
        # Map room letter to Bricklink status code
        room_map = {"A": "S", "B": "B", "C": "C"}

        if room:
            status = room_map.get(room.upper())
            if not status:
                print_error(f"Invalid stockroom '{room}'. Use A, B, or C.")
                raise typer.Exit(1)
        else:
            # All stockrooms
            status = "S,B,C"

        client = get_client()
        inventories = client.list_inventories(status=status)

        data = list(inventories)

        # Apply client-side filters
        if filter:
            data = apply_filters(data, filter)

        # Apply properties selection
        if properties:
            data = apply_properties_filter(data, properties)

        # Apply limit
        data = apply_limit(data, limit)

        if not properties:
            data = _prepare_table_rows(data)
        print_list(data, table, properties, TABLE_COLUMNS, TABLE_HEADERS)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
