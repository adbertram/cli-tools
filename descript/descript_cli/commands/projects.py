"""Projects commands for Descript CLI."""
from typing import Optional, List

import typer

from ..client import get_client, ClientError
from cli_tools_shared.filters import validate_filters, apply_filters
from cli_tools_shared import FilterMap
from cli_tools_shared.output import print_json, print_table, print_error, handle_error

app = typer.Typer(help="Manage Descript projects", no_args_is_help=True)


def _resolve_property(data: dict, prop: str):
    """Resolve a property path like 'owner.email' from a nested dict."""
    parts = prop.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


@app.command("list")
def list_projects(
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of projects to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot notation: owner.email)"),
):
    """
    List your Descript projects.

    Example:
        descript projects list
        descript projects list --limit 10
        descript projects list --table
        descript projects list --filter "name:contains:Cursor"
        descript projects list -p "name,composition_count"
        descript projects list -p "name,owner.email"
    """
    try:
        client = get_client()
        projects = client.list_projects(limit=limit)

        # Apply client-side filtering
        if filter:
            try:
                validate_filters(filter)
            except Exception:
                pass
            projects = apply_filters([p.model_dump() for p in projects], filter)
            output_data = projects if isinstance(projects, list) and all(isinstance(p, dict) for p in projects) else [p.model_dump() for p in projects]
        else:
            output_data = [p.model_dump() for p in projects]

        # Select properties (supports dot notation)
        if properties:
            selected = [p.strip() for p in properties.split(",")]
            output_data = [
                {prop: _resolve_property(row, prop) for prop in selected}
                for row in output_data
            ]

        if table:
            if output_data:
                headers = list(output_data[0].keys())
                display_headers = [h.replace("_", " ").replace(".", " ").title() for h in headers]
                print_table(output_data, headers, display_headers)
            else:
                print_error("No projects found")
        else:
            print_json(output_data)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_project(
    project_id: str = typer.Argument(help="Project ID (UUID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific project by ID.

    Example:
        descript projects get <project-id>
        descript projects get <project-id> --table
    """
    try:
        client = get_client()
        project = client.get_project(project_id)
        output = project.model_dump()

        if table:
            headers = list(output.keys())
            display_headers = [h.replace("_", " ").title() for h in headers]
            print_table([output], headers, display_headers)
        else:
            print_json(output)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
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
