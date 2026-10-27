"""View commands for Podio CLI."""

COMMAND_CREDENTIALS = {
    "create": [
        "oauth_authorization_code"
    ],
    "delete": [
        "oauth_authorization_code"
    ],
    "get": [
        "oauth_authorization_code"
    ],
    "list": [
        "oauth_authorization_code"
    ]
}
from pathlib import Path
from typing import Optional
import typer

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from ..output import (
    print_output, print_error, print_success, confirm_or_refuse, read_json_input,
    handle_api_error, format_response,
)
from cli_tools_shared.output import command
from pypodio2.transport import TransportException
from ..filter_map import apply_properties

app = typer.Typer(help="Manage Podio app views")


@app.command("list")
@command
def list_views(
    app_id: int = typer.Argument(..., help="Application ID to list views from"),
    include_standard_views: bool = typer.Option(False, "--include-standard-views", help="Also include Podio's standard views"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum views to return"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:contains:Open)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List the views of an application.

    Examples:
        podio view list 12345
        podio view list 12345 --include-standard-views
        podio view list 12345 --filter "name:contains:Open"
        podio view list 12345 --properties "view_id,name"
        podio view list 12345 --table
    """
    try:
        client = get_client()
        result = client.View.get_views(app_id=app_id, include_standard_views=include_standard_views)
        formatted = format_response(result)

        if filter and isinstance(formatted, list):
            formatted = apply_filters(formatted, [filter])
        if isinstance(formatted, list):
            formatted = formatted[:limit]
        if properties:
            formatted = apply_properties(formatted, properties)

        print_output(formatted, table=table)
    except TransportException as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
@command
def get_view(
    app_id: int = typer.Argument(..., help="Application ID the view belongs to"),
    view: str = typer.Argument(..., help="View ID, view name, or 'last' for the last view used"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get the definition of a view (GET /view/app/{app_id}/{view}).

    Examples:
        podio view get 12345 67890
        podio view get 12345 last
        podio view get 12345 67890 --table
    """
    try:
        client = get_client()
        result = client.View.get(app_id=app_id, view_specifier=view)
        print_output(format_response(result), table=table)
    except TransportException as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
@command
def create_view(
    app_id: int = typer.Argument(..., help="Application ID to create the view in"),
    json_file: Optional[Path] = typer.Option(None, "--json-file", help="Path to JSON file with the view definition (default: read stdin)"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Create a view on an application from a JSON definition.

    Reads the view definition from a JSON file or stdin. Documented keys:
    name, private, sort_by, sort_desc, filters, layout, fields, grouping.

    View data format:
        {
            "name": "Open items",
            "private": false,
            "sort_by": "created_on",
            "sort_desc": true,
            "filters": [{"key": "<field_id>", "values": ["<value>"]}]
        }

    Examples:
        podio view create 12345 --json-file view.json
        cat view.json | podio view create 12345
    """
    try:
        view_data = read_json_input(json_file)
        if not isinstance(view_data, dict):
            print_error("View data must be a JSON object")
            raise typer.Exit(1)

        client = get_client()
        result = client.View.create(app_id=app_id, attributes=view_data)
        print_output(format_response(result), table=table)
    except TransportException as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("delete")
@command
def delete_view(
    view_id: int = typer.Argument(..., help="View ID to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Delete a view.

    Prompts for confirmation unless --yes is given; without a terminal,
    --yes is required.

    Examples:
        podio view delete 67890
        podio view delete 67890 --yes
    """
    try:
        confirm_or_refuse(f"delete view {view_id}", yes)
        client = get_client()
        client.View.delete(view_id=view_id)
        print_success(f"View {view_id} deleted successfully")
        print_output({"view_id": view_id, "deleted": True}, table=table)
    except TransportException as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)
