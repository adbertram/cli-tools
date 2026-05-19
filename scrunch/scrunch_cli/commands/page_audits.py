"""Page audit commands for Scrunch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from ..models import CreatePageAudit
from .helpers import model_to_dict, extract_fields
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter


app = typer.Typer(help="Manage page audits", no_args_is_help=True)


@app.command("list")
def page_audits_list(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by audit status"),
    url: Optional[str] = typer.Option(None, "--url", help="Filter by URL"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List page audits for a brand.

    Examples:
        scrunch page-audits list 123
        scrunch page-audits list 123 --table
        scrunch page-audits list 123 --status completed
        scrunch page-audits list 123 --url "https://example.com/page"
    """
    try:
        client = get_client()
        items = client.list_page_audits(brand_id, limit=limit, status=status, url=url)
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
                    ["id", "url", "status", "created_at"],
                    ["ID", "URL", "Status", "Created At"],
                )
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def page_audits_get(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    page_audit_id: int = typer.Argument(..., help="Page audit ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get details for a specific page audit.

    Examples:
        scrunch page-audits get 123 456
        scrunch page-audits get 123 456 --table
    """
    try:
        client = get_client()
        item = client.get_page_audit(brand_id, page_audit_id)
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
def page_audits_create(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    url: str = typer.Option(..., "--url", "-u", help="URL to audit"),
):
    """Create a new page audit for a brand.

    Examples:
        scrunch page-audits create 123 --url "https://example.com/page"
    """
    try:
        client = get_client()
        data = CreatePageAudit(url=url)
        result = client.create_page_audit(brand_id, data)
        print_json(model_to_dict(result))

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ]
}
