"""Search commands for Manageengine CLI."""
COMMAND_CREDENTIALS = {
    "query": ["browser_session"],
    "item": ["browser_session"],
    "list": ["browser_session"],
    "wildcard": ["browser_session"],
}

import fnmatch
from typing import List, Optional

import typer
from pydantic import BaseModel

from .client import ClientError, get_client
from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters
from cli_tools_shared.output import handle_error, print_info, print_json, print_table

app = typer.Typer(help="Search Manageengine", no_args_is_help=True)


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
            extracted[field] = extract_field(item, field)
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
    """Search for items on Manageengine."""
    try:
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                from cli_tools_shared.output import print_error

                print_error(str(e))
                raise typer.Exit(1)

        client = get_client()
        results = client.search(query, limit=limit, filters=filter)

        if filter and isinstance(results, list):
            results = apply_filters([model_to_dict(item) for item in results], filter)

        if properties:
            results = extract_fields(results, [f.strip() for f in properties.split(",")])

        if table:
            if results:
                columns = [f.strip() for f in properties.split(",")] if properties else ["id", "name", "status"]
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
    """Get details for a specific item."""
    try:
        client = get_client()
        item = client.get_item(item_id)

        if properties:
            item = extract_fields([item], [f.strip() for f in properties.split(",")])[0]

        if table:
            if properties:
                columns = [f.strip() for f in properties.split(",")]
                print_table([item], columns, columns)
            else:
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
    """List items from Manageengine."""
    try:
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                from cli_tools_shared.output import print_error

                print_error(str(e))
                raise typer.Exit(1)

        client = get_client()
        items = client.list_items(limit=limit, filters=filter)

        if filter and isinstance(items, list):
            items = apply_filters([model_to_dict(item) for item in items], filter)

        if properties:
            items = extract_fields(items, [f.strip() for f in properties.split(",")])

        if table:
            if items:
                columns = [f.strip() for f in properties.split(",")] if properties else ["id", "name", "status"]
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
    """Search items with wildcard pattern matching."""
    try:
        client = get_client()
        items = client.list_items(limit=limit)
        search_fields = [f.strip() for f in fields.split(",")] if fields else None

        pattern = query.lower()
        if "*" not in pattern:
            pattern = f"*{pattern}*"

        results = []
        for item in items:
            item_dict = model_to_dict(item)
            item_fields = search_fields or [k for k, v in item_dict.items() if isinstance(v, str)]
            for field in item_fields:
                if fnmatch.fnmatch(str(item_dict.get(field, "")).lower(), pattern):
                    results.append(item)
                    break

        if properties:
            results = extract_fields(results, [f.strip() for f in properties.split(",")])

        if table:
            if results:
                columns = [f.strip() for f in properties.split(",")] if properties else ["id", "name", "status"]
                headers = [col.replace("_", " ").title() for col in columns]
                print_table(results, columns, headers)
            else:
                print_info("No items found matching the search query.")
        else:
            print_json(results)

        client.close()
    except Exception as e:
        raise typer.Exit(handle_error(e))
