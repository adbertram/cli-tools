"""Records commands for Airtable CLI."""
COMMAND_CREDENTIALS = {
    "create": [
        "personal_access_token"
    ],
    "delete": [
        "personal_access_token"
    ],
    "get": [
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
import typer
from typing import Optional, List

from ..client import get_client
from ..config import get_config
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info, print_error
from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters
from ..parsers import format_local_time

app = typer.Typer(help="Manage Airtable records")


def resolve_base_id(base_id: Optional[str]) -> str:
    """Resolve base_id from argument or config default."""
    if base_id:
        return base_id
    config = get_config()
    if config.default_base_id:
        return config.default_base_id
    print_error("No base_id provided and no default AIRTABLE_BASE_ID configured in .env")
    raise typer.Exit(1)


@app.command("list")
def records_list(
    table_id: str = typer.Argument(..., help="The table ID or name"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to BASE_ID in .env)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum total records to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include in output"),
    offset: Optional[str] = typer.Option(None, "--offset", "-o", help="Offset for pagination"),
    view: Optional[str] = typer.Option(None, "--view", help="View name or ID to filter"),
    sort_field: Optional[str] = typer.Option(None, "--sort-field", help="Field to sort by"),
    sort_direction: Optional[str] = typer.Option("asc", "--sort-direction", help="Sort direction (asc/desc)"),
    formula: Optional[str] = typer.Option(None, "--formula", help="Airtable filterByFormula (raw formula)"),
):
    """
    List records from an Airtable table.

    Examples:
        # List all records from a table (uses default base)
        airtable records list "Table Name"

        # List with explicit base ID
        airtable records list "Tasks" --base appXXX

        # Limit results
        airtable records list "Tasks" --limit 10

        # Filter with standard syntax
        airtable records list "Tasks" --filter "Status:eq:Active"

        # Filter with raw Airtable formula
        airtable records list "Tasks" --formula "Status='Active'"

        # List with sorting
        airtable records list "Tasks" --sort-field "Created" --sort-direction desc

        # Select specific properties
        airtable records list "Tasks" --properties "Name,Status,Priority"

        # Display as table
        airtable records list "Tasks" --table
    """
    try:
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()

        # Build sort parameter
        sort_param = None
        if sort_field:
            sort_param = [{"field": sort_field, "direction": sort_direction}]

        result = client.list_records(
            base_id=resolved_base_id,
            table_id=table_id,
            limit=limit,
            offset=offset,
            view=view,
            sort=sort_param,
            filter_by_formula=formula,
            fields=None,
            filters=filter,
        )

        records = result.get("records", [])

        # Apply properties selection to output
        if properties:
            prop_list = [f.strip() for f in properties.split(",")]
            filtered_records = []
            for record in records:
                filtered = {"id": record.get("id", "")}
                record_fields = record.get("fields", {})
                for prop in prop_list:
                    if prop in record_fields:
                        filtered[prop] = record_fields[prop]
                filtered_records.append(filtered)
        else:
            filtered_records = records

        if table:
            # For table display, flatten the fields
            table_data = []
            for record in filtered_records:
                if "fields" in record:
                    row = {
                        "id": record.get("id", ""),
                        "created": format_local_time(record.get("createdTime", "")),
                    }
                    for field_name, field_value in record.get("fields", {}).items():
                        if isinstance(field_value, (list, dict)):
                            row[field_name] = json.dumps(field_value)
                        else:
                            row[field_name] = field_value
                else:
                    row = {}
                    for k, v in record.items():
                        if isinstance(v, (list, dict)):
                            row[k] = json.dumps(v)
                        else:
                            row[k] = v
                table_data.append(row)

            if table_data:
                all_field_names = set()
                for row in table_data:
                    all_field_names.update(row.keys())
                columns = ["id"] + sorted([f for f in all_field_names if f != "id"])
                headers = [c.replace("_", " ").title() for c in columns]
                print_table(table_data, columns, headers)
            else:
                print_info("No records found")
        else:
            if properties:
                print_json(filtered_records)
            else:
                print_json(result)

        # Show pagination info if there's an offset
        if result.get("offset"):
            print_info(f"More records available. Use --offset {result['offset']} to fetch next page")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def records_get(
    table_id: str = typer.Argument(..., help="The table ID or name"),
    record_id: str = typer.Argument(..., help="The record ID"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific record by ID.

    Examples:
        airtable records get "Tasks" recXXXXXXXXXXXXXX
        airtable records get "Tasks" recXXX --table
    """
    try:
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()
        record = client.get_record(resolved_base_id, table_id, record_id)

        if table:
            # Flatten for table display
            row = {
                "id": record.get("id", ""),
                "created": format_local_time(record.get("createdTime", "")),
            }
            for field_name, field_value in record.get("fields", {}).items():
                if isinstance(field_value, (list, dict)):
                    row[field_name] = json.dumps(field_value)
                else:
                    row[field_name] = field_value

            columns = list(row.keys())
            headers = [c.replace("_", " ").title() for c in columns]
            print_table([row], columns, headers)
        else:
            print_json(record)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def records_update(
    table_id: str = typer.Argument(..., help="The table ID or name"),
    record_id: str = typer.Argument(..., help="The record ID"),
    field_values: List[str] = typer.Argument(..., help="Field updates as 'FieldName=value' pairs"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    typecast: bool = typer.Option(False, "--typecast", help="Enable automatic type conversion"),
    replace: bool = typer.Option(False, "--replace", help="Replace entire record (PUT) instead of updating (PATCH)"),
):
    """
    Update a record's fields.

    Use PATCH (default) to update only specified fields, or --replace for PUT to clear unspecified fields.

    Examples:
        # Update specific fields (PATCH)
        airtable records update "Tasks" recXXX "Status=Complete" "Priority=High"

        # Replace entire record (PUT - clears other fields)
        airtable records update "Tasks" recXXX "Name=New Task" --replace

        # With typecast for automatic data conversion
        airtable records update "Tasks" recXXX "Completed=true" --typecast
    """
    try:
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()

        # Parse field_values into a dictionary
        fields = {}
        for item in field_values:
            if "=" not in item:
                print_info(f"Skipping invalid field format: {item} (expected FieldName=value)")
                continue

            field_name, field_value = item.split("=", 1)
            field_name = field_name.strip()
            field_value = field_value.strip()

            # Try to parse as JSON for complex values
            try:
                fields[field_name] = json.loads(field_value)
            except json.JSONDecodeError:
                # Use as string if not valid JSON
                fields[field_name] = field_value

        if not fields:
            print_info("No valid field updates provided")
            raise typer.Exit(1)

        if replace:
            result = client.replace_record(resolved_base_id, table_id, record_id, fields, typecast)
            print_success(f"Record {record_id} replaced successfully")
        else:
            result = client.update_record(resolved_base_id, table_id, record_id, fields, typecast)
            print_success(f"Record {record_id} updated successfully")

        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def records_create(
    table_id: str = typer.Argument(..., help="The table ID or name"),
    field_values: List[str] = typer.Argument(..., help="Field values as 'FieldName=value' pairs"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    typecast: bool = typer.Option(False, "--typecast", help="Enable automatic type conversion"),
):
    """
    Create a new record.

    Examples:
        # Create a simple record
        airtable records create "Tasks" "Name=New Task" "Status=Todo"

        # Create with typecast
        airtable records create "Tasks" "Name=Task" "Priority=1" --typecast

        # Create with JSON values
        airtable records create "Tasks" 'Tags=["urgent","work"]'
    """
    try:
        resolved_base_id = resolve_base_id(base_id)
        client = get_client()

        # Parse field_values into a dictionary
        fields = {}
        for item in field_values:
            if "=" not in item:
                print_info(f"Skipping invalid field format: {item} (expected FieldName=value)")
                continue

            field_name, field_value = item.split("=", 1)
            field_name = field_name.strip()
            field_value = field_value.strip()

            # Try to parse as JSON for complex values
            try:
                fields[field_name] = json.loads(field_value)
            except json.JSONDecodeError:
                # Use as string if not valid JSON
                fields[field_name] = field_value

        if not fields:
            print_info("No valid field values provided")
            raise typer.Exit(1)

        result = client.create_record(resolved_base_id, table_id, fields, typecast)
        print_success(f"Record created with ID: {result.get('id')}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def records_delete(
    table_id: str = typer.Argument(..., help="The table ID or name"),
    record_id: str = typer.Argument(..., help="The record ID"),
    base_id: Optional[str] = typer.Option(None, "--base", "-b", help="The base ID (defaults to AIRTABLE_BASE_ID)"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """
    Delete a record.

    Examples:
        airtable records delete "Tasks" recXXX
        airtable records delete "Tasks" recXXX --yes
    """
    try:
        resolved_base_id = resolve_base_id(base_id)

        if not confirm:
            confirmed = typer.confirm(f"Are you sure you want to delete record {record_id}?")
            if not confirmed:
                print_info("Deletion cancelled")
                raise typer.Exit(0)

        client = get_client()
        result = client.delete_record(resolved_base_id, table_id, record_id)
        print_success(f"Record {record_id} deleted successfully")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
