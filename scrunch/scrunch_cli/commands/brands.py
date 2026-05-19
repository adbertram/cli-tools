"""Brand commands for Scrunch CLI."""
import json
import typer
from typing import Optional, List

from ..client import get_client
from ..models import CreateBrand, UpdateBrand
from .helpers import model_to_dict, extract_fields
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter


app = typer.Typer(help="Manage brands", no_args_is_help=True)


@app.command("list")
def brands_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List all brands.

    Examples:
        scrunch brands list
        scrunch brands list --table
        scrunch brands list --limit 10
        scrunch brands list --filter "status:eq:active"
        scrunch brands list --properties "id,name,website"
    """
    try:
        client = get_client()
        items = client.list_brands(limit=limit)
        items = [model_to_dict(i) for i in items]

        if filter:
            items = apply_filters(items, filter)
        if properties:
            items = apply_properties_filter(items, properties)

        if table:
            if properties:
                cols = [f.strip() for f in properties.split(",")]
                print_table(items, cols, cols)
            else:
                print_table(
                    items,
                    ["id", "name", "website", "status"],
                    ["ID", "Name", "Website", "Status"],
                )
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def brands_get(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get details for a specific brand.

    Examples:
        scrunch brands get 123
        scrunch brands get 123 --table
        scrunch brands get 123 --properties "id,name,website"
    """
    try:
        client = get_client()
        item = client.get_brand(brand_id)
        item = model_to_dict(item)

        if properties:
            item = apply_properties_filter([item], properties)[0]

        if table:
            if properties:
                cols = [f.strip() for f in properties.split(",")]
                print_table([item], cols, cols)
            else:
                rows = [{"field": k, "value": str(v)} for k, v in item.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def brands_create(
    name: str = typer.Option(..., "--name", "-n", help="Brand name"),
    website: str = typer.Option(..., "--website", "-w", help="Brand website URL"),
    description: str = typer.Option(..., "--description", "-d", help="Brand description"),
    alternative_names: Optional[str] = typer.Option(None, "--alt-names", help="Comma-separated alternative names"),
    alternative_websites: Optional[str] = typer.Option(None, "--alt-websites", help="Comma-separated alternative websites"),
    key_topics: Optional[str] = typer.Option(None, "--key-topics", help="Comma-separated key topics"),
    status: Optional[str] = typer.Option(None, "--status", help="Brand status"),
):
    """Create a new brand.

    Examples:
        scrunch brands create --name "My Brand" --website "https://example.com" --description "A brand"
        scrunch brands create --name "My Brand" --website "https://example.com" --description "A brand" --key-topics "ai,ml"
    """
    try:
        client = get_client()
        data = CreateBrand(
            name=name,
            website=website,
            description=description,
            alternative_names=[n.strip() for n in alternative_names.split(",")] if alternative_names else None,
            alternative_websites=[w.strip() for w in alternative_websites.split(",")] if alternative_websites else None,
            key_topics=[t.strip() for t in key_topics.split(",")] if key_topics else None,
            status=status,
        )
        result = client.create_brand(data)
        print_json(model_to_dict(result))

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def brands_update(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Brand name"),
    website: Optional[str] = typer.Option(None, "--website", "-w", help="Brand website URL"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Brand description"),
    status: Optional[str] = typer.Option(None, "--status", help="Brand status"),
):
    """Update an existing brand.

    Examples:
        scrunch brands update 123 --name "New Name"
        scrunch brands update 123 --status "active"
    """
    try:
        client = get_client()
        data = UpdateBrand(
            name=name,
            website=website,
            description=description,
            status=status,
        )
        result = client.update_brand(brand_id, data)
        print_json(model_to_dict(result))

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def brands_delete(
    brand_id: int = typer.Argument(..., help="Brand ID"),
):
    """Archive (delete) a brand.

    Examples:
        scrunch brands delete 123
    """
    try:
        client = get_client()
        client.delete_brand(brand_id)
        print_json({"status": "deleted", "brand_id": brand_id})

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "api_key"
    ],
    "delete": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "update": [
        "api_key"
    ]
}
