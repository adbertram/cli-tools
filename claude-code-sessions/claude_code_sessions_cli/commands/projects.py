"""Project commands for Claude Code Sessions CLI."""
import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, print_json, print_table, handle_error
from ..parsers import format_local_time

app = typer.Typer(help="List and query projects", no_args_is_help=True)


@app.command("list")
@command
def list_projects(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all projects with Claude Code sessions.

    Example:
        claude-code-sessions projects list
        claude-code-sessions projects list --table
        claude-code-sessions projects list --limit 10
    """
    try:
        client = get_client()
        projects = client.list_projects(limit=limit)

        # Convert to dicts for filtering/output
        items = [p.model_dump() for p in projects]

        # Apply client-side filters
        if filter:
            items = apply_filters(items, filter)

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            items = [{k: v for k, v in item.items() if k in prop_list} for item in items]

        if table:
            for item in items:
                item['last_activity'] = format_local_time(item.get('last_activity', ''))
            columns = ["name", "session_count", "last_activity"]
            headers = ["Name", "Sessions", "Last Activity"]
            print_table(items, columns, headers)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_project(
    name: str = typer.Argument(..., help="Project name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific project.

    Example:
        claude-code-sessions projects get ExampleProject
    """
    try:
        client = get_client()
        project = client.get_project(name)

        if table:
            rows = [
                {"field": "Name", "value": project.name},
                {"field": "Full Path", "value": project.full_path},
                {"field": "Session Count", "value": str(project.session_count)},
                {"field": "Last Activity", "value": format_local_time(project.last_activity) if project.last_activity else "N/A"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(project.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))
