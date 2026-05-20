"""Product commands for ClickBank CLI."""
COMMAND_CREDENTIALS = {
    "get": ["api_key"],
    "list": ["api_key"],
    "create": ["api_key"],
    "delete": ["api_key"],
}

import typer
from typing import List, Optional

from cli_tools_shared.output import handle_error, print_json

from ..client import get_client
from . import emit_rows


app = typer.Typer(help="Manage ClickBank products", no_args_is_help=True)

DEFAULT_COLUMNS = [
    "sku",
    "title",
    "site",
    "status",
    "language",
]
DEFAULT_HEADERS = [
    "SKU",
    "Title",
    "Site",
    "Status",
    "Language",
]


def _parse_params(values: List[str]) -> List[tuple[str, str]]:
    params: List[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid parameter format '{value}'. Expected key=value.")
        key, raw_value = value.split("=", 1)
        if not key or not raw_value:
            raise ValueError(f"Invalid parameter format '{value}'. Expected key=value.")
        params.append((key, raw_value))
    return params

@app.command("get")
def products_get(
    sku: str = typer.Argument(..., help="Product SKU"),
    site: str = typer.Option(..., "--site", help="Owning ClickBank account nickname"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a product by SKU."""
    try:
        product = get_client().get_product(sku, site=site)
        rows = [product]
        emit_rows(
            rows,
            table=table,
            properties=properties,
            default_columns=DEFAULT_COLUMNS,
            default_headers=DEFAULT_HEADERS,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("list")
def products_list(
    site: str = typer.Option(..., "--site", help="Owning ClickBank account nickname"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum products to return"),
    page: int = typer.Option(1, "--page", min=1, help="Starting ClickBank page number"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List products for a ClickBank account nickname."""
    try:
        rows = get_client().list_products(site=site, limit=limit, page=page, filters=filter)
        emit_rows(
            rows,
            table=table,
            properties=properties,
            default_columns=DEFAULT_COLUMNS,
            default_headers=DEFAULT_HEADERS,
        )
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("create")
def products_create(
    sku: str = typer.Argument(..., help="Product SKU to create"),
    param: List[str] = typer.Option(
        ...,
        "--param",
        help="Documented ClickBank product field as key=value. Repeat as needed.",
    ),
):
    """Create a product using documented ClickBank query parameters."""
    try:
        result = get_client().create_product(sku, _parse_params(param))
        print_json(result)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("delete")
def products_delete(
    sku: str = typer.Argument(..., help="Product SKU"),
    site: str = typer.Option(..., "--site", help="Owning ClickBank account nickname"),
):
    """Delete a product by SKU."""
    try:
        result = get_client().delete_product(sku, site=site)
        print_json(result)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
