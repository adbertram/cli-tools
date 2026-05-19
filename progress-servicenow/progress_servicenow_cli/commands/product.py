"""Product commands for Progress ServiceNow CLI."""
import typer
from typing import List, Optional

from ..client import get_client
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters
from cli_tools_shared.output import (
    print_json, print_table, handle_error, print_info, print_error,
)

app = typer.Typer(help="Product field options for catalog items", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
}


@app.command("list")
def product_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List available Product dropdown options from the Development Cloud Issue form.

    Scrapes the Product Select2 dropdown via browser automation.

    Examples:
        progress-servicenow ticket product list
        progress-servicenow ticket product list --table
    """
    try:
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        client = get_client()
        products = client.list_products()
        rows = [{"product": product} for product in products]

        if filter:
            rows = apply_filters(rows, filter)

        rows = rows[:limit]

        if properties:
            fields = [field.strip() for field in properties.split(",")]
            rows = [{field: row.get(field) for field in fields} for row in rows]

        if table:
            if rows:
                columns = [field.strip() for field in properties.split(",")] if properties else ["product"]
                print_table(rows, columns, [column.title() for column in columns])
            else:
                print_info("No products found.")
        else:
            print_json(rows)

        client.close()
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def product_get(
    product: str = typer.Argument(..., help="Exact product name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one Product dropdown option by exact name."""
    try:
        client = get_client()
        matches = [name for name in client.list_products() if name == product]
        client.close()

        if not matches:
            raise ClientError(f"Product not found: {product}")

        row = {"product": matches[0]}
        if properties:
            fields = [field.strip() for field in properties.split(",")]
            row = {field: row.get(field) for field in fields}

        if table:
            columns = [field.strip() for field in properties.split(",")] if properties else ["product"]
            print_table([row], columns, [column.title() for column in columns])
        else:
            print_json(row)
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
