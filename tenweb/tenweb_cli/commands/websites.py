"""Website commands for the 10Web CLI."""

from typing import List, Optional

import typer
from pydantic import BaseModel

from cli_tools_shared.output import handle_error, print_json, print_table

from ..client import get_client


COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
}


app = typer.Typer(help="Manage 10Web websites", no_args_is_help=True)


def model_to_dict(item):
    """Convert a model or mapping into a plain dict."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation."""
    value = model_to_dict(item)
    for part in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def extract_fields(items: list, fields: list) -> list:
    """Project items to the requested field set."""
    rows = []
    for item in items:
        row = {}
        for field in fields:
            row[field] = extract_field(item, field)
        rows.append(row)
    return rows


@app.command("list")
def websites_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of websites to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List websites for the current 10Web account.

    Examples:
        tenweb websites list
        tenweb websites list --table
        tenweb websites list --filter "type:eq:live"
        tenweb websites list --properties "id,name,site_url,type"
    """
    try:
        websites = get_client().list_websites(limit=limit, filters=filter)

        if properties:
            fields = [field.strip() for field in properties.split(",")]
            websites = extract_fields(websites, fields)

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",")]
                print_table(websites, fields, fields)
            else:
                print_table(
                    websites,
                    ["id", "name", "site_url", "type"],
                    ["ID", "Name", "Site URL", "Type"],
                )
        else:
            print_json(websites)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def websites_get(
    website_id: int = typer.Argument(..., help="10Web website ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Get instance details for a single website.

    Examples:
        tenweb websites get 15354
        tenweb websites get 15354 --table
        tenweb websites get 15354 --properties "website_id,status,region"
    """
    try:
        website = get_client().get_website(website_id)

        if properties:
            fields = [field.strip() for field in properties.split(",")]
            website = extract_fields([website], fields)[0]

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",")]
                print_table([website], fields, fields)
            else:
                website_dict = model_to_dict(website)
                rows = [
                    {"field": key, "value": str(value)}
                    for key, value in website_dict.items()
                    if value is not None
                ]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(website)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
