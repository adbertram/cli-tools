"""Analytics commands for Cloudflare CLI (GraphQL Analytics API).

Commands:
  summary   - Zone traffic totals for a date range (httpRequests1dGroups)
  top-paths - Top request paths by HTML page views (httpRequestsAdaptiveGroups)
"""
from datetime import date, timedelta
from typing import List, Optional, Tuple

import typer

from ..client import get_client
from cli_tools_shared.filters import apply_filters, apply_properties_filter
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Zone traffic analytics (GraphQL Analytics API)", no_args_is_help=True)


def resolve_date_range(start: Optional[str], end: Optional[str]) -> Tuple[str, str]:
    """Validate a YYYY-MM-DD date range, defaulting to the last 30 days."""
    end_date = date.fromisoformat(end) if end else date.today()
    start_date = date.fromisoformat(start) if start else end_date - timedelta(days=30)
    if start_date > end_date:
        raise typer.BadParameter(f"--start {start_date} is after --end {end_date}")
    return start_date.isoformat(), end_date.isoformat()


@app.command("summary")
def analytics_summary(
    zone: str = typer.Argument(..., help="Zone name (e.g. example.com) or 32-character zone ID"),
    start: Optional[str] = typer.Option(None, "--start", "-s", help="Start date YYYY-MM-DD, inclusive (default: 30 days ago)"),
    end: Optional[str] = typer.Option(None, "--end", "-e", help="End date YYYY-MM-DD, inclusive (default: today)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as key-value table"),
):
    """
    Show zone traffic totals for a date range.

    Totals come from the httpRequests1dGroups daily rollup dataset:
    page views, unique visitors, requests, and bytes. unique_visitors is the
    sum of per-day uniques, not deduplicated across days.

    Examples:
        cloudflare analytics summary example.com
        cloudflare analytics summary example.com --start 2026-06-01 --end 2026-06-30
        cloudflare analytics summary example.com --table
    """
    try:
        start_date, end_date = resolve_date_range(start, end)
        client = get_client()
        zone_id = client.resolve_zone_id(zone)
        summary = client.get_analytics_summary(zone_id, start_date, end_date)
        summary = {"zone": zone, **summary}

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in summary.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(summary)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("top-paths")
def analytics_top_paths(
    zone: str = typer.Argument(..., help="Zone name (e.g. example.com) or 32-character zone ID"),
    start: Optional[str] = typer.Option(None, "--start", "-s", help="Start date YYYY-MM-DD, inclusive (default: 30 days ago)"),
    end: Optional[str] = typer.Option(None, "--end", "-e", help="End date YYYY-MM-DD, inclusive (default: today)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of paths to return"),
    filter_str: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., path:contains:powershell)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    Show top request paths by HTML page views for a date range.

    Uses the httpRequestsAdaptiveGroups dataset filtered to edge responses
    with content type "html" (page views). Data is adaptively sampled by
    Cloudflare, and pct_of_total is each path's share of all HTML page views
    in the range. Dataset retention varies by plan, so old ranges may return
    no data.

    Examples:
        cloudflare analytics top-paths example.com
        cloudflare analytics top-paths example.com --start 2026-06-01 --end 2026-06-30
        cloudflare analytics top-paths example.com --limit 5 --table
        cloudflare analytics top-paths example.com --filter "path:contains:blog"
    """
    try:
        start_date, end_date = resolve_date_range(start, end)
        client = get_client()
        zone_id = client.resolve_zone_id(zone)
        paths = client.get_top_paths(zone_id, start_date, end_date, limit=limit)

        if filter_str:
            paths = apply_filters(paths, filter_str)

        if properties:
            paths = apply_properties_filter(paths, properties)

        if table:
            print_table(
                paths,
                ["path", "page_views", "pct_of_total"],
                ["Path", "Page Views", "% of Total"],
            )
        else:
            print_json(paths)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "summary": [
        "api_key"
    ],
    "top-paths": [
        "api_key"
    ]
}
