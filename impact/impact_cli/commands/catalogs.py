"""Catalog, store, and exception-list commands."""
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from ._common import output_item, output_list


COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"], "items": ["custom"], "item": ["custom"], "search": ["custom"], "stores": ["custom"], "exception-lists": ["custom"], "promo-code-exception-lists": ["custom"]}

app = typer.Typer(help="Manage catalogs, stores, and exception lists", no_args_is_help=True)
stores_app = typer.Typer(help="Manage stores", no_args_is_help=True)
exception_lists_app = typer.Typer(help="Manage exception lists", no_args_is_help=True)
promo_exception_lists_app = typer.Typer(help="Manage promo code exception lists", no_args_is_help=True)


@app.command("list")
def catalogs_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List catalogs."""
    try:
        output_list(get_client().list_catalogs(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def catalogs_get(catalog_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one catalog."""
    try:
        output_item(get_client().get_catalog(catalog_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("items")
def catalog_items(
    catalog_id: str,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List catalog items."""
    try:
        output_list(get_client().list_catalog_items(catalog_id, limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("item")
def catalog_item(catalog_id: str, item_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one catalog item."""
    try:
        output_item(get_client().get_catalog_item(catalog_id, item_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("search")
def catalog_search(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Search catalog items."""
    try:
        output_list(get_client().search_catalog_items(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@stores_app.command("list")
def stores_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List stores."""
    try:
        output_list(get_client().list_stores(limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@stores_app.command("get")
def stores_get(store_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one store."""
    try:
        output_item(get_client().get_store(store_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@stores_app.command("items")
def store_items(
    store_id: str,
    group_id: str,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List store group items."""
    try:
        output_list(get_client().list_store_items(store_id, group_id, limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@exception_lists_app.command("show")
def exception_lists_show(exception_list_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one exception list."""
    try:
        output_item(get_client().get_exception_list(exception_list_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@exception_lists_app.command("items")
def exception_list_items(
    exception_list_id: str,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List exception list items."""
    try:
        output_list(get_client().list_exception_list_items(exception_list_id, limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@promo_exception_lists_app.command("show")
def promo_exception_lists_show(exception_list_id: str, table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get one promo code exception list."""
    try:
        output_item(get_client().get_promo_code_exception_list(exception_list_id), table)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@promo_exception_lists_app.command("items")
def promo_exception_list_items(
    exception_list_id: str,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Maximum records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="API equality filter field:eq:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List promo code exception list items."""
    try:
        output_list(get_client().list_promo_code_exception_list_items(exception_list_id, limit=limit, filters=filter), table, properties, ["id", "name"], ["Id", "Name"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


app.add_typer(stores_app, name="stores")
app.add_typer(exception_lists_app, name="exception-lists")
app.add_typer(promo_exception_lists_app, name="promo-code-exception-lists")
