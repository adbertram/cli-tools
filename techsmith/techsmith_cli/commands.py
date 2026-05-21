"""Search commands for Techsmith CLI."""
COMMAND_CREDENTIALS = {
    "query": ["browser_session"],
    "item": ["browser_session"],
    "list": ["browser_session"],
    "wildcard": ["browser_session"],
}

import fnmatch
import typer
from typing import Optional, List

from pydantic import BaseModel

from .client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error, print_info
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Search Techsmith", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("query")
def search_query(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    Search for items on Techsmith.

    Example:
        techsmith search query "my search term" --limit 20 --table
        techsmith search query "keyword" --filter "price:lt:100"
        techsmith search query "keyword" --properties "title,price"
    """
    try:
        # Validate filters if provided
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                from cli_tools_shared.output import print_error
                print_error(str(e))
                raise typer.Exit(1)

        client = get_client()
        # Returns List[Item] models
        results = client.search(query, limit=limit, filters=filter)

        # Apply client-side filters (browser CLIs typically filter client-side)
        if filter and isinstance(results, list):
            results_dict = [model_to_dict(item) for item in results]
            results_dict = apply_filters(results_dict, filter)
            results = results_dict

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            results = extract_fields(results, fields)

        if table:
            if results:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    # TODO: Update columns based on your search result fields
                    columns = ["id", "name", "status"]
                print_table(results, columns, columns)
            else:
                print_info("No results found.")
        else:
            print_json(results)

        client.close()
    except NotImplementedError:
        print_info("Search not implemented. Update client.py with your site's search logic.")
        raise typer.Exit(1)
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("item")
def search_item(
    item_id: str = typer.Argument(..., help="Item ID or URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    Get details for a specific item.

    Example:
        techsmith search item abc123 --table
        techsmith search item "https://example.com/item/abc123"
        techsmith search item abc123 --properties "title,price"
    """
    try:
        client = get_client()
        # Returns ItemDetail model
        item = client.get_item(item_id)

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            item = extract_fields([item], fields)[0]

        if table:
            if properties:
                columns = [f.strip() for f in properties.split(",")]
                print_table([item], columns, columns)
            else:
                # Convert model to key-value table
                item_dict = model_to_dict(item)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

        client.close()
    except NotImplementedError:
        print_info("Get item not implemented. Update client.py with your site's item retrieval logic.")
        raise typer.Exit(1)
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def search_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    List items from Techsmith.

    Example:
        techsmith search list --limit 100 --table
        techsmith search list --filter "status:active"
        techsmith search list --properties "id,name,status"
    """
    try:
        # Validate filters if provided
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                from cli_tools_shared.output import print_error
                print_error(str(e))
                raise typer.Exit(1)

        client = get_client()
        # Returns List[Item] models
        items = client.list_items(limit=limit, filters=filter)

        # Apply client-side filters (browser CLIs typically filter client-side)
        if filter and isinstance(items, list):
            items_dict = [model_to_dict(item) for item in items]
            items_dict = apply_filters(items_dict, filter)
            items = items_dict

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            items = extract_fields(items, fields)

        if table:
            if items:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    # Default columns for models
                    columns = ["id", "name", "status"]
                headers = [col.replace("_", " ").title() for col in columns]
                print_table(items, columns, headers)
            else:
                print_info("No items found.")
        else:
            print_json(items)

        client.close()
    except NotImplementedError:
        print_info("List items not implemented. Update client.py with your site's listing logic.")
        raise typer.Exit(1)
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("wildcard")
def search_wildcard(
    query: str = typer.Argument(..., help="Search query (supports * wildcards)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    fields: Optional[str] = typer.Option(None, "--fields", help="Comma-separated fields to search"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    Search items with wildcard pattern matching.

    Supports * wildcards for pattern matching across all string fields.
    Browser CLIs use client-side search.

    Examples:
        techsmith search wildcard "*test*"
        techsmith search wildcard "prefix*"
        techsmith search wildcard "*pending*" --fields "status,notes"
        techsmith search wildcard "*error*" --properties "id,name,status" --table
    """
    try:
        client = get_client()

        # Get all items first - returns List[Item] models
        items = client.list_items(limit=limit)

        # Get search fields if specified
        search_fields = [f.strip() for f in fields.split(",")] if fields else None

        # Apply client-side wildcard matching
        pattern = query.lower()
        if '*' not in pattern:
            pattern = f'*{pattern}*'  # Default to contains match

        results = []
        for item in items:
            # Convert model to dict for field access
            item_dict = model_to_dict(item)

            # Get fields to search
            item_fields = search_fields or [k for k, v in item_dict.items() if isinstance(v, str)]

            # Check if any field matches
            for field in item_fields:
                value = str(item_dict.get(field, '')).lower()
                if fnmatch.fnmatch(value, pattern):
                    results.append(item)
                    break

        # Apply properties field selection with dot-notation support
        if properties:
            prop_fields = [f.strip() for f in properties.split(",")]
            results = extract_fields(results, prop_fields)

        if table:
            if results:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    columns = ["id", "name", "status"]
                headers = [c.replace("_", " ").title() for c in columns]
                print_table(results, columns, headers)
            else:
                print_info("No items found matching the search query.")
        else:
            print_json(results)

        client.close()
    except Exception as e:
        raise typer.Exit(handle_error(e))
