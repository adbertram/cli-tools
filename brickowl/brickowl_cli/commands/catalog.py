"""Catalog commands for Brickowl CLI."""
COMMAND_CREDENTIALS = {
    "lookup": ["api_key"],
    "search": ["browser_session"],
    "id": ["api_key"],
    "availability": ["api_key"],
    "inventory": ["api_key"],
    "colors": ["api_key"],
    "conditions": ["api_key"],
    "categories": ["api_key"],
    "themes": ["api_key"],
}

import typer
from typing import Optional

from ..client import get_client, ClientError, ApprovalRequiredError
from cli_tools_shared.output import print_json, print_table, print_error, print_success, print_info, handle_error

app = typer.Typer(help="Browse the Brick Owl catalog", no_args_is_help=True)


@app.command("lookup")
def catalog_lookup(
    boid: str = typer.Argument(..., help="Brick Owl item ID (BOID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Look up a catalog item by BOID.

    Examples:
        brickowl catalog lookup 123456
        brickowl catalog lookup 123456 --table
    """
    try:
        client = get_client()
        result = client.catalog_lookup(boid)

        if table:
            if isinstance(result, dict):
                rows = [{"field": k, "value": str(v)} for k, v in result.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
            else:
                print_table(result)
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def catalog_search(
    query: str = typer.Argument(..., help="Search query"),
    page: int = typer.Option(1, "--page", help="Page number"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Search the Brick Owl catalog (browser-based).

    Examples:
        brickowl catalog search "Millennium Falcon"
        brickowl catalog search "3001" --table
        brickowl catalog search "minifig" --page 2
    """
    try:
        from ..browser import get_browser
        browser = get_browser()

        try:
            result = browser.catalog_search(query, page=page)
        finally:
            browser.close()

        rows = result.get("rows", []) if isinstance(result, dict) else []
        total = result.get("total", 0) if isinstance(result, dict) else 0
        total_pages = result.get("total_pages", 1) if isinstance(result, dict) else 1

        if not rows:
            print_info("No results found")
            raise typer.Exit(0)

        if table:
            print_info(f"Page {page} of {total_pages} ({total} total results)")
            print_table(
                rows,
                columns=["boid", "name", "price"],
                headers=["BOID", "Name", "Price"],
            )
        else:
            print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("id")
def catalog_id(
    id_value: str = typer.Argument(..., help="External ID value"),
    type: str = typer.Argument(..., help="Item type (Part, Set, Minifigure, etc.)"),
    id_type: Optional[str] = typer.Option(None, "--id-type", help="ID type: item_no, design_id, bl_item_no, set_number (alias: bricklink -> bl_item_no)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Look up a catalog item by external ID.

    ID types: item_no, design_id, bl_item_no, set_number (alias: bricklink -> bl_item_no)

    Examples:
        brickowl catalog id 3001 Part
        brickowl catalog id 3001 Part --id-type design_id
        brickowl catalog id 3001 Part --id-type bl_item_no
        brickowl catalog id 75192 Set --table
    """
    try:
        client = get_client()
        result = client.catalog_id_lookup(id_value, type, id_type=id_type)

        if table:
            if isinstance(result, dict):
                boids = result.get("boids", [])
                if boids:
                    rows = [{"boid": b} for b in boids]
                    print_table(rows, ["boid"], ["BOID"])
                else:
                    rows = [{"field": k, "value": str(v)} for k, v in result.items() if v is not None]
                    print_table(rows, ["field", "value"], ["Field", "Value"])
            else:
                print_table(result)
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("availability")
def catalog_availability(
    boid: str = typer.Argument(..., help="Brick Owl item ID (BOID)"),
    country: str = typer.Argument(..., help="Country code (e.g., US, GB, DE)"),
    quantity: Optional[int] = typer.Option(None, "--quantity", "-q", help="Quantity to check"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get pricing and availability for a catalog item.

    Examples:
        brickowl catalog availability 123456 US
        brickowl catalog availability 123456 US --quantity 10
        brickowl catalog availability 123456 US --table
    """
    try:
        client = get_client()
        result = client.catalog_availability(boid, country, quantity=quantity)

        if table:
            if isinstance(result, dict):
                # Check if result has nested data
                items = result.get("items", result.get("rows", None))
                if isinstance(items, list):
                    print_table(items)
                else:
                    rows = [{"field": k, "value": str(v)} for k, v in result.items() if v is not None]
                    print_table(rows, ["field", "value"], ["Field", "Value"])
            elif isinstance(result, list):
                print_table(result)
            else:
                print_json(result)
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("inventory")
def catalog_inventory(
    boid: str = typer.Argument(..., help="Brick Owl item ID (BOID) for a set"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get the parts inventory for a set.

    Examples:
        brickowl catalog inventory 123456
        brickowl catalog inventory 123456 --table
    """
    try:
        client = get_client()
        result = client.catalog_inventory(boid)

        if table:
            if isinstance(result, list):
                print_table(result)
            elif isinstance(result, dict):
                items = result.get("items", result.get("rows", None))
                if isinstance(items, list):
                    print_table(items)
                else:
                    rows = [{"field": k, "value": str(v)} for k, v in result.items() if v is not None]
                    print_table(rows, ["field", "value"], ["Field", "Value"])
            else:
                print_json(result)
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("colors")
def catalog_colors(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List all available colors.

    Examples:
        brickowl catalog colors
        brickowl catalog colors --table
    """
    try:
        client = get_client()
        result = client.catalog_colors()

        if table:
            if isinstance(result, list):
                print_table(result)
            elif isinstance(result, dict):
                # Colors might be keyed by ID
                rows = [{"color_id": k, **v} if isinstance(v, dict) else {"color_id": k, "name": v}
                        for k, v in result.items()]
                print_table(rows)
            else:
                print_json(result)
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("conditions")
def catalog_conditions(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List all available conditions.

    Examples:
        brickowl catalog conditions
        brickowl catalog conditions --table
    """
    try:
        client = get_client()
        result = client.catalog_conditions()

        if table:
            if isinstance(result, list):
                print_table(result)
            elif isinstance(result, dict):
                rows = [{"code": k, **v} if isinstance(v, dict) else {"code": k, "name": v}
                        for k, v in result.items()]
                print_table(rows)
            else:
                print_json(result)
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("categories")
def catalog_categories(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List all catalog categories.

    Examples:
        brickowl catalog categories
        brickowl catalog categories --table
    """
    try:
        client = get_client()
        result = client.catalog_field_options("category_0")

        if table:
            if isinstance(result, list):
                print_table(result)
            elif isinstance(result, dict):
                rows = [{"id": k, **v} if isinstance(v, dict) else {"id": k, "name": v}
                        for k, v in result.items()]
                print_table(rows)
            else:
                print_json(result)
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("themes")
def catalog_themes(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List all catalog themes.

    Examples:
        brickowl catalog themes
        brickowl catalog themes --table
    """
    try:
        client = get_client()
        result = client.catalog_field_options("theme_0")

        if table:
            if isinstance(result, list):
                print_table(result)
            elif isinstance(result, dict):
                rows = [{"id": k, **v} if isinstance(v, dict) else {"id": k, "name": v}
                        for k, v in result.items()]
                print_table(rows)
            else:
                print_json(result)
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
