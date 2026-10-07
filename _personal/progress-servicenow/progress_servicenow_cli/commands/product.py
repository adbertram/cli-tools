"""Product commands for Progress ServiceNow CLI.

``ticket product list`` reports the Product dropdown options that the live
catalog item publishes. It never reports an empty list as a success: when the
live catalog cannot answer, the command fails and names what it looked for.
"""

import typer
from typing import List, Optional

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters
from cli_tools_shared.output import command, handle_error, print_error, print_json, print_table

from ..client import get_client

app = typer.Typer(help="Product field options for catalog items", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
}


def _product_rows() -> List[dict]:
    """Fetch the live Product dropdown options as output records."""
    client = get_client()
    try:
        products = client.list_products()
    finally:
        client.close()

    if not products:
        raise ClientError(
            "The live Product dropdown returned no options. A discovery command must not "
            "report success with an empty result. Verify the catalog item with "
            "'progress-servicenow ticket template get other_development_request'."
        )
    return [{"product": product} for product in products]


def _select_properties(row: dict, properties: Optional[str]) -> dict:
    if not properties:
        return row
    fields = [field.strip() for field in properties.split(",")]
    return {field: row.get(field) for field in fields}


def _columns(properties: Optional[str]) -> List[str]:
    if properties:
        return [field.strip() for field in properties.split(",")]
    return ["product"]


@app.command("list")
@command
def product_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    List available Product dropdown options from the live catalog item form.

    Reads the choices the ServiceNow Service Catalog publishes for the Product
    variable. Fails when the catalog cannot be reached or publishes no choices.

    Examples:
        progress-servicenow ticket product list
        progress-servicenow ticket product list --table
    """
    try:
        if filter:
            validate_filters(filter)
        rows = _product_rows()
        if filter:
            rows = apply_filters(rows, filter)
        rows = rows[:limit]
        rows = [_select_properties(row, properties) for row in rows]

        if table:
            columns = _columns(properties)
            print_table(rows, columns, [column.title() for column in columns])
        else:
            print_json(rows)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    except ClientError as exc:
        handle_error(exc)
        raise typer.Exit(1)


@app.command("get")
@command
def product_get(
    product: str = typer.Argument(..., help="Exact product name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Get one Product dropdown option by exact name."""
    try:
        rows = [row for row in _product_rows() if row["product"] == product]
    except ClientError as exc:
        handle_error(exc)
        raise typer.Exit(1)

    if not rows:
        print_error(f"Product not found: {product}")
        raise typer.Exit(1)

    row = _select_properties(rows[0], properties)
    if table:
        columns = _columns(properties)
        print_table([row], columns, [column.title() for column in columns])
    else:
        print_json(row)
