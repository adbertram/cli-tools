"""Workspace commands for Asana CLI."""
import typer
from typing import Optional, List
from ..client import get_client
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage Asana workspaces")


def extract_field(data, field_path: str):
    """Extract a field value using dot notation."""
    parts = field_path.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            idx = int(part)
            value = value[idx] if idx < len(value) else None
        else:
            return None
        if value is None:
            return None
    return value


@app.command("list")
def workspace_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(100, "--limit", "-l", help="Limit number of results"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output single field (e.g., 'gid', 'name')"),
):
    """List all workspaces the user has access to."""
    try:
        # Validate filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                typer.echo(f"Filter error: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        workspaces = client.list_workspaces(limit=limit)

        # Apply filters if provided
        if filter_:
            workspaces = apply_filters(workspaces, filter_)

        if properties:
            for workspace in workspaces:
                value = extract_field(workspace, properties)
                if value is not None:
                    print(value)
        elif table:
            print_table(
                workspaces,
                ["gid", "name"],
                ["ID", "Name"]
            )
        else:
            print_json(workspaces)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def workspace_get(
    workspace_id: str = typer.Argument(..., help="Workspace ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get workspace details."""
    try:
        client = get_client()
        workspace = client.get_workspace(workspace_id)

        if table:
            data = {
                "gid": workspace.get("gid"),
                "name": workspace.get("name"),
            }
            print_table([data], list(data.keys()), ["ID", "Name"])
        else:
            print_json(workspace)
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
