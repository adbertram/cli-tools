"""Saved meal commands for MyFitnessPal CLI."""
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

app = typer.Typer(help="View saved meals", no_args_is_help=True)


@app.command("list")
def meals_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all saved meals.

    Examples:
        fitnesspal meals list
        fitnesspal meals list --table
        fitnesspal meals list --limit 10
        fitnesspal meals list --filter "name:contains:lunch"
    """
    try:
        client = get_client()
        meals = client.list_saved_meals(limit=limit)

        items = [m.to_dict() for m in meals]

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
                print_table(items, ["id", "name"], ["ID", "Name"])
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def meals_get(
    meal_id: int = typer.Argument(..., help="Saved meal ID"),
    meal_title: str = typer.Argument(..., help="Saved meal title"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get detailed saved meal information.

    The meal title is required by the MyFitnessPal API.
    Use 'fitnesspal meals list' to find meal IDs and titles.

    Examples:
        fitnesspal meals get 12345 "My Lunch"
        fitnesspal meals get 12345 "My Lunch" --table
    """
    try:
        client = get_client()
        meal = client.get_saved_meal(meal_id, meal_title)

        if table:
            item_dict = meal.to_dict()
            rows = [
                {"field": k, "value": str(v)}
                for k, v in item_dict.items()
                if v is not None
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(meal)

    except Exception as e:
        raise typer.Exit(handle_error(e))
