"""Response commands for Scrunch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from .helpers import model_to_dict, extract_fields
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter


app = typer.Typer(help="View AI responses", no_args_is_help=True)


@app.command("list")
def responses_list(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset"),
    platform: Optional[str] = typer.Option(None, "--platform", help="Filter by AI platform"),
    prompt_id: Optional[int] = typer.Option(None, "--prompt-id", help="Filter by prompt ID"),
    persona_id: Optional[int] = typer.Option(None, "--persona-id", help="Filter by persona ID"),
    stage: Optional[str] = typer.Option(None, "--stage", help="Filter by stage"),
    start_date: Optional[str] = typer.Option(None, "--start-date", help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end-date", help="End date (YYYY-MM-DD)"),
    has_shopping_data: Optional[bool] = typer.Option(None, "--has-shopping-data", help="Filter by shopping data presence"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List AI responses for a brand.

    Examples:
        scrunch responses list 123
        scrunch responses list 123 --platform chatgpt --table
        scrunch responses list 123 --start-date 2025-01-01 --end-date 2025-03-31
        scrunch responses list 123 --stage Awareness --limit 50
    """
    try:
        client = get_client()
        items = client.list_responses(
            brand_id,
            limit=limit,
            offset=offset,
            platform=platform,
            prompt_id=prompt_id,
            persona_id=persona_id,
            stage=stage,
            start_date=start_date,
            end_date=end_date,
            has_shopping_data=has_shopping_data,
        )
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
                    ["id", "platform", "stage", "brand_mentioned", "brand_position", "date"],
                    ["ID", "Platform", "Stage", "Brand Mentioned", "Position", "Date"],
                )
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "list": [
        "api_key"
    ]
}
