"""Food commands for MyFitnessPal CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.exceptions import ClientError

COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ]
}

app = typer.Typer(help="Search and view food items", no_args_is_help=True)


@app.command("list")
def food_list(
    query: str = typer.Argument(..., help="Search query for food items"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Search the MyFitnessPal food database.

    Examples:
        fitnesspal food list "chicken breast"
        fitnesspal food list banana --table
        fitnesspal food list "greek yogurt" --limit 5
        fitnesspal food list "protein bar" --filter "verified:true"
        fitnesspal food list rice --properties "mfp_id,name,calories"
    """
    try:
        client = get_client()
        results = client.search_food(query=query, limit=limit)

        items = [r.to_dict() for r in results]

        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")
            items = apply_filters(items, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            items = [{k: item[k] for k in fields if k in item} for item in items]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(items, fields, fields)
            else:
                print_table(
                    items,
                    ["mfp_id", "name", "brand", "calories", "verified"],
                    ["ID", "Name", "Brand", "Calories", "Verified"],
                )
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def food_get(
    mfp_id: int = typer.Argument(..., help="MyFitnessPal food item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get detailed information about a specific food item.

    Examples:
        fitnesspal food get 12345
        fitnesspal food get 12345 --table
    """
    try:
        client = get_client()
        food = client.get_food(mfp_id)

        if table:
            item_dict = food.to_dict()
            rows = [
                {"field": k, "value": str(v)}
                for k, v in item_dict.items()
                if v is not None
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(food)

    except Exception as e:
        raise typer.Exit(handle_error(e))
