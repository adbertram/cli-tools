"""Table schema commands for Airtable CLI."""
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
from cli_tools_shared.filters import apply_filters, apply_properties_filter
from cli_tools_shared.output import print_json, print_table, handle_error, print_success

app = typer.Typer(help="Manage Airtable tables", no_args_is_help=True)


def parse_fields(fields_json: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Parse Airtable fields array from a JSON string."""
    if fields_json is None:
        return None
    try:
        parsed = json.loads(fields_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"--fields must be valid JSON: {e}") from e
    if not isinstance(parsed, list):
        raise ValueError("--fields must be a JSON array of field objects")
    for entry in parsed:
        if not isinstance(entry, dict):
            raise ValueError("--fields entries must be JSON objects")
    return parsed


def print_table_schema(result: Dict[str, Any], table: bool) -> None:
    """Print a single table schema response."""
    if not table:
        print_json(result)
        return

    row = {
        "id": result.get("id", ""),
        "name": result.get("name", ""),
        "primary_field_id": result.get("primaryFieldId", ""),
        "description": result.get("description", ""),
        "field_count": len(result.get("fields", [])),
    }
    print_table(
        [row],
        list(row.keys()),
        ["ID", "Name", "Primary Field ID", "Description", "Field Count"],
    )


def summarize_table(result: Dict[str, Any]) -> Dict[str, Any]:
    """Return the flat list-view representation for a table schema."""
    return {
        "id": result.get("id", ""),
        "name": result.get("name", ""),
        "primaryFieldId": result.get("primaryFieldId", ""),
        "description": result.get("description", ""),
        "field_count": len(result.get("fields", [])),
    }


@app.command("list")
def tables_list(
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum tables to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:Tasks, name:contains:log)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include in output"),
):
    """
    List tables in an Airtable base.

    Examples:
        airtable tables list
        airtable tables list --base appXXXXXXXXXXXXXX --table
        airtable tables list --filter "name:contains:log"
    """
    try:
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()
        tables = client.list_tables(base_id=resolved_base_id)

        if filter:
            tables = apply_filters(tables, filter)

        if limit and len(tables) > limit:
            tables = tables[:limit]

        summarized_tables = [summarize_table(table_schema) for table_schema in tables]

        if properties:
            summarized_tables = apply_properties_filter(summarized_tables, properties)

        if not table:
            print_json(summarized_tables)
            return

        rows = []
        for table_schema in summarized_tables:
            rows.append({
                "id": table_schema.get("id", ""),
                "name": table_schema.get("name", ""),
                "primary_field_id": table_schema.get("primaryFieldId", ""),
                "description": table_schema.get("description", ""),
                "field_count": table_schema.get("field_count", ""),
            })
        print_table(
            rows,
            ["id", "name", "primary_field_id", "description", "field_count"],
            ["ID", "Name", "Primary Field ID", "Description", "Field Count"],
        )
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def tables_get(
    table_id: str = typer.Argument(..., help="The table ID (beginning with tbl) or table name"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get one table schema by ID or name."""
    try:
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()
        result = client.get_table(base_id=resolved_base_id, table_id=table_id)
        print_table_schema(result, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def tables_create(
    name: str = typer.Argument(..., help="The new table name"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Table description (max 20,000 chars)"),
    fields: Optional[str] = typer.Option(None, "--fields", help="Fields as a JSON array of {name, type, ...} objects. Defaults to a single primary 'Name' singleLineText field if omitted."),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Create a new table in an Airtable base.

    The Meta API requires at least one field; if --fields is omitted, a single
    primary field named "Name" of type singleLineText is created.

    Examples:
        airtable tables create "Tasks"
        airtable tables create "Tasks" --description "Task tracker"
        airtable tables create "Tasks" --fields '[{"name":"Title","type":"singleLineText"},{"name":"Done","type":"checkbox","options":{"icon":"check","color":"greenBright"}}]'
    """
    try:
        parsed_fields = parse_fields(fields)
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()
        result = client.create_table(
            base_id=resolved_base_id,
            name=name,
            description=description,
            fields=parsed_fields,
        )
        print_success(f"Table created with ID: {result.get('id')}")
        print_table_schema(result, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def tables_update(
    table_id: str = typer.Argument(..., help="The table ID (beginning with tbl) or table name"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="New table name"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New table description"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Update a table's name or description.

    Examples:
        airtable tables update tblXXXXXXXXXXXXXX --name "Renamed Table"
        airtable tables update "Tasks" --description "Updated description"
    """
    try:
        if name is None and description is None:
            raise ValueError("At least one of --name or --description must be specified")
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()
        result = client.update_table(
            base_id=resolved_base_id,
            table_id=table_id,
            name=name,
            description=description,
        )
        print_success(f"Table {table_id} updated successfully")
        print_table_schema(result, table)
    except Exception as e:
        raise typer.Exit(handle_error(e))
