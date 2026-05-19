"""Competitor commands for Scrunch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from ..models import CreateCompetitor, UpdateCompetitor
from .helpers import model_to_dict, extract_fields
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter


app = typer.Typer(help="Manage brand competitors", no_args_is_help=True)


@app.command("list")
def competitors_list(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List competitors for a brand.

    Examples:
        scrunch competitors list 123
        scrunch competitors list 123 --table
        scrunch competitors list 123 --limit 10
        scrunch competitors list 123 --filter "name:contains:acme"
    """
    try:
        client = get_client()
        items = client.list_competitors(brand_id, limit=limit)
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
                    ["id", "name", "websites"],
                    ["ID", "Name", "Websites"],
                )
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def competitors_get(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    competitor_id: int = typer.Argument(..., help="Competitor ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get details for a specific competitor.

    Examples:
        scrunch competitors get 123 456
        scrunch competitors get 123 456 --table
    """
    try:
        client = get_client()
        item = client.get_competitor(brand_id, competitor_id)
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
def competitors_create(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    name: str = typer.Option(..., "--name", "-n", help="Competitor name"),
    alternative_names: Optional[str] = typer.Option(None, "--alt-names", help="Comma-separated alternative names"),
    websites: Optional[str] = typer.Option(None, "--websites", "-w", help="Comma-separated website URLs"),
):
    """Create a new competitor for a brand.

    Examples:
        scrunch competitors create 123 --name "Competitor Inc"
        scrunch competitors create 123 --name "Competitor Inc" --websites "https://competitor.com"
    """
    try:
        client = get_client()
        data = CreateCompetitor(
            name=name,
            alternative_names=[n.strip() for n in alternative_names.split(",")] if alternative_names else None,
            websites=[w.strip() for w in websites.split(",")] if websites else None,
        )
        result = client.create_competitor(brand_id, data)
        print_json(model_to_dict(result))

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def competitors_update(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    competitor_id: int = typer.Argument(..., help="Competitor ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Competitor name"),
    alternative_names: Optional[str] = typer.Option(None, "--alt-names", help="Comma-separated alternative names"),
    websites: Optional[str] = typer.Option(None, "--websites", "-w", help="Comma-separated website URLs"),
):
    """Update a competitor.

    Examples:
        scrunch competitors update 123 456 --name "New Name"
    """
    try:
        client = get_client()
        data = UpdateCompetitor(
            name=name,
            alternative_names=[n.strip() for n in alternative_names.split(",")] if alternative_names else None,
            websites=[w.strip() for w in websites.split(",")] if websites else None,
        )
        result = client.update_competitor(brand_id, competitor_id, data)
        print_json(model_to_dict(result))

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def competitors_delete(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    competitor_id: int = typer.Argument(..., help="Competitor ID"),
):
    """Archive (delete) a competitor.

    Examples:
        scrunch competitors delete 123 456
    """
    try:
        client = get_client()
        client.delete_competitor(brand_id, competitor_id)
        print_json({"status": "deleted", "brand_id": brand_id, "competitor_id": competitor_id})

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
