"""Main entry point for Target CLI."""

import typer
from typing import List, Optional
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_table

from . import __version__
from .client import ClientError, get_client
from .config import get_config

from cli_tools_shared.auth_commands import create_auth_app

COLUMNS = ["id", "title", "price"]

app = create_app(name="target", help="CLI interface for Target", version=__version__)
products_app = typer.Typer(help="Products management", no_args_is_help=True)
cart_app = typer.Typer(help="Cart management", no_args_is_help=True)

def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None

def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

def _render(rows: List[dict], table: bool, properties: Optional[str], empty: str) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or COLUMNS
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])

def _list(fetch, filters, table, properties, empty) -> None:
    _validate(filters)
    rows = fetch()
    if filters:
        rows = apply_filters(rows, filters)
    _render(rows, table, properties, empty)

@products_app.command("list")
@command
def products_list(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search for items on Target."""
    client = get_client()
    try:
        _list(lambda: client.search(query, limit), filter, table, properties, "No results found.")
    finally:
        client.close()

@products_app.command("get")
@command
def products_get(
    item_id: str = typer.Argument(..., help="Item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get details for a specific item."""
    client = get_client()
    try:
        row = client.get_item(item_id)
        fields = _property_fields(properties)
        if fields:
            _render([row], table, properties, "No item found.")
        elif table:
            print_table(
                [{"field": key, "value": str(value)} for key, value in row.items()],
                ["field", "value"],
                ["Field", "Value"],
            )
        else:
            print_json(row)
    finally:
        client.close()

@cart_app.command("list")
@command
def cart_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """View current cart contents."""
    client = get_client()
    try:
        cart_data = client.get_cart()
        print_json(cart_data)
    finally:
        client.close()

@cart_app.command("add")
@command
def cart_add(
    item_id: str = typer.Argument(..., help="Item TCIN or URL"),
):
    """Add an item to the cart."""
    client = get_client()
    try:
        client.add_to_cart(item_id)
        print_info(f"Added {item_id} to cart.")
    finally:
        client.close()

@cart_app.command("remove")
@command
def cart_remove(
    item_id: str = typer.Argument(..., help="Item TCIN"),
):
    """Remove an item from the cart."""
    client = get_client()
    try:
        client.remove_from_cart(item_id)
        print_info(f"Removed {item_id} from cart.")
    finally:
        client.close()

@cart_app.command("checkout")
@command
def cart_checkout(
    delivery: str = typer.Option("pickup", "--delivery", help="Delivery method (pickup, shipping)"),
):
    """Proceed through checkout and place order."""
    client = get_client()
    try:
        result = client.checkout(delivery)
        print_info(result)
    finally:
        client.close()

store_app = typer.Typer(help="Store location management", no_args_is_help=True)

@store_app.command("set")
@command
def store_set(
    zip_code: str = typer.Argument(..., help="Zip code or city/state to search for"),
):
    """Set the home store for pickup/inventory."""
    client = get_client()
    try:
        result = client.set_store(zip_code)
        print_info(result)
    finally:
        client.close()

app.add_typer(products_app, name="products")
app.add_typer(cart_app, name="cart")
app.add_typer(store_app, name="store")
app.add_typer(create_auth_app(get_config, tool_name="target"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")

def main():
    """Main entry point."""
    try:
        run_app(app)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
