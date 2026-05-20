"""Field schema commands for Airtable CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "personal_access_token"
    ],
    "create": [
        "personal_access_token"
    ],
    "list": [
        "personal_access_token"
    ],
    "update": [
        "personal_access_token"
    ]
}

import json
from typing import Any, Dict, List, Optional

import typer

from ..client import get_client
from ..commands.records import resolve_base_id
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import print_json, print_table, handle_error, print_success

app = typer.Typer(help="Manage Airtable fields", no_args_is_help=True)


def parse_options(options: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse Airtable field options from a JSON object string."""
    if options is None:
        return None
    try:
        parsed = json.loads(options)
    except json.JSONDecodeError as e:
        raise ValueError(f"--options must be valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("--options must be a JSON object")
    return parsed


def print_field(result: Dict[str, Any], table: bool) -> None:
    """Print a field schema response."""
    if not table:
        print_json(result)
        return

    row = {
        "id": result.get("id", ""),
        "name": result.get("name", ""),
        "type": result.get("type", ""),
        "description": result.get("description", ""),
        "options": json.dumps(result.get("options", {}), sort_keys=True),
    }
    print_table([row], list(row.keys()), ["ID", "Name", "Type", "Description", "Options"])


@app.command("list")
def fields_list(
    table_id: str = typer.Argument(..., help="The table ID or table name"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum fields to return"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:Status, type:eq:singleLineText)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated list of fields to include in output"
    ),
):
    """
    List fields in an Airtable table.

    Examples:
        airtable fields list tblXXXXXXXXXXXXXX
        airtable fields list "Slides" --table
    """
    try:
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()
        result = client.list_fields(
            base_id=resolved_base_id,
            table_id=table_id,
        )
        if filter:
            validate_filters(filter)
            result = apply_filters(result, filter)
        if limit and len(result) > limit:
            result = result[:limit]
        if properties:
            result = apply_properties_filter(result, properties)
        if not table:
            print_json(result)
            return

        rows = []
        for field in result:
            rows.append({
                "id": field.get("id", ""),
                "name": field.get("name", ""),
                "type": field.get("type", ""),
                "description": field.get("description", ""),
                "options": json.dumps(field.get("options", {}), sort_keys=True),
            })
        print_table(rows, ["id", "name", "type", "description", "options"], ["ID", "Name", "Type", "Description", "Options"])
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def fields_get(
    table_id: str = typer.Argument(..., help="The table ID or table name"),
    field_id: str = typer.Argument(..., help="The field ID or field name"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a single field schema by ID or name."""
    try:
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()
        result = client.get_field(
            base_id=resolved_base_id,
            table_id=table_id,
            field_id=field_id,
        )
        print_field(result, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))



@app.command("create")
def fields_create(
    table_id: str = typer.Argument(..., help="The table ID, beginning with tbl"),
    name: str = typer.Argument(..., help="The field name"),
    field_type: str = typer.Argument(..., help="The Airtable field type, such as singleLineText"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Field description"),
    options: Optional[str] = typer.Option(None, "--options", "-o", help="Field options as a JSON object"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Create a field in an Airtable table.

    Examples:
        airtable fields create tblXXXXXXXXXXXXXX "Status" singleLineText
        airtable fields create tblXXXXXXXXXXXXXX "Done" checkbox --options '{"icon":"check","color":"greenBright"}'
    """
    try:
        parsed_options = parse_options(options)
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()
        result = client.create_field(
            base_id=resolved_base_id,
            table_id=table_id,
            name=name,
            field_type=field_type,
            description=description,
            options=parsed_options,
        )
        print_success(f"Field created with ID: {result.get('id')}")
        print_field(result, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def fields_update(
    table_id: str = typer.Argument(..., help="The table ID, beginning with tbl"),
    field_id: str = typer.Argument(..., help="The field ID, beginning with fld"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="New field name"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New field description"),
    options: Optional[str] = typer.Option(None, "--options", "-o", help="Field options as a JSON object"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Update a field's name, description, or options.

    Examples:
        airtable fields update tblXXXXXXXXXXXXXX fldXXXXXXXXXXXXXX --name "New Status"
        airtable fields update tblXXXXXXXXXXXXXX fldXXXXXXXXXXXXXX --options '{"formula":"{Hours} * {Rate}"}'
    """
    try:
        parsed_options = parse_options(options)
        if name is None and description is None and parsed_options is None:
            raise ValueError("At least one of --name, --description, or --options must be specified")
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()
        result = client.update_field(
            base_id=resolved_base_id,
            table_id=table_id,
            field_id=field_id,
            name=name,
            description=description,
            options=parsed_options,
        )
        print_success(f"Field {field_id} updated successfully")
        print_field(result, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))
