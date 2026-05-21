"""Recipe commands for MyFitnessPal CLI."""
import json
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.exceptions import ClientError

COMMAND_CREDENTIALS = {
    "create": [
        "browser_session"
    ],
    "delete": [
        "browser_session"
    ],
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ]
}

app = typer.Typer(help="Manage saved recipes", no_args_is_help=True)


@app.command("list")
def recipes_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all saved recipes.

    Examples:
        fitnesspal recipes list
        fitnesspal recipes list --table
        fitnesspal recipes list --limit 10
        fitnesspal recipes list --filter "name:contains:chicken"
    """
    try:
        client = get_client()
        recipes = client.list_recipes(limit=limit)

        items = [r.to_dict() for r in recipes]

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


@app.command("create")
def recipes_create(
    name: str = typer.Option(..., "--name", "-n", help="Recipe name"),
    servings: float = typer.Option(..., "--servings", "-s", help="Number of servings"),
    ingredients: str = typer.Option(
        ...,
        "--ingredients",
        "-i",
        help='JSON array of ingredients: [{"food_id":"123","quantity":2,"serving_unit":"oz","serving_value":4,"nutrition_multiplier":1.0}]',
    ),
):
    """
    Create a new recipe.

    Each ingredient requires a food_id (from 'fitnesspal food search'),
    quantity (number of servings), and serving size details.

    Examples:
        fitnesspal recipes create --name "Grilled Chicken Bowl" --servings 2 \\
          --ingredients '[{"food_id":"164248067900917","quantity":8,"serving_unit":"oz","serving_value":4,"nutrition_multiplier":1.0}]'
    """
    try:
        ingredient_list = json.loads(ingredients)
        if not isinstance(ingredient_list, list) or not ingredient_list:
            raise ClientError("Ingredients must be a non-empty JSON array")

        required_keys = {"food_id", "quantity", "serving_unit", "serving_value", "nutrition_multiplier"}
        for i, ing in enumerate(ingredient_list):
            missing = required_keys - set(ing.keys())
            if missing:
                raise ClientError(f"Ingredient {i} missing keys: {', '.join(missing)}")

        client = get_client()
        result = client.create_recipe(
            name=name,
            servings=servings,
            ingredients=ingredient_list,
        )

        print_json(result)

    except json.JSONDecodeError as e:
        raise typer.Exit(handle_error(ClientError(f"Invalid JSON for ingredients: {e}")))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def recipes_delete(
    recipe_id: str = typer.Argument(..., help="Recipe ID to delete"),
):
    """
    Delete a recipe.

    Examples:
        fitnesspal recipes delete 277632783478317
    """
    try:
        client = get_client()
        client.delete_recipe(recipe_id)
        print_json({"status": "deleted", "id": recipe_id})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def recipes_get(
    recipe_id: int = typer.Argument(..., help="Recipe ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get detailed recipe information.

    Examples:
        fitnesspal recipes get 12345
        fitnesspal recipes get 12345 --table
    """
    try:
        client = get_client()
        recipe = client.get_recipe(recipe_id)

        if table:
            item_dict = recipe.to_dict()
            rows = [
                {"field": k, "value": str(v)}
                for k, v in item_dict.items()
                if v is not None
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(recipe)

    except Exception as e:
        raise typer.Exit(handle_error(e))
