"""Store commands for eBay CLI.

Uses the eBay Stores API to manage store settings and categories.
API Docs: https://developer.ebay.com/api-docs/sell/stores/resources/store/methods/getStoreCategories
"""
COMMAND_CREDENTIALS = {
    "list": ["oauth_authorization_code"],
    "categories": ["oauth_authorization_code"],
}

from typing import Optional, List

import typer

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..properties import validate_and_filter_properties, PropertyValidationError

app = typer.Typer(help="Manage eBay store")
categories_app = typer.Typer(help="Manage eBay store categories")
app.add_typer(categories_app, name="categories", help="Manage eBay store categories")


def _flatten_categories(categories: list, parent_path: str = "") -> list:
    """Flatten nested store category hierarchy into a flat list.

    Each category includes its full path for use with storeCategoryNames.

    Args:
        categories: List of store category dicts from the API
        parent_path: Parent category path prefix

    Returns:
        Flat list of category dicts with id, name, level, order, path
    """
    result = []
    for cat in categories:
        name = cat.get("categoryName", "")
        cat_id = cat.get("categoryId", "")
        level = cat.get("level", 0)
        order = cat.get("order", 0)

        path = f"{parent_path}/{name}" if parent_path else name

        result.append({
            "categoryId": cat_id,
            "categoryName": name,
            "level": level,
            "order": order,
            "path": path,
        })

        children = cat.get("childrenCategories", [])
        if children:
            result.extend(_flatten_categories(children, parent_path=path))

    return result


@categories_app.command("list")
def categories_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    flat: bool = typer.Option(False, "--flat", help="Flatten category hierarchy into a flat list"),
    filters: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output"
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Maximum number of categories to return (client-side truncation)"
    ),
):
    """
    List all store categories for the seller's eBay store.

    Returns the store category hierarchy (up to 3 levels deep).
    Use --flat to flatten the hierarchy into a single list.

    Examples:
        ebay store categories list
        ebay store categories list --table
        ebay store categories list --flat --table
        ebay store categories list --filter "categoryName:ilike:%lego%"
    """
    try:
        client = get_client()
        result = client.get_store_categories()

        categories = result.get("storeCategories", [])

        if flat:
            categories = _flatten_categories(categories)

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                categories = apply_filters(categories, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply properties filter if specified
        if properties:
            try:
                categories = validate_and_filter_properties(categories, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply client-side limit (truncate flattened results)
        if limit is not None:
            if not flat:
                categories = _flatten_categories(categories)
            categories = categories[:limit]
            # Force flat display since we truncated a flattened list
            flat = True

        if table:
            if not categories:
                print("No store categories found.")
                return

            if flat:
                table_data = []
                for cat in categories:
                    indent = "  " * (cat.get("level", 1) - 1)
                    table_data.append({
                        "id": cat.get("categoryId", ""),
                        "name": f"{indent}{cat.get('categoryName', '')}",
                        "level": str(cat.get("level", "")),
                        "order": str(cat.get("order", "")),
                        "path": cat.get("path", ""),
                    })

                print_table(
                    table_data,
                    ["id", "name", "level", "order", "path"],
                    ["Category ID", "Name", "Level", "Order", "Path"],
                )
            else:
                # For hierarchical display, flatten for table but show indentation
                flat_cats = _flatten_categories(categories)
                table_data = []
                for cat in flat_cats:
                    indent = "  " * (cat.get("level", 1) - 1)
                    table_data.append({
                        "id": cat.get("categoryId", ""),
                        "name": f"{indent}{cat.get('categoryName', '')}",
                        "level": str(cat.get("level", "")),
                        "order": str(cat.get("order", "")),
                    })

                print_table(
                    table_data,
                    ["id", "name", "level", "order"],
                    ["Category ID", "Name", "Level", "Order"],
                )
        else:
            if flat:
                print_json({"storeCategories": categories, "total": len(categories)})
            else:
                print_json({"storeCategories": categories, "total": len(categories)})

    except Exception as e:
        raise typer.Exit(handle_error(e))


@categories_app.command("get")
def categories_get(
    category_id: str = typer.Argument(..., help="Store category ID to look up"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific store category by ID.

    Fetches all store categories and returns the one matching the given ID,
    including its full path in the category hierarchy.

    Examples:
        ebay store categories get 12345
        ebay store categories get 12345 --table
    """
    try:
        client = get_client()
        result = client.get_store_categories()

        categories = result.get("storeCategories", [])
        flat_cats = _flatten_categories(categories)

        # Find the category by ID
        match = None
        for cat in flat_cats:
            if str(cat.get("categoryId", "")) == str(category_id):
                match = cat
                break

        if not match:
            print_error(f"Store category '{category_id}' not found.")
            raise typer.Exit(1)

        if table:
            table_data = [{
                "id": match.get("categoryId", ""),
                "name": match.get("categoryName", ""),
                "level": str(match.get("level", "")),
                "order": str(match.get("order", "")),
                "path": match.get("path", ""),
            }]

            print_table(
                table_data,
                ["id", "name", "level", "order", "path"],
                ["Category ID", "Name", "Level", "Order", "Path"],
            )
        else:
            print_json(match)

    except Exception as e:
        raise typer.Exit(handle_error(e))
