"""Categories commands for Kick CLI."""
import typer
from typing import Optional, List

from cli_tools_shared.filters import apply_filters
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage Kick categories")


@app.command("list")
def categories_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of categories to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of properties to display"),
    parents_only: bool = typer.Option(False, "--parents-only", help="Only show parent categories (no subcategories)"),
):
    """
    List all categories.

    Examples:
        kick categories list
        kick categories list --table
        kick categories list --parents-only
        kick categories list --filter "label:like:%Income%"
        kick categories list --filter "isBusiness:true"
    """
    try:
        client = get_client()
        categories = client.list_categories(include_subcategories=not parents_only)

        # Apply client-side filtering (API doesn't support filtering)
        if filter:
            categories = apply_filters(categories, filter)

        # Apply limit
        categories = categories[:limit]

        if table:
            table_data = []
            for cat in categories:
                parent_id = cat.get("parentCategoryId", "")
                table_data.append({
                    "id": cat.get("id", ""),
                    "label": ("  " if cat.get("isSubcategory") else "") + cat.get("label", ""),
                    "taxonomy": cat.get("taxonomy", ""),
                    "isBusiness": "Yes" if cat.get("isBusiness") else "No",
                    "parentId": parent_id[:8] + "..." if parent_id else "",
                })

            print_table(
                table_data,
                ["id", "label", "taxonomy", "isBusiness", "parentId"],
                ["ID", "Label", "Taxonomy", "Business", "Parent"],
            )
            from cli_tools_shared.output import print_info
            print_info(f"Showing {len(categories)} categories")
        else:
            print_json(categories)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def categories_get(
    category_id: str = typer.Argument(..., help="The category UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific category.

    Examples:
        kick categories get 01956661-459c-74c3-94d8-b52a43fbae24
        kick categories get 01956661-459c-74c3-94d8-b52a43fbae24 --table
    """
    try:
        client = get_client()
        category = client.get_category(category_id)

        if table:
            summary = [{
                "id": category.get("id", ""),
                "label": category.get("label", ""),
                "taxonomy": category.get("taxonomy", ""),
                "description": (category.get("description") or "")[:50],
                "isBusiness": "Yes" if category.get("isBusiness") else "No",
                "parentCategoryId": category.get("parentCategoryId") or "",
            }]

            print_table(
                summary,
                ["id", "label", "taxonomy", "description", "isBusiness", "parentCategoryId"],
                ["ID", "Label", "Taxonomy", "Description", "Business", "Parent ID"],
            )
        else:
            print_json(category)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
