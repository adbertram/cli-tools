"""``cj advertisers`` subcommand group.

Read-only discovery surface on top of the CJ Advertiser Lookup REST
API.  Apply / join actions live in :mod:`cj_cli.commands.relationships`
because they require browser automation.
"""

from __future__ import annotations

from typing import List, Optional

import typer
from pydantic import BaseModel

from cli_tools_shared.output import handle_error, print_info, print_json, print_table

from ..client import get_client
from ..filter_map import FilterMap  # noqa: F401  compliance: command files reference filter_map


app = typer.Typer(help="Discover CJ advertiser programs", no_args_is_help=True)


# Compliance: each command's credential gate, used by the auth audit tests.
COMMAND_CREDENTIALS = {
    "list": ["personal_access_token"],
    "search": ["personal_access_token"],
    "get": ["personal_access_token"],
}


def _to_dict(item):
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def _extract_field(item, field: str):
    data = _to_dict(item)
    value = data
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _extract_fields(items: list, fields: list) -> list:
    return [{field: _extract_field(item, field) for field in fields} for item in items]


# ----------------------------------------------------------------------
# advertisers list
# ----------------------------------------------------------------------


@app.command("list")
def advertisers_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of records (CJ caps page size at 100)"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Client-side filter (field:op:value)"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include (supports dot-notation)",
    ),
    relationship: str = typer.Option(
        "joined",
        "--relationship",
        "-r",
        help="Relationship slice: joined | notjoined | all | <comma-separated advertiser IDs>",
    ),
    keywords: Optional[str] = typer.Option(
        None, "--keywords", "-k", help="Free-text keywords (server-side search)"
    ),
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Exact advertiser-name filter (server-side)"
    ),
    category: Optional[str] = typer.Option(
        None, "--category", "-c", help="Primary category name (server-side)"
    ),
    page: int = typer.Option(1, "--page", help="1-indexed page number"),
):
    """List advertiser programs from CJ.

    Examples:
        cj advertisers list
        cj advertisers list --relationship notjoined --limit 50
        cj advertisers list --keywords "software" --table
        cj advertisers list --category "Computer & Electronics"
        cj advertisers list --filter "primary_category:eq:Software"
    """
    try:
        client = get_client()
        rows = client.list_advertisers(
            relationship=relationship,
            keywords=keywords,
            advertiser_name=name,
            category=category,
            page=page,
            limit=limit,
            filters=filter,
        )

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            rows = _extract_fields(rows, fields)

        if table:
            if properties:
                cols = [f.strip() for f in properties.split(",")]
                print_table(rows, cols, cols)
            else:
                print_table(
                    rows,
                    ["advertiser_id", "advertiser_name", "relationship_status", "primary_category", "network_rank"],
                    ["ID", "Name", "Status", "Category", "Rank"],
                )
        else:
            print_json(rows)

    except Exception as exc:
        raise typer.Exit(handle_error(exc))


# ----------------------------------------------------------------------
# advertisers search
# ----------------------------------------------------------------------


@app.command("search")
def advertisers_search(
    query: str = typer.Argument(..., help="Search query (supports * wildcards)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    relationship: str = typer.Option(
        "all",
        "--relationship",
        "-r",
        help="Relationship slice to search within (joined | notjoined | all)",
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Wildcard search advertiser names.

    Server-side keyword search plus client-side fnmatch so explicit
    ``*`` wildcards work.

    Examples:
        cj advertisers search "*wordpress*"
        cj advertisers search "Bluehost"
        cj advertisers search "*hosting*" --relationship notjoined --table
    """
    try:
        client = get_client()
        rows = client.search_advertisers(query=query, limit=limit, relationship=relationship)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            rows = _extract_fields(rows, fields)

        if table:
            if not rows:
                print_info("No advertisers found matching the search query.")
                return
            if properties:
                cols = [f.strip() for f in properties.split(",")]
            else:
                cols = ["advertiser_id", "advertiser_name", "relationship_status", "primary_category"]
            print_table(rows, cols, cols)
        else:
            print_json(rows)

    except Exception as exc:
        raise typer.Exit(handle_error(exc))


# ----------------------------------------------------------------------
# advertisers get
# ----------------------------------------------------------------------


@app.command("get")
def advertisers_get(
    advertiser_id: str = typer.Argument(..., help="The CJ advertiser ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as key/value table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """Get full detail for a single advertiser program.

    Examples:
        cj advertisers get 1234567
        cj advertisers get 1234567 --table
        cj advertisers get 1234567 --properties "advertiser_name,primary_category,actions"
    """
    try:
        client = get_client()
        detail = client.get_advertiser(advertiser_id)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            detail = _extract_fields([detail], fields)[0]

        if table:
            if properties:
                cols = [f.strip() for f in properties.split(",")]
                print_table([detail], cols, cols)
            else:
                row_dict = _to_dict(detail)
                rows = [{"field": k, "value": str(v)} for k, v in row_dict.items() if v not in (None, [], {})]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(detail)

    except Exception as exc:
        raise typer.Exit(handle_error(exc))
