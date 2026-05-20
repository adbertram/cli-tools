"""Workspaces commands for Kick CLI."""
import typer
from typing import Optional, List

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage Kick workspaces")


@app.command("list")
def workspaces_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of workspaces to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to display"),
):
    """
    List all workspaces.

    Examples:
        kick workspaces list
        kick workspaces list --table
    """
    try:
        client = get_client()
        workspaces_raw = client.get_workspaces()

        # Extract workspace objects for filtering
        workspaces_data = [ws_data["workspace"] for ws_data in workspaces_raw]

        # Apply client-side filtering (API doesn't support filtering)
        if filter:
            workspaces_data = apply_filters(workspaces_data, filter)

        # Apply limit
        workspaces_data = workspaces_data[:limit]

        if table:
            table_data = []
            for ws in workspaces_data:
                entity_count = len(ws.get("entities", []))
                table_data.append({
                    "id": ws.get("id", ""),
                    "name": ws.get("name", ""),
                    "plan": ws.get("plan", ""),
                    "entities": str(entity_count),
                })

            print_table(
                table_data,
                ["id", "name", "plan", "entities"],
                ["ID", "Name", "Plan", "Entities"],
            )
        else:
            print_json(workspaces_data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def workspaces_get(
    workspace_id: Optional[str] = typer.Argument(None, help="Workspace UUID (uses default if not provided)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific workspace.

    Examples:
        kick workspaces get
        kick workspaces get 019409a4-f7bd-7282-8325-3a417b0c7cd3
        kick workspaces get --table
    """
    try:
        client = get_client()
        workspaces = client.get_workspaces()

        ws_id = workspace_id or client.get_default_workspace_id()

        workspace = None
        for ws_data in workspaces:
            if ws_data["workspace"]["id"] == ws_id:
                workspace = ws_data["workspace"]
                break

        if not workspace:
            from cli_tools_shared.output import print_error
            print_error(f"Workspace {ws_id} not found")
            raise typer.Exit(1)

        if table:
            summary = [{
                "id": workspace.get("id", ""),
                "name": workspace.get("name", ""),
                "plan": workspace.get("plan", ""),
                "entities": str(len(workspace.get("entities", []))),
                "bookkeepingStart": workspace.get("bookkeepingStartDate", ""),
            }]

            print_table(
                summary,
                ["id", "name", "plan", "entities", "bookkeepingStart"],
                ["ID", "Name", "Plan", "Entities", "Bookkeeping Start"],
            )
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
