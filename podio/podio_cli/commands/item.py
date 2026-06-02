"""Item commands for Podio CLI."""

COMMAND_CREDENTIALS = {
    "create": [
        "oauth_authorization_code"
    ],
    "delete": [
        "oauth_authorization_code"
    ],
    "field-value": [
        "oauth_authorization_code"
    ],
    "get": [
        "oauth_authorization_code"
    ],
    "get-by-external-id": [
        "oauth_authorization_code"
    ],
    "list": [
        "oauth_authorization_code"
    ],
    "update": [
        "oauth_authorization_code"
    ],
    "values": [
        "oauth_authorization_code"
    ]
}
import json
import sys
from typing import Optional, List, Any, Dict
from pathlib import Path
import typer

from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from ..client import get_client
from ..output import print_json, print_output, print_error, print_success, print_warning, handle_api_error, format_response
from ..filter_map import FilterMap, apply_properties

app = typer.Typer(help="Manage Podio items")


@app.command("get")
def get_item(
    item_id: Optional[int] = typer.Argument(None, help="Item ID to retrieve"),
    external_id: Optional[str] = typer.Option(None, "--external-id", "-e", help="External ID to look up (requires --app-id)"),
    app_id: Optional[int] = typer.Option(None, "--app-id", "-a", help="App ID (required with --external-id)"),
    basic: bool = typer.Option(False, "--basic", help="Get basic item info only"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a Podio item by ID or external ID.

    Examples:
        podio item get 12345
        podio item get 12345 --basic
        podio item get --external-id my-custom-id --app-id 30543397
        podio item get 12345 --table
    """
    try:
        client = get_client()

        if external_id:
            # Look up by external ID
            if not app_id:
                print_error("--app-id is required when using --external-id")
                raise typer.Exit(1)
            result = client.Item.find_by_external_id(app_id=app_id, external_id=external_id)
        elif item_id:
            # Look up by item ID
            result = client.Item.find(item_id=item_id, basic=basic)
        else:
            print_error("Either item_id argument or --external-id option is required")
            raise typer.Exit(1)

        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("list")
def list_items(
    app_id: int = typer.Argument(..., help="Application ID to list items from"),
    filter: Optional[str] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., 'status:eq:active', 'title:contains:report'). Ops: eq,ne,gt,gte,lt,lte,in,nin,like,ilike,null,notnull,contains,startswith,endswith. Also supports JSON filter for Podio API fields.",
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    offset: int = typer.Option(0, "--offset", help="Offset for pagination"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
    sort_by: Optional[str] = typer.Option(
        None,
        "--sort-by",
        help="Field to sort by",
    ),
    sort_desc: bool = typer.Option(False, "--desc", help="Sort in descending order"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List items in a Podio application with optional filtering.

    Examples:
        podio item list 12345
        podio item list 12345 --filter '{"status": "active"}'
        podio item list 12345 --limit 50 --offset 0
        podio item list 12345 --sort-by "created_on" --desc
        podio item list 12345 --properties "item_id,title,status"
        podio item list 12345 --table
    """
    try:
        client = get_client()

        # Build filter attributes
        attributes = {
            "limit": limit,
            "offset": offset,
        }

        # Parse JSON filters if provided
        if filter:
            try:
                filter_dict = json.loads(filter)
                attributes["filters"] = filter_dict
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON in --filter: {e}")
                raise typer.Exit(1)

        # Add sorting if specified
        if sort_by:
            attributes["sort_by"] = sort_by
            attributes["sort_desc"] = sort_desc

        result = client.Item.filter(app_id=app_id, attributes=attributes)
        formatted = format_response(result)

        # Apply properties filter if specified
        if properties:
            formatted = apply_properties(formatted, properties)

        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
def create_item(
    app_id: int = typer.Argument(..., help="Application ID to create item in"),
    json_file: Optional[Path] = typer.Option(
        None,
        "--json-file",
        help="Path to JSON file with item data",
    ),
    silent: bool = typer.Option(True, "--silent/--notify", help="Suppress Podio notifications (default: silent)"),
    no_hook: bool = typer.Option(False, "--no-hook", help="Skip webhook execution"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Create a new item in a Podio application.

    Reads item data from a JSON file or stdin.
    Podio notifications are suppressed by default.

    Item data format:
        {
            "fields": [
                {"external_id": "title", "values": [{"value": "Item Title"}]},
                {"external_id": "status", "values": [{"value": "active"}]}
            ]
        }

    Examples:
        podio item create 12345 --json-file item.json
        cat item.json | podio item create 12345
        podio item create 12345 --json-file item.json --table
    """
    try:
        client = get_client()

        # Read item data from file or stdin
        if json_file:
            if not json_file.exists():
                print_error(f"File not found: {json_file}")
                raise typer.Exit(1)
            with open(json_file) as f:
                item_data = json.load(f)
        else:
            # Read from stdin
            try:
                item_data = json.load(sys.stdin)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON from stdin: {e}")
                raise typer.Exit(1)

        # Validate that we have fields
        if "fields" not in item_data:
            print_error("Item data must contain 'fields' key")
            raise typer.Exit(1)

        result = client.Item.create(
            app_id=app_id,
            attributes=item_data,
            silent=silent,
            hook=not no_hook
        )
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
def update_item(
    item_id: int = typer.Argument(..., help="Item ID to update"),
    json_file: Optional[Path] = typer.Option(
        None,
        "--json-file",
        help="Path to JSON file with update data",
    ),
    silent: bool = typer.Option(False, "--silent", help="Suppress Podio notifications"),
    no_hook: bool = typer.Option(False, "--no-hook", help="Skip webhook execution"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Update an existing Podio item.

    Reads update data from a JSON file or stdin.

    Update data format (same as create):
        {
            "fields": [
                {"external_id": "status", "values": [{"value": "completed"}]}
            ]
        }

    Examples:
        podio item update 12345 --json-file update.json
        cat update.json | podio item update 12345
        podio item update 12345 --json-file update.json --table
    """
    try:
        client = get_client()

        # Read update data from file or stdin
        if json_file:
            if not json_file.exists():
                print_error(f"File not found: {json_file}")
                raise typer.Exit(1)
            with open(json_file) as f:
                update_data = json.load(f)
        else:
            # Read from stdin
            try:
                update_data = json.load(sys.stdin)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON from stdin: {e}")
                raise typer.Exit(1)

        result = client.Item.update(
            item_id=item_id,
            attributes=update_data,
            silent=silent,
            hook=not no_hook
        )
        formatted = format_response(result)
        print_success(f"Item {item_id} updated successfully")
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("delete")
def delete_item(
    item_id: int = typer.Argument(..., help="Item ID to delete"),
    silent: bool = typer.Option(False, "--silent", help="Suppress Podio notifications"),
    no_hook: bool = typer.Option(False, "--no-hook", help="Skip webhook execution"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Delete a Podio item.

    Examples:
        podio item delete 12345
        podio item delete 12345 --silent
        podio item delete 12345 --table
    """
    try:
        client = get_client()
        client.Item.delete(item_id=item_id, silent=silent, hook=not no_hook)
        print_success(f"Item {item_id} deleted successfully")
        print_output({"item_id": item_id, "deleted": True}, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("values")
def get_item_values(
    item_id: int = typer.Argument(..., help="Item ID to get values from"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get field values for a specific item.

    Returns all field values in a clean format using the v2 API endpoint.

    Examples:
        podio item values 12345
        podio item values 12345 --table
    """
    try:
        client = get_client()
        result = client.Item.values_v2(item_id=item_id)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("field-value")
def get_field_value(
    item_id: int = typer.Argument(..., help="Item ID to get field value from"),
    field: str = typer.Argument(..., help="Field ID or external_id to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a specific field's values for an item (v2 endpoint).

    The field can be specified either as:
    - field_id (e.g., 274720804)
    - external_id (e.g., "potential-writer")

    Examples:
        podio item field-value 12345 274720804
        podio item field-value 12345 potential-writer
        podio item field-value 12345 potential-writer --table
    """
    try:
        client = get_client()
        result = client.Item.field_value_v2(item_id=item_id, field_or_external_id=field)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("get-by-external-id", hidden=True)
def get_item_by_external_id(
    app_id: int = typer.Argument(..., help="Application ID"),
    external_id: str = typer.Argument(..., help="External ID of the item"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    [DEPRECATED] Use 'podio item get --external-id <id> --app-id <app_id>' instead.

    Get a Podio item by external ID within a specific app.
    """
    print_warning("'podio item get-by-external-id' is deprecated. Use 'podio item get --external-id <id> --app-id <app_id>' instead.")
    try:
        client = get_client()
        result = client.Item.find_by_external_id(app_id=app_id, external_id=external_id)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)
