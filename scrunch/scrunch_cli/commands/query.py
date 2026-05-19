"""Query commands for Scrunch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from .helpers import model_to_dict, extract_fields
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter


app = typer.Typer(help="Query aggregated metrics", no_args_is_help=True)


@app.command("metrics")
def query_metrics(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    start_date: Optional[str] = typer.Option(None, "--start-date", help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end-date", help="End date (YYYY-MM-DD)"),
    fields: Optional[str] = typer.Option(None, "--fields", help="Comma-separated dimension/metric fields to include in query"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(1000, "--limit", "-l", help="Maximum number of items to return (max 90000)"),
    offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include in output"),
):
    """Query aggregated metrics for a brand.

    Dimensions: date, date_week, date_month, date_quarter, date_year, prompt_id, prompt,
    persona_id, persona_name, ai_platform, ai_platform_search_enabled, tag, source_url,
    source_type, competitor_id, competitor_name, branded, stage, prompt_topic, country

    Metrics: responses, brand_presence_percentage, brand_position_score,
    brand_sentiment_score, competitor_presence_percentage, competitor_position_score,
    competitor_sentiment_score

    Examples:
        scrunch query metrics 123 --start-date 2025-01-01 --end-date 2025-03-31
        scrunch query metrics 123 --fields "date,ai_platform,brand_presence_percentage" --table
        scrunch query metrics 123 --limit 500 --offset 0
    """
    try:
        client = get_client()
        items = client.query_metrics(
            brand_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
            fields=fields,
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
                # Use field names from first item as columns if available
                if items:
                    cols = [k for k in items[0].keys() if items[0][k] is not None]
                    print_table(items, cols, cols)
                else:
                    print_json(items)
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "metrics": [
        "api_key"
    ]
}
