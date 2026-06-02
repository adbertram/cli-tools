"""Inventory commands for Brickowl CLI."""
COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
    "search": ["api_key"],
    "stats": ["api_key"],
    "update": ["api_key"],
    "delete": ["api_key"],
}

import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_error, print_success, print_info, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit

app = typer.Typer(help="Manage Brick Owl inventory", no_args_is_help=True)


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
def inventory_list(
    type: Optional[str] = typer.Option(None, "--type", help="Filter by item type (Part, Set, Minifigure, etc.)"),
    all: bool = typer.Option(False, "--all", help="Include inactive lots (default: active only)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of lots to return"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List inventory lots.

    Examples:
        brickowl inventory list
        brickowl inventory list --type Part
        brickowl inventory list --all --limit 50
        brickowl inventory list --table
        brickowl inventory list --filter "qty:gt:5"
        brickowl inventory list --properties "lot_id,name,qty,price"
    """
    try:
        client = get_client()
        lots = client.list_inventory(
            item_type=type,
            active_only=not all,
        )

        # Convert to dicts for filtering
        data = _to_dicts(lots)

        # Apply client-side filters
        if filter:
            data = apply_filters(data, filter)

        # Apply limit
        if limit:
            data = apply_limit(data, limit)

        # Apply properties selection
        if properties:
            data = _apply_properties(data, properties)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(data, fields, fields)
            else:
                print_table(
                    data,
                    ["lot_id", "boid", "name", "qty", "price", "condition"],
                    ["Lot ID", "BOID", "Name", "Qty", "Price", "Condition"],
                )
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def inventory_get(
    lot_id: str = typer.Argument(..., help="The lot ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific inventory lot.

    Examples:
        brickowl inventory get 12345678
        brickowl inventory get 12345678 --table
    """
    try:
        client = get_client()
        lot = client.get_inventory_lot(lot_id)

        if lot is None:
            print_error(f"Lot {lot_id} not found")
            raise typer.Exit(1)

        if table:
            lot_dict = lot.model_dump(mode="json")
            rows = [{"field": k, "value": str(v)} for k, v in lot_dict.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(lot)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def inventory_search(
    part_no: str = typer.Argument(..., help="Part number to search for (design ID, BL item no, etc.)"),
    color: Optional[int] = typer.Option(None, "--color", "-c", help="Filter by Brick Owl color ID"),
    type: Optional[str] = typer.Option("Part", "--type", help="Item type (Part, Set, Minifigure, etc.)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Search inventory for a part by number.

    Looks up the part via catalog ID, then filters your inventory lots
    matching that item. Returns bricklink-compatible output format.

    Examples:
        brickowl inventory search 3063
        brickowl inventory search 3063 --color 38
        brickowl inventory search 2420 --table
        brickowl inventory search 3001 --type Part
    """
    try:
        client = get_client()
        result = client.search_inventory(part_no, item_type=type, color_id=color)
        data = result.get("results", [])

        if table:
            if data:
                print_table(
                    data,
                    ["lot_id", "color_name", "quantity", "unit_price", "remarks", "new_or_used"],
                    ["Lot ID", "Color", "Qty", "Price", "Location", "Cond"],
                )
            else:
                print_info("No matching lots found")
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("stats")
def inventory_stats(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Show inventory statistics.

    Computes totals for lots, items, and value across all active inventory.

    Examples:
        brickowl inventory stats
        brickowl inventory stats --table
    """
    try:
        client = get_client()
        stats = client.get_inventory_stats()

        if table:
            stats_dict = stats.model_dump(mode="json")
            # Show summary row
            summary = {
                "total_lots": stats_dict["total_lots"],
                "total_items": stats_dict["total_items"],
                "total_value": f"${stats_dict['total_value']:.2f}",
            }
            print_table(
                [summary],
                ["total_lots", "total_items", "total_value"],
                ["Total Lots", "Total Items", "Total Value"],
            )
            # Show breakdown by type
            if stats_dict.get("by_type"):
                type_rows = []
                for type_name, type_data in stats_dict["by_type"].items():
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
    lot_id: str = typer.Argument(..., help="The lot ID to update"),
    price: Optional[float] = typer.Option(None, "--price", help="Set price"),
    quantity: Optional[int] = typer.Option(None, "--quantity", "-q", help="Set absolute quantity"),
    adjust: Optional[int] = typer.Option(None, "--adjust", help="Adjust quantity (positive or negative)"),
    sale: Optional[int] = typer.Option(None, "--sale", help="Set sale percentage (0 to remove)"),
    hide: bool = typer.Option(False, "--hide", help="Hide lot (set for_sale=0)"),
    show: bool = typer.Option(False, "--show", help="Show lot (set for_sale=1)"),
):
    """
    Update an inventory lot.

    Examples:
        brickowl inventory update LOT_ID --price 1.50
        brickowl inventory update LOT_ID --quantity 10
        brickowl inventory update LOT_ID --adjust -2
        brickowl inventory update LOT_ID --sale 20
        brickowl inventory update LOT_ID --hide
        brickowl inventory update LOT_ID --show
    """
    try:
        client = get_client()

        # Determine for_sale flag
        for_sale = None
        if hide:
            for_sale = False
        elif show:
            for_sale = True

        result = client.update_inventory(
            lot_id=lot_id,
            price=price,
            absolute_quantity=quantity,
            relative_quantity=adjust,
            sale_percent=sale,
            for_sale=for_sale,
        )
        print_success(f"Lot {lot_id} updated")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def inventory_delete(
    lot_id: str = typer.Argument(..., help="The lot ID to delete"),
):
    """
    Delete an inventory lot.

    Examples:
        brickowl inventory delete LOT_ID
    """
    try:
        client = get_client()
        result = client.delete_inventory(lot_id=lot_id)
        print_success(f"Lot {lot_id} deleted")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
