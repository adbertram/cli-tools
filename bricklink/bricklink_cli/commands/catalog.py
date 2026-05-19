"""Catalog commands for Bricklink CLI."""
COMMAND_CREDENTIALS = {
    "colors": ["oauth"],
    "get": ["oauth"],
    "item": ["oauth"],
    "list": ["oauth"],
    "minifig": ["oauth"],
    "part": ["oauth"],
    "price": ["oauth"],
    "set": ["oauth"],
    "subsets": ["oauth"],
    "supersets": ["oauth"],
}

import typer
from typing import Optional, List

from ..client import get_client
from ..display import print_detail, print_list
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Browse catalog data", no_args_is_help=True)


def _get_catalog_item(type: str, item_no: str, table: bool = False):
    """Shared implementation for catalog item lookup."""
    client = get_client()
    data = client.get_catalog_item(type, item_no)
    print_detail(data, table)


@app.command("get")
def catalog_get(
    type: str = typer.Argument(..., help="Item type (PART,SET,MINIFIG,BOOK,GEAR,CATALOG,INSTRUCTION)"),
    item_no: str = typer.Argument(..., help="Item number"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get catalog item info by type and item number.

    Examples:
        bricklink catalog get PART 3001
        bricklink catalog get SET 75192-1
        bricklink catalog get MINIFIG sw0001 --table
    """
    try:
        _get_catalog_item(type, item_no, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("item", hidden=True)
def catalog_item(
    type: str = typer.Argument(..., help="Item type (PART,SET,MINIFIG,BOOK,GEAR,CATALOG,INSTRUCTION)"),
    item_no: str = typer.Argument(..., help="Item number"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get catalog item info (alias for 'get').

    Examples:
        bricklink catalog item PART 3001
        bricklink catalog item SET 75192-1
        bricklink catalog item MINIFIG sw0001 --table
    """
    try:
        _get_catalog_item(type, item_no, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def catalog_list(
    item_type: str = typer.Argument(..., help="Item type (PART, SET, MINIFIG, etc.)"),
    keyword: str = typer.Option(None, "--keyword", "-k", help="Search keyword"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    List catalog items by type using store inventory.

    The Bricklink API does not provide a catalog search endpoint.
    This command lists catalog items found in your store inventory,
    filtered by item type. Use 'catalog get' for direct lookups.

    Examples:
        bricklink catalog list PART
        bricklink catalog list SET --limit 10
        bricklink catalog list MINIFIG --table
    """
    try:
        client = get_client()
        raw = client.list_inventories(item_type=item_type.upper())
        # Extract catalog-level info from inventory items
        items = []
        seen = set()
        for inv in raw:
            item_data = inv.get("item", {})
            item_no = item_data.get("no", "")
            if item_no and item_no not in seen:
                seen.add(item_no)
                items.append({
                    "no": item_no,
                    "name": item_data.get("name", ""),
                    "type": item_data.get("type", item_type.upper()),
                    "category_id": item_data.get("category_id"),
                })

        if keyword:
            kw = keyword.lower()
            items = [i for i in items if kw in (i.get("name", "") or "").lower() or kw in (i.get("no", "") or "").lower()]

        data = items

        if filter:
            data = apply_filters(data, filter)
        if properties:
            data = apply_properties_filter(data, properties)
        if limit:
            data = apply_limit(data, limit)

        print_list(data, table, properties,
                   ["no", "name", "type", "category_id"],
                   ["Item No", "Name", "Type", "Category"])

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("part")
def catalog_part(
    part_no: str = typer.Argument(..., help="Part number"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Shortcut to get catalog info for a PART.

    Examples:
        bricklink catalog part 3001
        bricklink catalog part 3001 --table
    """
    try:
        _get_catalog_item("PART", part_no, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("set")
def catalog_set(
    set_no: str = typer.Argument(..., help="Set number"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Shortcut to get catalog info for a SET.

    Examples:
        bricklink catalog set 75192-1
        bricklink catalog set 10294-1 --table
    """
    try:
        _get_catalog_item("SET", set_no, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("minifig")
def catalog_minifig(
    fig_no: str = typer.Argument(..., help="Minifig number"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Shortcut to get catalog info for a MINIFIG.

    Examples:
        bricklink catalog minifig sw0001
        bricklink catalog minifig sh0001 --table
    """
    try:
        _get_catalog_item("MINIFIG", fig_no, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("price")
def catalog_price(
    type: Optional[str] = typer.Argument(None, help="Item type"),
    item_no: Optional[str] = typer.Argument(None, help="Item number"),
    color: Optional[int] = typer.Option(None, "--color", "-c", help="Color ID"),
    condition: Optional[str] = typer.Option(None, "--condition", help="N=new, U=used"),
    sold: bool = typer.Option(False, "--sold", help="Show sold prices instead of stock"),
    country: Optional[str] = typer.Option(None, "--country", help="Country code"),
    region: Optional[str] = typer.Option(None, "--region", help="Region filter"),
    currency: Optional[str] = typer.Option(None, "--currency", help="Currency code"),
    vat: Optional[str] = typer.Option(None, "--vat", help="VAT option (N,Y,O)"),
    input_file: Optional[str] = typer.Option(None, "--input", help="JSON file for bulk"),
    stdin: bool = typer.Option(False, "--stdin", help="Read from stdin"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without executing"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get price guide for an item. Supports bulk via --input or --stdin.

    Single item:
        bricklink catalog price PART 3001
        bricklink catalog price PART 3001 --color 11 --condition N
        bricklink catalog price SET 75192-1 --sold

    Bulk (JSON file with list of {type, item_no, color?, condition?}):
        bricklink catalog price --input items.json
        cat items.json | bricklink catalog price --stdin
    """
    try:
        client = get_client()
        guide_type = "sold" if sold else None

        if input_file or stdin:
            from cli_tools_shared.bulk import BulkProcessor

            processor = BulkProcessor()
            items = processor.parse_input(file=input_file, stdin=stdin)

            if dry_run:
                print_json({"dry_run": True, "items": items, "count": len(items)})
                return

            def _fetch_price(item_data, index):
                return client.get_price_guide(
                    item_type=item_data["type"],
                    item_no=item_data["item_no"],
                    color_id=item_data.get("color"),
                    guide_type=guide_type,
                    condition=item_data.get("condition", condition),
                    country_code=item_data.get("country", country),
                    region=item_data.get("region", region),
                    currency_code=item_data.get("currency", currency),
                    vat=item_data.get("vat", vat),
                )

            result = processor.process(items, _fetch_price)
            print_json(result)
        else:
            if not type or not item_no:
                raise typer.BadParameter("type and item_no are required for single lookups")

            data = client.get_price_guide(
                item_type=type,
                item_no=item_no,
                color_id=color,
                guide_type=guide_type,
                condition=condition,
                country_code=country,
                region=region,
                currency_code=currency,
                vat=vat,
            )
            if table:
                item_info = data.get("item", {})
                item_label = f"{item_info.get('type', '')}/{item_info.get('no', '')}" if item_info else ""
                row = {
                    "item": item_label,
                    "new_or_used": data.get("new_or_used"),
                    "avg_price": data.get("avg_price"),
                    "min_price": data.get("min_price"),
                    "max_price": data.get("max_price"),
                    "total_quantity": data.get("total_quantity"),
                    "currency_code": data.get("currency_code"),
                }
                print_table(
                    [row],
                    ["item", "new_or_used", "avg_price", "min_price", "max_price", "total_quantity", "currency_code"],
                    ["Item", "Condition", "Avg Price", "Min Price", "Max Price", "Total Qty", "Currency"],
                )
            else:
                print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("colors")
def catalog_colors(
    type: str = typer.Argument(..., help="Item type"),
    item_no: str = typer.Argument(..., help="Item number"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get known colors for an item.

    Examples:
        bricklink catalog colors PART 3001
        bricklink catalog colors PART 3001 --table
        bricklink catalog colors PART 3001 --filter "quantity:gt:100"
        bricklink catalog colors PART 3001 --limit 10
    """
    try:
        client = get_client()
        raw = client.get_known_colors(type, item_no)
        # Enrich with color names from /colors endpoint
        all_colors = client.get_colors()
        color_map = {c["color_id"]: c.get("color_name") for c in all_colors}
        for item in raw:
            item["color_name"] = color_map.get(item["color_id"])
        data = raw

        data = apply_filters(data, filter)
        data = apply_properties_filter(data, properties)
        data = apply_limit(data, limit)

        if table:
            print_table(
                data,
                ["color_id", "color_name", "quantity"],
                ["Color ID", "Color Name", "Quantity"],
            )
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("subsets")
def catalog_subsets(
    type: str = typer.Argument(..., help="Item type"),
    item_no: str = typer.Argument(..., help="Item number"),
    break_minifigs: bool = typer.Option(False, "--break-minifigs", help="Break down minifigs into parts"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get items contained in a set or item (subsets).

    Examples:
        bricklink catalog subsets SET 75192-1
        bricklink catalog subsets SET 75192-1 --break-minifigs
        bricklink catalog subsets SET 75192-1 --table
        bricklink catalog subsets MINIFIG sw0001 --limit 20
    """
    try:
        client = get_client()
        raw = client.get_subsets(
            type, item_no,
            break_minifigs=break_minifigs if break_minifigs else None,
        )
        data = raw if isinstance(raw, list) else []

        data = apply_filters(data, filter)
        data = apply_properties_filter(data, properties)
        data = apply_limit(data, limit)

        if table:
            print_table(data)
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("supersets")
def catalog_supersets(
    type: str = typer.Argument(..., help="Item type"),
    item_no: str = typer.Argument(..., help="Item number"),
    color: Optional[int] = typer.Option(None, "--color", "-c", help="Color ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum results"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get sets or items that contain this item (supersets).

    Examples:
        bricklink catalog supersets PART 3001
        bricklink catalog supersets PART 3001 --color 11
        bricklink catalog supersets MINIFIG sw0001 --table
    """
    try:
        client = get_client()
        raw = client.get_supersets(type, item_no, color_id=color)
        data = raw if isinstance(raw, list) else []

        data = apply_filters(data, filter)
        data = apply_properties_filter(data, properties)
        data = apply_limit(data, limit)

        if table:
            print_table(data)
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))
