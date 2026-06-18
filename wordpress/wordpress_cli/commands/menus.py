"""Navigation menu commands for WordPress CLI."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.output import handle_error, print_json, print_table


from . import extract_fields


app = typer.Typer(help="Manage WordPress navigation menus")

COMMAND_CREDENTIALS = {
    "add-page": ["username_password"],
    "items": ["username_password"],
    "list": ["username_password"],
    "locations": ["username_password"],
}


def get_client():
    from ..client import get_client as _get_client

    return _get_client()


def _fields(properties: Optional[str]) -> Optional[list[str]]:
    if properties is None:
        return None
    return [field.strip() for field in properties.split(",") if field.strip()]


@app.command("list")
def menus_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """List WordPress navigation menus."""
    try:
        client = get_client()
        menus = client.list_menus()
        fields = _fields(properties)
        if fields:
            menus = extract_fields(menus, fields)

        if table:
            table_fields = fields or ["id", "name", "slug", "locations"]
            print_table(menus, table_fields, table_fields)
        else:
            print_json(menus)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("locations")
def menu_locations(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List WordPress navigation menu locations."""
    try:
        client = get_client()
        locations = client.list_menu_locations()
        if table:
            rows = [
                {
                    "location": key,
                    "description": value.get("description"),
                    "menu": value.get("menu"),
                }
                for key, value in locations.items()
                if isinstance(value, dict)
            ]
            print_table(rows, ["location", "description", "menu"], ["Location", "Description", "Menu"])
        else:
            print_json(locations)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("items")
def menu_items(
    menu: Optional[str] = typer.Option(None, "--menu", help="Menu ID, slug, or name"),
    location: Optional[str] = typer.Option(None, "--location", help="Theme menu location"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum menu items to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """List items in a WordPress navigation menu."""
    try:
        client = get_client()
        menu_id = client.resolve_menu_id(menu=menu, location=location)
        items = client.list_menu_items(menu_id, limit=limit)
        fields = _fields(properties)
        if fields:
            items = extract_fields(items, fields)

        if table:
            table_fields = fields or ["id", "title.rendered", "url", "menu_order", "object", "object_id"]
            print_table(items, table_fields, table_fields)
        else:
            print_json({"menu_id": menu_id, "items": items})
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("add-page")
def menu_add_page(
    page_id: int = typer.Argument(..., help="WordPress page ID"),
    menu: Optional[str] = typer.Option(None, "--menu", help="Menu ID, slug, or name"),
    location: Optional[str] = typer.Option(None, "--location", help="Theme menu location"),
    title: Optional[str] = typer.Option(None, "--title", help="Menu item title"),
    menu_order: Optional[int] = typer.Option(None, "--menu-order", help="Menu item order"),
):
    """Add a WordPress page to a navigation menu."""
    try:
        client = get_client()
        menu_id = client.resolve_menu_id(menu=menu, location=location)
        result = client.add_page_to_menu(
            page_id=page_id,
            menu_id=menu_id,
            title=title,
            menu_order=menu_order,
        )
        print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))
