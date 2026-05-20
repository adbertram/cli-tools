"""Custom field commands for Asana CLI."""
import typer
from typing import Optional, List
from ..client import get_client
from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage Asana custom fields")


def extract_field(data, field_path: str):
    """Extract a field value using dot notation (e.g., 'custom_field.name')."""
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
def custom_field_list(
    project: str = typer.Option(..., "--project", "-p", help="Project ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(100, "--limit", "-l", help="Limit number of results"),
    filter_: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Output single field (e.g., 'custom_field.gid', 'custom_field.name')"),
):
    """List custom fields for a project with enum options."""
    try:
        # Validate filters first
        if filter_:
            try:
                validate_filters(filter_)
            except FilterValidationError as e:
                typer.echo(f"Filter error: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        fields = client.list_custom_fields(project, limit=limit)

        # Apply filters if provided
        if filter_:
            fields = apply_filters(fields, filter_)

        if properties:
            for field in fields:
                value = extract_field(field, properties)
                if value is not None:
                    print(value)
        elif table:
            # Extract custom field info
            rows = []
            for item in fields:
                cf = item.get("custom_field", {})
                rows.append({
                    "gid": cf.get("gid"),
                    "name": cf.get("name"),
                    "type": cf.get("type"),
                    "description": cf.get("description", "")[:50],
                })
            print_table(
                rows,
                ["gid", "name", "type", "description"],
                ["ID", "Name", "Type", "Description"]
            )
        else:
            print_json(fields)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def custom_field_get(
    field_id: str = typer.Argument(..., help="Custom field ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get custom field details including enum options."""
    try:
        client = get_client()
        field = client.get_custom_field(field_id)

        if table:
            data = {
                "gid": field.get("gid"),
                "name": field.get("name"),
                "type": field.get("type"),
                "description": field.get("description", ""),
            }
            print_table([data], list(data.keys()), ["ID", "Name", "Type", "Description"])

            # Show enum options separately if available
            enum_options = field.get("enum_options", [])
            if enum_options:
                print("\nEnum Options:", file=__import__('sys').stderr)
                print_table(
                    enum_options,
                    ["gid", "name", "enabled"],
                    ["ID", "Name", "Enabled"]
                )
        else:
            print_json(field)
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
