"""Search commands for Globiflow CLI."""
COMMAND_CREDENTIALS = {
    "item": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "query": [
        "browser_session"
    ]
}

import typer
from typing import Optional, List

from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table, handle_error, print_info
from cli_tools_shared import FilterMap

app = typer.Typer(help="Search Globiflow")


def extract_field(item: dict, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    parts = field.split(".")
    value = item
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
def query_items(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include in output"),
):
    """
    Search for items on Globiflow.

    Example:
        globiflow search query "my search term" --limit 20 --table
        globiflow search query "keyword" --filter "price:lt:100"
        globiflow search query "keyword" --properties "title,price"
    """
    try:
        client = get_client()
        # Returns only the array of results (no metadata)
        results = client.search(query, limit=limit, filters=filter)

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
                    columns = ["title", "price", "url"]
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
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Comma-separated fields to display (supports dot-notation)"),
):
    """
    Get details for a specific item.

    Example:
        globiflow search item abc123 --table
        globiflow search item "https://example.com/item/abc123"
        globiflow search item abc123 --output "title,price"
    """
    try:
        client = get_client()
        # Returns only the item object (no metadata)
        item = client.get_item(item_id)

        # Apply output field selection with dot-notation support
        if output:
            fields = [f.strip() for f in output.split(",")]
            item = extract_fields([item], fields)[0]

        if table:
            if output:
                columns = [f.strip() for f in output.split(",")]
                print_table([item], columns, columns)
            else:
                # Convert dict to rows for table display
                rows = [{"field": k, "value": str(v)} for k, v in item.items()]
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
def list_items(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include in output"),
):
    """
    List items from Globiflow.

    Example:
        globiflow search list --limit 100 --table
        globiflow search list --filter "status:active"
        globiflow search list --properties "id,name,status"
    """
    try:
        client = get_client()
        # Returns only the array of items (no metadata)
        items = client.list_items(limit=limit, filters=filter)

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            items = extract_fields(items, fields)

        if table:
            if items:
                if properties:
                    columns = [f.strip() for f in properties.split(",")]
                else:
                    # Use first item's keys as columns
                    columns = list(items[0].keys())
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
