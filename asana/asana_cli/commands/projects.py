"""Project commands for Asana CLI."""
import typer
from typing import Optional, List
from ..client import get_client
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage Asana projects")


def extract_field(data, field_path: str):
    """Extract a field value using dot notation (e.g., 'owner.name')."""
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
def project_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="Workspace ID"),
    limit: Optional[int] = typer.Option(100, "--limit", "-l", help="Limit number of results"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Output single field (e.g., 'gid', 'name')"),
):
    """List projects in workspace."""
    try:
        # Validate filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                typer.echo(f"Filter error: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        projects = client.list_projects(workspace_id=workspace, limit=limit)

        # Apply filters if provided
        if filter_:
            projects = apply_filters(projects, filter_)

        if properties:
            for project in projects:
                value = extract_field(project, properties)
                if value is not None:
                    print(value)
        elif table:
            print_table(
                projects,
                ["gid", "name"],
                ["ID", "Name"]
            )
        else:
            print_json(projects)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def project_get(
    project_id: str = typer.Argument(..., help="Project ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get project details."""
    try:
        client = get_client()
        project = client.get_project(project_id)

        if table:
            # Flatten for table display
            data = {
                "gid": project.get("gid"),
                "name": project.get("name"),
                "owner": project.get("owner", {}).get("name", ""),
                "archived": project.get("archived"),
                "public": project.get("public"),
            }
            print_table([data], list(data.keys()), ["ID", "Name", "Owner", "Archived", "Public"])
        else:
            print_json(project)
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
