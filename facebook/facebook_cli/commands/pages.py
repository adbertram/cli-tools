"""Facebook Page discovery through the Graph API."""
from typing import List, Optional

import typer

from cli_tools_shared.filters import (
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_json, print_table

from ..graph_api import FacebookGraphClient

app = typer.Typer(help="Manage Facebook Pages available to the Graph API profile")

COMMAND_CREDENTIALS = {
    "get": ["oauth_authorization_code"],
    "list": ["oauth_authorization_code"],
}

_DEFAULT_COLUMNS = ["id", "name", "tasks"]


@app.command("list")
@command
def pages_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum Pages to return"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    """List Pages managed by the authenticated Facebook user."""
    if filter:
        validate_filters(filter)
    rows = FacebookGraphClient().list_pages(limit=limit)
    if filter:
        rows = apply_filters(rows, filter)
    if properties:
        rows = apply_properties_filter(rows, properties)
    columns = (
        [field.strip() for field in properties.split(",") if field.strip()]
        if properties
        else _DEFAULT_COLUMNS
    )
    if table:
        print_table(rows, columns, [column.replace("_", " ").title() for column in columns])
    else:
        print_json(rows)


@app.command("get")
@command
def pages_get(
    page_id: str = typer.Argument(..., help="Facebook Page ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to display"
    ),
):
    """Get a Page available to the authenticated Facebook user."""
    row = FacebookGraphClient().get_page(page_id)
    if properties:
        row = apply_properties_filter([row], properties)[0]
    columns = (
        [field.strip() for field in properties.split(",") if field.strip()]
        if properties
        else _DEFAULT_COLUMNS
    )
    if table:
        print_table([row], columns, [column.replace("_", " ").title() for column in columns])
    else:
        print_json(row)
