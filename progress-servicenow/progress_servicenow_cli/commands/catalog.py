"""Catalog commands for Progress ServiceNow CLI."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import (
    print_json, print_table, handle_error, print_info,
)
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Browse the ServiceNow catalog", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "search": [
        "browser_session"
    ]
}


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items."""
    result = []
    for item in items:
        data = model_to_dict(item)
        extracted = {}
        for field in fields:
            parts = field.split(".")
            value = data
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def catalog_list(
    category: Optional[str] = typer.Option(
        None,
        "--category", "-C",
        help="Category: it, business-operations, workplace-operations, or a topic_id",
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    List catalog items, optionally filtered by category.

    Examples:
        progress-servicenow catalog list
        progress-servicenow catalog list --category it --table
        progress-servicenow catalog list --category business-operations --limit 20
        progress-servicenow catalog list --filter "type:eq:Request"
        progress-servicenow catalog list --properties "name,type,sys_id"
    """
    try:
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                from cli_tools_shared.output import print_error
                print_error(str(e))
                raise typer.Exit(1)

        client = get_client()
        results = client.list_catalog(category=category, limit=limit)

        # Apply client-side filters
        if filter and isinstance(results, list):
            results_dict = [model_to_dict(item) for item in results]
            results_dict = apply_filters(results_dict, filter)
            results = results_dict

        # Apply properties selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            results = extract_fields(results, fields)

        if table:
            if results:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    columns = ["name", "type", "description"]
                headers = [c.replace("_", " ").title() for c in columns]
                print_table(results, columns, headers)
            else:
                print_info("No catalog items found.")
        else:
            print_json(results)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def catalog_get(
    sys_id: str = typer.Argument(..., help="Catalog item sys_id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    Get details for a specific catalog item by sys_id.

    Examples:
        progress-servicenow catalog get abc123def456789012345678abcdef01
        progress-servicenow catalog get abc123... --table
        progress-servicenow catalog get abc123... --properties "name,type,description"
    """
    try:
        client = get_client()
        item = client.get_catalog_item(sys_id)
        item_dict = model_to_dict(item)

        # Apply properties selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            item_dict = extract_fields([item_dict], fields)[0]

        if table:
            if properties:
                columns = [f.strip() for f in properties.split(",")]
                print_table([item_dict], columns, columns)
            else:
                rows = [
                    {"field": k, "value": str(v)}
                    for k, v in item_dict.items()
                    if v is not None
                ]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item_dict)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def catalog_search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
):
    """
    Search the ServiceNow catalog.

    Examples:
        progress-servicenow catalog search "application access"
        progress-servicenow catalog search "vpn" --table
        progress-servicenow catalog search "password" --limit 5
        progress-servicenow catalog search "hardware" --properties "name,type"
    """
    try:
        client = get_client()
        results = client.search_catalog(query, limit=limit)

        # Apply properties selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            results = extract_fields(results, fields)

        if table:
            if results:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    columns = ["name", "type", "description"]
                headers = [c.replace("_", " ").title() for c in columns]
                print_table(results, columns, headers)
            else:
                print_info("No results found.")
        else:
            print_json(results)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
