"""Statistics commands for Kick CLI.

Note: Statistics is singular aggregate data, not a collection of resources.
Therefore it only has a 'get' command, not list/get pattern.
"""
import typer
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Get Kick transaction statistics")


def format_currency(val: float) -> str:
    """Format a value as currency."""
    if val >= 0:
        return f"${val:,.2f}"
    return f"-${abs(val):,.2f}"


@app.command("get")
def statistics_get(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    workspace_id: Optional[str] = typer.Option(None, "--workspace-id", "-w", help="Workspace UUID (uses default if not provided)"),
    entity_id: Optional[int] = typer.Option(None, "--entity-id", "-e", help="Filter by entity ID"),
):
    """
    Get transaction statistics for a workspace.

    Returns aggregate statistics including total, cash in/out, average, and count.

    Examples:
        kick statistics get
        kick statistics get --table
        kick statistics get --entity-id 16044
    """
    try:
        client = get_client()

        ws_id = workspace_id or client.get_default_workspace_id()

        # Get entity IDs
        if entity_id:
            entity_ids = [entity_id]
        else:
            entity_ids = client.get_entity_ids(ws_id)

        # Build params
        params = {"workspaceId": ws_id}
        for i, eid in enumerate(entity_ids):
            params[f"filters[entityIds][{i}]"] = eid

        stats = client._make_request("GET", "/api/transactions/statistics", params=params)

        if table:
            table_data = [{
                "total": format_currency(stats.get("total", 0)),
                "cashIn": format_currency(stats.get("cashIn", 0)),
                "cashOut": format_currency(stats.get("cashOut", 0)),
                "average": format_currency(stats.get("average", 0)),
                "count": str(stats.get("count", 0)),
            }]

            print_table(
                table_data,
                ["total", "cashIn", "cashOut", "average", "count"],
                ["Net Total", "Cash In", "Cash Out", "Average", "Count"],
            )
        else:
            print_json(stats)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ]
}
