"""Project commands: workspaces that have Hermes sessions."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters, validate_filters
from cli_tools_shared.output import command, handle_error, print_json

from ..client import get_client
from ._render import bound_rows, add_time, fetch_limit, print_record, render_table, select_properties, to_items

app = typer.Typer(help="List and query projects", no_args_is_help=True)

LEAN = [
    ("name", "Name"),
    ("full_path", "Path"),
    ("session_count", "Sessions"),
    ("subagent_session_count", "Subagents"),
    ("last", "Last Activity"),
]
EXTRA = [
    ("message_count", "Msgs"),
    ("tool_call_count", "Tools"),
    ("first", "First Activity"),
]
DETAIL = [
    ("name", "Name"),
    ("full_path", "Full Path"),
    ("session_count", "Sessions"),
    ("subagent_session_count", "Subagent Sessions"),
    ("message_count", "Messages"),
    ("tool_call_count", "Tool Calls"),
    ("first_activity", "First Activity"),
    ("last_activity", "Last Activity"),
]


@app.command("list")
@command
def list_projects(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., session_count:gt:5)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List every workspace that has Hermes sessions.

    Example:
        hermes-sessions projects list
        hermes-sessions projects list --table
        hermes-sessions projects list --filter "session_count:gt:5"
    """
    try:
        if filter:
            validate_filters(filter)
        items = to_items(get_client().list_projects(limit=fetch_limit(limit, filter)))
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(bound_rows(items, limit), properties)

        if table:
            add_time(items, "last_activity", "last")
            add_time(items, "first_activity", "first")
            render_table(items, LEAN, EXTRA, wide)
        else:
            print_json(items)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
@command
def get_project(
    name: str = typer.Argument(..., help="Project name, absolute path, or (no-workspace)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for one workspace.

    Example:
        hermes-sessions projects get LegoScout
        hermes-sessions projects get /Users/adam/Dropbox/GitRepos/Agents/LegoScout --table
    """
    try:
        project = get_client().get_project(name).model_dump()
        if table:
            print_record(project, DETAIL)
        else:
            print_json(project)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
