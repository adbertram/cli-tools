"""Entities commands for Kick CLI."""
import typer
from typing import Optional, List

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage Kick entities (business/personal units)")


@app.command("list")
def entities_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of entities to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to display"),
    workspace_id: Optional[str] = typer.Option(None, "--workspace-id", "-w", help="Workspace UUID (uses default if not provided)"),
):
    """
    List all entities in a workspace.

    Entities are business or personal units used to organize transactions.

    Examples:
        kick entities list
        kick entities list --table
        kick entities list --filter "isBusiness:true"
    """
    try:
        client = get_client()
        workspaces = client.get_workspaces()

        ws_id = workspace_id or client.get_default_workspace_id()

        entities = []
        for ws_data in workspaces:
            if ws_data["workspace"]["id"] == ws_id:
                entities = ws_data["workspace"].get("entities", [])
                break

        # Apply client-side filtering (API doesn't support filtering)
        if filter:
            entities = apply_filters(entities, filter)

        # Apply limit
        entities = entities[:limit]

        if table:
            table_data = []
            for entity in entities:
                entity_type = "Personal" if entity.get("isPersonal") else "Business"
                table_data.append({
                    "id": str(entity.get("id", "")),
                    "name": entity.get("name", ""),
                    "type": entity_type,
                    "legalType": entity.get("legalType") or "",
                    "industry": entity.get("industry", ""),
                })

            print_table(
                table_data,
                ["id", "name", "type", "legalType", "industry"],
                ["ID", "Name", "Type", "Legal Type", "Industry"],
            )
            from cli_tools_shared.output import print_info
            print_info(f"Showing {len(entities)} entities")
        else:
            print_json(entities)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def entities_get(
    entity_id: int = typer.Argument(..., help="The entity ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    workspace_id: Optional[str] = typer.Option(None, "--workspace-id", "-w", help="Workspace UUID (uses default if not provided)"),
):
    """
    Get details for a specific entity.

    Examples:
        kick entities get 16044
        kick entities get 16044 --table
    """
    try:
        client = get_client()
        workspaces = client.get_workspaces()

        ws_id = workspace_id or client.get_default_workspace_id()

        entity = None
        for ws_data in workspaces:
            if ws_data["workspace"]["id"] == ws_id:
                for e in ws_data["workspace"].get("entities", []):
                    if e["id"] == entity_id:
                        entity = e
                        break
                break

        if not entity:
            from cli_tools_shared.output import print_error
            print_error(f"Entity {entity_id} not found")
            raise typer.Exit(1)

        if table:
            entity_type = "Personal" if entity.get("isPersonal") else "Business"
            summary = [{
                "id": str(entity.get("id", "")),
                "name": entity.get("name", ""),
                "type": entity_type,
                "legalType": entity.get("legalType") or "",
                "industry": entity.get("industry", ""),
                "bookkeepingStart": entity.get("bookkeepingStartDate", ""),
                "federalTaxRate": f"{entity.get('federalTaxRate', 0) * 100:.0f}%",
            }]

            print_table(
                summary,
                ["id", "name", "type", "legalType", "industry", "bookkeepingStart", "federalTaxRate"],
                ["ID", "Name", "Type", "Legal Type", "Industry", "Bookkeeping Start", "Tax Rate"],
            )
        else:
            print_json(entity)

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
