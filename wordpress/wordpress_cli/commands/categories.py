"""Categories commands for WordPress CLI."""
import typer
from typing import Optional, List

from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info
from ..filter_map import wordpress_filter_map
from . import model_to_dict, extract_fields, apply_client_side_filters


app = typer.Typer(help="Manage WordPress categories")

COMMAND_CREDENTIALS = {
    "create": [
        "username_password"
    ],
    "delete": [
        "username_password"
    ],
    "get": [
        "username_password"
    ],
    "list": [
        "username_password"
    ],
    "update": [
        "username_password"
    ]
}


def get_client():
    from ..client import get_client as _get_client
    return _get_client()


@app.command("list")
def categories_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of categories to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """List WordPress categories."""
    try:
        client = get_client()

        filters = wordpress_filter_map.to_api_params(filter) if filter else {}
        categories = client.list_categories(limit=limit, filters=filters)

        # Apply client-side filtering for fields without API translators
        categories = apply_client_side_filters(categories, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            categories = extract_fields(categories, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(categories, fields, fields)
            else:
                print_table(
                    categories,
                    ["id", "name", "slug", "count"],
                    ["ID", "Name", "Slug", "Count"],
                )
        else:
            print_json(categories)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def categories_get(
    category_id: int = typer.Argument(..., help="The category ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """Get details for a specific WordPress category."""
    try:
        client = get_client()
        category = client.get_category(category_id)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            category = extract_fields([category], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([category], fields, fields)
            else:
                cat_dict = model_to_dict(category)
                rows = [{"field": k, "value": str(v)} for k, v in cat_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(category)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def categories_create(
    name: str = typer.Option(..., "--name", "-n", help="Category name"),
    slug: Optional[str] = typer.Option(None, "--slug", "-s", help="URL slug for the category"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Category description"),
    parent: int = typer.Option(0, "--parent", "-p", help="Parent category ID (0 for no parent)"),
):
    """Create a new WordPress category."""
    try:
        client = get_client()

        print_info(f"Creating category: {name}")
        category = client.create_category(
            name=name,
            slug=slug,
            description=description,
            parent=parent,
        )

        print_success(f"Category created successfully (ID: {category.id})")
        print_json(category)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def categories_update(
    category_id: int = typer.Argument(..., help="The category ID to update"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="New category name"),
    slug: Optional[str] = typer.Option(None, "--slug", "-s", help="New URL slug"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description"),
    parent: Optional[int] = typer.Option(None, "--parent", help="New parent category ID"),
):
    """Update an existing WordPress category."""
    try:
        client = get_client()

        fields = {}
        if name is not None:
            fields["name"] = name
        if slug is not None:
            fields["slug"] = slug
        if description is not None:
            fields["description"] = description
        if parent is not None:
            fields["parent"] = parent

        if not fields:
            raise ValueError("Must provide at least one field to update (--name, --slug, --description, or --parent)")

        print_info(f"Updating category {category_id}")
        category = client.update_category(category_id, fields)

        print_success(f"Category {category_id} updated successfully")
        print_json(category)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def categories_delete(
    category_id: int = typer.Argument(..., help="The category ID to delete"),
):
    """Delete a WordPress category."""
    try:
        client = get_client()

        print_info(f"Permanently deleting category {category_id}")

        result = client.delete_category(category_id)

        print_success(f"Category {category_id} permanently deleted")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
