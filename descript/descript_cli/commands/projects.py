"""Projects commands for Descript CLI."""
from typing import Optional, List

import typer

from ..platform import (
    PlatformCLIError,
    get_project_json,
    list_projects_json,
    select_object_properties,
    select_properties,
)
from cli_tools_shared.filters import apply_filters, validate_filters
from cli_tools_shared.output import print_json, print_table, print_error, handle_error

app = typer.Typer(help="Manage Descript projects", no_args_is_help=True)


@app.command("list")
def list_projects(
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of projects to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot notation: owner.email)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Filter projects whose name contains this text"),
    folder_path: Optional[str] = typer.Option(None, "--folder-path", help="Filter projects by folder path"),
    created_by: Optional[str] = typer.Option(None, "--created-by", help="Filter by creator user ID; use 'me' for current user"),
    created_after: Optional[str] = typer.Option(None, "--created-after", help="Filter projects created after this ISO 8601 timestamp"),
    created_before: Optional[str] = typer.Option(None, "--created-before", help="Filter projects created before this ISO 8601 timestamp"),
    updated_after: Optional[str] = typer.Option(None, "--updated-after", help="Filter projects updated after this ISO 8601 timestamp"),
    updated_before: Optional[str] = typer.Option(None, "--updated-before", help="Filter projects updated before this ISO 8601 timestamp"),
    sort: Optional[str] = typer.Option(None, "--sort", "-s", help="Sort field: name, created_at, updated_at, last_viewed_at"),
    direction: Optional[str] = typer.Option(None, "--direction", help="Sort direction: asc, desc"),
    cursor: Optional[str] = typer.Option(None, "--cursor", help="Pagination cursor from a previous response"),
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
        output_data = list_projects_json(
            limit=limit,
            name=name,
            folder_path=folder_path,
            created_by=created_by,
            created_after=created_after,
            created_before=created_before,
            updated_after=updated_after,
            updated_before=updated_before,
            sort=sort,
            direction=direction,
            cursor=cursor,
        )

        if filter:
            try:
                validate_filters(filter)
            except Exception as e:
                print_error(str(e))
                raise typer.Exit(1)
            output_data = apply_filters(output_data, filter)

        output_data = select_properties(output_data, properties)

        if table:
            if output_data:
                headers = list(output_data[0].keys())
                display_headers = [h.replace("_", " ").replace(".", " ").title() for h in headers]
                print_table(output_data, headers, display_headers)
            else:
                print_error("No projects found")
        else:
            print_json(output_data)

    except PlatformCLIError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_project(
    project_id: str = typer.Argument(help="Project ID (UUID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    Get a specific project by ID.

    Example:
        descript projects get <project-id>
        descript projects get <project-id> --table
    """
    try:
        output = select_object_properties(get_project_json(project_id), properties)

        if table:
            headers = list(output.keys())
            display_headers = [h.replace("_", " ").title() for h in headers]
            print_table([output], headers, display_headers)
        else:
            print_json(output)

    except PlatformCLIError as e:
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
