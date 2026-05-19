"""Agent traffic commands for Scrunch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from ..models import create_agent_traffic_row
from .helpers import model_to_dict, extract_fields
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter


app = typer.Typer(help="View agent traffic data", no_args_is_help=True)


@app.command("get")
def agent_traffic_get(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    site_id: int = typer.Argument(..., help="Site ID"),
    start_date: str = typer.Option(..., "--start-date", help="Start date (YYYY-MM-DD, required)"),
    end_date: str = typer.Option(..., "--end-date", help="End date (YYYY-MM-DD, required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset"),
    fields: Optional[str] = typer.Option(None, "--fields", help="Comma-separated fields to request"),
    time_bucket: Optional[str] = typer.Option(None, "--time-bucket", help="Time bucket for aggregation"),
    path: Optional[str] = typer.Option(None, "--path", help="Filter by URL path"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include in output"),
):
    """Get agent traffic data for a brand's site.

    Both brand_id and site_id are required positional arguments.
    start_date and end_date are required options.

    Examples:
        scrunch agent-traffic get 123 789 --start-date 2025-01-01 --end-date 2025-03-31
        scrunch agent-traffic get 123 789 --start-date 2025-01-01 --end-date 2025-03-31 --table
        scrunch agent-traffic get 123 789 --start-date 2025-01-01 --end-date 2025-03-31 --time-bucket day
        scrunch agent-traffic get 123 789 --start-date 2025-01-01 --end-date 2025-03-31 --path "/blog"
    """
    try:
        client = get_client()
        response = client.get_agent_traffic(
            brand_id,
            site_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
            fields=fields,
            time_bucket=time_bucket,
            path=path,
        )

        # Convert AgentTrafficResponse data rows to dicts
        items = []
        for row in response.data:
            if isinstance(row, dict):
                items.append(row)
            else:
                items.append(model_to_dict(row))

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
                    ["date", "agent_source", "agent_type", "path", "requests"],
                    ["Date", "Agent Source", "Agent Type", "Path", "Requests"],
                )
        else:
            # Output the full response including meta
            output = {
                "meta": response.meta,
                "data": items,
            }
            print_json(output)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "api_key"
    ]
}
