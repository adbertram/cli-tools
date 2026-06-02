"""Organization commands for Podio CLI."""

COMMAND_CREDENTIALS = {
    "get": [
        "oauth_authorization_code"
    ],
    "list": [
        "oauth_authorization_code"
    ]
}
import typer
from typing import Optional, Any

from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from ..client import get_client
from ..output import print_json, print_output, handle_api_error, format_response
from ..filter_map import FilterMap, apply_properties

app = typer.Typer(help="Manage Podio organizations")




@app.command("list")
def list_orgs(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum organizations to return"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List all organizations the user is a member of.

    Returns organizations with their org_id and associated spaces.

    Examples:
        podio org list
        podio org list --limit 10
        podio org list --filter "name:ATA"
        podio org list --properties "org_id,name"
        podio org list --table
    """
    try:
        client = get_client()
        result = client.Org.get_all()
        formatted = format_response(result)

        # Apply client-side filtering
        if filter and isinstance(formatted, list):
            formatted = apply_filters(formatted, filter)

        # Apply limit (client-side)
        if isinstance(formatted, list) and len(formatted) > limit:
            formatted = formatted[:limit]

        # Apply properties filter
        if properties:
            formatted = apply_properties(formatted, properties)

        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def get_org(
    org_id: int = typer.Argument(..., help="Organization ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a Podio organization by ID.

    Returns organization details including name, spaces, and member info.

    Examples:
        podio org get 12345
        podio org get 12345 --table
    """
    try:
        client = get_client()
        result = client.Org.find(org_id=org_id)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)
