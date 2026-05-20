"""Data Tables commands - list, create, delete tables; list, insert, delete rows."""
import json
import sys
import typer
from typing import Optional, List

from ..n8n_api import get_n8n_api_client
from cli_tools_shared.output import print_json, print_table, print_error, print_success, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit

app = typer.Typer(help="Manage n8n Data Tables", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "columns": [
        "api_key"
    ],
    "create": [
        "api_key"
    ],
    "delete": [
        "api_key"
    ],
    "delete-rows": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "insert": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "rows": [
        "api_key"
    ],
    "update-rows": [
        "api_key"
    ]
}


@app.command("list")
def tables_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all data tables.

    Example:
        n8n data-tables list
        n8n data-tables list --table
        n8n data-tables list --filter "name:contains:orders"
        n8n data-tables list --properties "id,name"
    """
    try:
        api = get_n8n_api_client()
        data = api.list_data_tables()

        if filter:
            data = apply_filters(data, filter)

        data = apply_limit(data, limit)

        if properties:
            data = apply_properties_filter(data, properties)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(data, fields, fields)
            else:
                print_table(data, ["id", "name", "createdAt"], ["ID", "Name", "Created"])
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def tables_get(
    table_id: str = typer.Argument(..., help="Data table ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a data table by ID, including its columns.

    Example:
        n8n data-tables get L13pmzZlnNh5hPw7
        n8n data-tables get L13pmzZlnNh5hPw7 --table
    """
    try:
        api = get_n8n_api_client()
        all_tables = api.list_data_tables()

        match = None
        for t in all_tables:
            if str(t.get("id")) == table_id:
                match = t
                break

        if not match:
            print_error(f"Data table '{table_id}' not found")
            raise typer.Exit(1)

        # Enrich with columns
        columns = api.get_data_table_columns(table_id)
        match["columns"] = columns

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in match.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(match)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def tables_create(
    name: str = typer.Argument(..., help="Table name"),
    column: Optional[List[str]] = typer.Option(None, "--column", "-c", help="Column definition as name:type (repeatable)"),
):
    """
    Create a new data table.

    Column types: string, number, boolean, date

    Example:
        n8n data-tables create "Orders" --column "name:string" --column "total:number"
        n8n data-tables create "Flags" --column "key:string" --column "enabled:boolean"
    """
    try:
        if not column:
            print_error("At least one --column is required (e.g., --column 'name:string')")
            raise typer.Exit(1)

        columns = []
        for col_def in column:
            parts = col_def.split(":", 1)
            if len(parts) != 2:
                print_error(f"Invalid column format '{col_def}'. Expected name:type (e.g., name:string)")
                raise typer.Exit(1)
            col_name, col_type = parts
            valid_types = {"string", "number", "boolean", "date"}
            if col_type not in valid_types:
                print_error(f"Invalid column type '{col_type}'. Must be one of: {', '.join(sorted(valid_types))}")
                raise typer.Exit(1)
            columns.append({"name": col_name, "type": col_type})

        api = get_n8n_api_client()
        result = api.create_data_table(name, columns)

        print_success(f"Created data table '{result.get('name', name)}' (id: {result.get('id', 'unknown')})")
        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def tables_delete(
    table_id: str = typer.Argument(..., help="Data table ID to delete"),
):
    """
    Delete a data table.

    Example:
        n8n data-tables delete L13pmzZlnNh5hPw7
    """
    try:
        api = get_n8n_api_client()
        api.delete_data_table(table_id)
        print_success(f"Deleted data table (id: {table_id})")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("columns")
def tables_columns(
    table_id: str = typer.Argument(..., help="Data table ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Show columns for a data table.

    Example:
        n8n data-tables columns L13pmzZlnNh5hPw7
        n8n data-tables columns L13pmzZlnNh5hPw7 --table
    """
    try:
        api = get_n8n_api_client()
        data = api.get_data_table_columns(table_id)

        if table:
            print_table(data, ["id", "name", "type"], ["ID", "Name", "Type"])
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("rows")
def tables_rows(
    table_id: str = typer.Argument(..., help="Data table ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of rows"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List rows in a data table.

    Example:
        n8n data-tables rows L13pmzZlnNh5hPw7
        n8n data-tables rows L13pmzZlnNh5hPw7 --table --limit 10
        n8n data-tables rows L13pmzZlnNh5hPw7 --filter "status:eq:active"
    """
    try:
        api = get_n8n_api_client()
        data = api.list_data_table_rows(table_id, limit=limit)

        if filter:
            data = apply_filters(data, filter)

        data = apply_limit(data, limit)

        if properties:
            data = apply_properties_filter(data, properties)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(data, fields, fields)
            else:
                print_table(data)
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("insert")
def tables_insert(
    table_id: str = typer.Argument(..., help="Data table ID"),
    data: Optional[str] = typer.Argument(None, help="JSON array of row objects (or pipe via stdin)"),
):
    """
    Insert rows into a data table.

    Accepts a JSON array of objects as an argument or via stdin.

    Example:
        n8n data-tables insert L13pmzZlnNh5hPw7 '[{"name":"test","value":42}]'
        echo '[{"name":"test"}]' | n8n data-tables insert L13pmzZlnNh5hPw7
    """
    try:
        json_str = data
        if not json_str:
            if sys.stdin.isatty():
                print_error("Provide JSON data as argument or pipe via stdin")
                raise typer.Exit(1)
            json_str = sys.stdin.read()

        try:
            rows = json.loads(json_str)
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON: {e}")
            raise typer.Exit(1)

        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            print_error("JSON data must be an array of objects")
            raise typer.Exit(1)

        api = get_n8n_api_client()
        result = api.insert_data_table_rows(table_id, rows)

        print_success(f"Inserted {len(rows)} row(s)")
        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update-rows")
def tables_update_rows(
    table_id: str = typer.Argument(..., help="Data table ID"),
    row_id: int = typer.Argument(..., help="Row ID (integer)"),
    data: str = typer.Argument(..., help="JSON object of column:value pairs to update"),
):
    """
    Update a row in a data table by row ID.

    Accepts a JSON object with the columns to update.

    Example:
        n8n data-tables update-rows TABLE_ID 1 '{"last_status":"ok","last_checked":"2026-02-20T14:00:00Z"}'
    """
    try:
        try:
            update_data = json.loads(data)
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON: {e}")
            raise typer.Exit(1)

        if not isinstance(update_data, dict):
            print_error("JSON data must be an object (not array)")
            raise typer.Exit(1)

        api = get_n8n_api_client()
        result = api.update_data_table_rows(table_id, row_id, update_data)

        print_success(f"Updated row {row_id}")
        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete-rows")
def tables_delete_rows(
    table_id: str = typer.Argument(..., help="Data table ID"),
    row_id: List[str] = typer.Option(..., "--row-id", "-r", help="Row ID to delete (repeatable)"),
):
    """
    Delete specific rows from a data table.

    Example:
        n8n data-tables delete-rows L13pmzZlnNh5hPw7 --row-id row123
        n8n data-tables delete-rows L13pmzZlnNh5hPw7 --row-id row1 --row-id row2
    """
    try:
        api = get_n8n_api_client()
        result = api.delete_data_table_rows(table_id, row_id)

        print_success(f"Deleted {len(row_id)} row(s)")
        if result:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
