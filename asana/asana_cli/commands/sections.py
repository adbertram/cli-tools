"""Section commands for Asana CLI."""
import typer
from typing import Optional, List
from ..client import get_client
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage Asana sections")


def extract_field(data, field_path: str):
    """Extract a field value using dot notation (e.g., 'project.name')."""
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
def section_list(
    project: str = typer.Option(..., "--project", "-p", help="Project ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(100, "--limit", "-l", help="Limit number of results"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Output single field (e.g., 'gid', 'name')"),
):
    """List sections in a project."""
    try:
        # Validate filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                typer.echo(f"Filter error: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        sections = client.list_sections(project, limit=limit)

        # Apply filters if provided
        if filter_:
            sections = apply_filters(sections, filter_)

        if properties:
            for section in sections:
                value = extract_field(section, properties)
                if value is not None:
                    print(value)
        elif table:
            print_table(
                sections,
                ["gid", "name"],
                ["ID", "Name"]
            )
        else:
            print_json(sections)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def section_get(
    section_id: str = typer.Argument(..., help="Section ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get section details."""
    try:
        client = get_client()
        section = client.get_section(section_id)

        if table:
            data = {
                "gid": section.get("gid"),
                "name": section.get("name"),
                "project": section.get("project", {}).get("name", ""),
            }
            print_table([data], list(data.keys()), ["ID", "Name", "Project"])
        else:
            print_json(section)
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
