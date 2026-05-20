"""Search commands for Devolutions CLI."""

import fnmatch
from typing import List, Optional

import typer
from pydantic import BaseModel

from .client import ClientError, get_client
from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters
from cli_tools_shared.output import handle_error, print_info, print_json, print_table

COMMAND_CREDENTIALS = {
    "query": ["browser_session"],
    "item": ["browser_session"],
    "list": ["browser_session"],
    "wildcard": ["browser_session"],
}

app = typer.Typer(help="Search Devolutions", no_args_is_help=True)


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
    """Search for items on Devolutions."""
    try:
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as exc:
                from cli_tools_shared.output import print_error

                print_error(str(exc))
                raise typer.Exit(1)

        client = get_client()
        results = client.search(query, limit=limit, filters=filter)

        if filter and isinstance(results, list):
            results = apply_filters([model_to_dict(item) for item in results], filter)

        if properties:
            results = extract_fields(results, [field.strip() for field in properties.split(",")])

        if table:
            if results:
                columns = [field.strip() for field in properties.split(",")] if properties else ["id", "name", "status"]
                print_table(results, columns, columns)
            else:
                print_info("No results found.")
        else:
            print_json(results)

        client.close()
    except NotImplementedError:
        print_info("Search not implemented. Update client.py with your site's search logic.")
        raise typer.Exit(1)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


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
            item = extract_fields([item], [field.strip() for field in properties.split(",")])[0]

        if table:
            if properties:
                columns = [field.strip() for field in properties.split(",")]
                print_table([item], columns, columns)
            else:
                rows = [{"field": key, "value": str(value)} for key, value in model_to_dict(item).items() if value is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

        client.close()
    except NotImplementedError:
        print_info("Get item not implemented. Update client.py with your site's item retrieval logic.")
        raise typer.Exit(1)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("list")
def search_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """List items from Devolutions."""
    try:
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as exc:
                from cli_tools_shared.output import print_error

                print_error(str(exc))
                raise typer.Exit(1)

        client = get_client()
        items = client.list_items(limit=limit, filters=filter)

        if filter and isinstance(items, list):
            items = apply_filters([model_to_dict(item) for item in items], filter)

        if properties:
            items = extract_fields(items, [field.strip() for field in properties.split(",")])

        if table:
            if items:
                columns = [field.strip() for field in properties.split(",")] if properties else ["id", "name", "status"]
                headers = [column.replace("_", " ").title() for column in columns]
                print_table(items, columns, headers)
            else:
                print_info("No items found.")
        else:
            print_json(items)

        client.close()
    except NotImplementedError:
        print_info("List items not implemented. Update client.py with your site's listing logic.")
        raise typer.Exit(1)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


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
        search_fields = [field.strip() for field in fields.split(",")] if fields else None

        pattern = query.lower()
        if "*" not in pattern:
            pattern = f"*{pattern}*"

        def matches(item) -> bool:
            data = model_to_dict(item)
            field_names = search_fields or data.keys()
            for field_name in field_names:
                value = extract_field(data, field_name) if "." in field_name else data.get(field_name)
                if isinstance(value, str) and fnmatch.fnmatch(value.lower(), pattern):
                    return True
            return False

        results = [item for item in items if matches(item)]

        if properties:
            results = extract_fields(results, [field.strip() for field in properties.split(",")])

        if table:
            if results:
                columns = [field.strip() for field in properties.split(",")] if properties else ["id", "name", "status"]
                print_table(results, columns, columns)
            else:
                print_info("No matches found.")
        else:
            print_json(results)

        client.close()
    except NotImplementedError:
        print_info("Wildcard search not implemented. Update client.py with your site's listing logic.")
        raise typer.Exit(1)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
