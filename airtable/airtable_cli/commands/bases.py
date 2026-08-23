"""Base discovery commands for Airtable CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "personal_access_token"
    ],
    "list": [
        "personal_access_token"
    ]
}

from typing import Any, Dict, List, Optional

import typer

from ..client import get_client
from cli_tools_shared.filters import apply_filters, apply_properties_filter
from cli_tools_shared.output import print_json, print_table, command

app = typer.Typer(help="Discover Airtable bases", no_args_is_help=True)

BASE_COLUMNS = ["id", "name", "permissionLevel"]
BASE_HEADERS = ["ID", "Name", "Permission Level"]


def summarize_base(base: Dict[str, Any]) -> Dict[str, Any]:
    """Return the flat representation for a base record."""
    return {
        "id": base.get("id", ""),
        "name": base.get("name", ""),
        "permissionLevel": base.get("permissionLevel", ""),
    }


def print_base(base: Dict[str, Any], table: bool) -> None:
    """Print a single base record as JSON or a one-row table."""
    summary = summarize_base(base)
    if not table:
        print_json(summary)
        return
    print_table([summary], BASE_COLUMNS, BASE_HEADERS)


@app.command("list")
@command
def bases_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum bases to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:CourseCraft, name:contains:Course)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include in output"),
):
    """
    List every base the active Personal Access Token can access.

    Follows Airtable's Metadata API offset pagination so all accessible bases
    are returned, not just the first page.

    Examples:
        airtable bases list
        airtable bases list --table
        airtable bases list --filter "name:contains:Course"
    """
    client = get_client()
    bases = client.list_bases()

    summarized = [summarize_base(base) for base in bases]

    if filter:
        summarized = apply_filters(summarized, filter)

    if limit and len(summarized) > limit:
        summarized = summarized[:limit]

    if properties:
        summarized = apply_properties_filter(summarized, properties)

    if not table:
        print_json(summarized)
        return

    print_table(summarized, BASE_COLUMNS, BASE_HEADERS)


@app.command("get")
@command
def bases_get(
    base_id: str = typer.Argument(..., help="The base ID (beginning with app) or base name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one base by ID or name from the accessible bases list.

    Airtable exposes no single-base detail endpoint, so this resolves the base
    from the full bases listing.

    Examples:
        airtable bases get app9uzzru5KZOImYQ
        airtable bases get CourseCraft --table
    """
    client = get_client()
    result = client.get_base(base_id)
    print_base(result, table)
