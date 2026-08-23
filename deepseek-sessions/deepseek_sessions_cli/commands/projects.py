"""Project commands for the DeepSeek Sessions CLI."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, handle_error, print_json, print_table

from ..client import ClientError, get_client
from ..parsers import format_local_time
from ._render import add_time, fetch_limit, render_table, select_properties, to_items

app = typer.Typer(help="List and query projects", no_args_is_help=True)


@app.command("list")
@command
def list_projects(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:LegoScout, session_count:gt:5)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all projects that have dsh sessions.

    Example:
        deepseek-sessions projects list
        deepseek-sessions projects list --table
        deepseek-sessions projects list --filter "session_count:gt:5"
    """
    try:
        items = to_items(get_client().list_projects(limit=fetch_limit(limit, filter)))
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_time(items, "last_activity", "last", "%b %d %H:%M")
            render_table(
                items,
                [("name", "Name"), ("full_path", "Path"), ("session_count", "Sessions"),
                 ("subagent_session_count", "Subagents"), ("last", "Last Activity")],
                [("encoded_path", "Directory Key")],
                wide,
            )
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_project(
    name: str = typer.Argument(..., help="Project name, absolute path, or directory key"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific project.

    Example:
        deepseek-sessions projects get LegoScout
        deepseek-sessions projects get /Users/adam/Dropbox/GitRepos/Agents/LegoScout
    """
    try:
        project = get_client().get_project(name)

        if table:
            rows = [
                {"field": "Name", "value": project.name},
                {"field": "Full Path", "value": project.full_path or "N/A"},
                {"field": "Directory Key", "value": project.encoded_path},
                {"field": "Sessions", "value": str(project.session_count)},
                {"field": "Subagent Sessions", "value": str(project.subagent_session_count)},
                {"field": "Last Activity", "value": format_local_time(project.last_activity or "") or "N/A"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(project.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))
