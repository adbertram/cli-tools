"""Space commands for Podio CLI."""

COMMAND_CREDENTIALS = {
    "find-by-url": [
        "oauth_authorization_code"
    ],
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
from ..config import get_config
from cli_tools_shared.output import command
from ..output import print_json, print_output, print_error, print_warning, handle_api_error, format_response
from ..filter_map import FilterMap, apply_properties

app = typer.Typer(help="Manage Podio spaces")


@app.command("get")
def get_space(
    space_id: Optional[int] = typer.Argument(None, help="Space ID to retrieve"),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Find space by Podio URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a Podio space by ID or URL.

    If neither space_id nor url is provided, uses PODIO_WORKSPACE_ID from environment.

    Examples:
        podio space get 12345
        podio space get --url https://podio.com/org/workspace
        podio space get  # Uses PODIO_WORKSPACE_ID
        podio space get --table
    """
    try:
        client = get_client()

        if url:
            # Look up by URL
            result = client.Space.find_by_url(url=url)
        elif space_id:
            # Look up by space ID
            result = client.Space.find(space_id=space_id)
        else:
            # Use workspace_id from config
            config = get_config()
            if config.workspace_id:
                result = client.Space.find(space_id=int(config.workspace_id))
            else:
                print_error("No space_id provided and WORKSPACE_ID not set in environment")
                raise typer.Exit(1)

        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("list")
def list_spaces(
    org_id: Optional[int] = typer.Option(None, "--org-id", "-o", help="Organization ID to list spaces from (defaults to PODIO_ORGANIZATION_ID)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum spaces to return"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List all spaces in an organization.

    If org_id is not provided, uses PODIO_ORGANIZATION_ID from environment.

    Examples:
        podio space list --org-id 3747840
        podio space list  # Uses PODIO_ORGANIZATION_ID
        podio space list --limit 10
        podio space list --filter "name:Progress"
        podio space list --properties "space_id,name"
        podio space list --table
    """
    try:
        # Use organization_id from config if org_id not provided
        if org_id is None:
            config = get_config()
            if config.organization_id:
                org_id = int(config.organization_id)
            else:
                print_error("No org_id provided and PODIO_ORGANIZATION_ID not set in environment")
                raise typer.Exit(1)

        client = get_client()
        result = client.Space.find_all_for_org(org_id=org_id)
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


@app.command("find-by-url", hidden=True)
@command
def find_space_by_url_deprecated(
    url: str = typer.Argument(..., help="Podio space URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """[DEPRECATED] Use 'podio space get --url <url>' instead."""
    print_warning("'podio space find-by-url' is deprecated. Use 'podio space get --url <url>' instead.")
    return get_space(url=url, table=table)

