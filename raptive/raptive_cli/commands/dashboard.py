"""Dashboard commands for Raptive CLI."""
import typer

from cli_tools_shared.output import command

from ..client import get_client
from ..dates import get_date_range
from ..output import print_json, print_table

COMMAND_CREDENTIALS = {
    "date-bounds": [
        "browser_session"
    ],
    "summary": [
        "browser_session"
    ]
}

app = typer.Typer(help="View dashboard metrics and summaries")


@app.command("summary")
@command
def dashboard_summary(
    period: str = typer.Option(
        "last30d",
        "--period", "-p",
        help="Time period: yesterday, last7d, last30d, mtd, lastmonth",
    ),
    start: str = typer.Option(
        None,
        "--start", "-s",
        help="Start date (YYYY-MM-DD). Overrides --period.",
    ),
    end: str = typer.Option(
        None,
        "--end", "-e",
        help="End date (YYYY-MM-DD). Overrides --period.",
    ),
    table: bool = typer.Option(
        False,
        "--table", "-t",
        help="Display as table",
    ),
):
    """
    Get dashboard summary metrics for a date range.

    Shows earnings, RPM, sessions, and pageviews.

    Examples:
        raptive dashboard summary --period last7d
        raptive dashboard summary --start 2025-12-01 --end 2025-12-31
        raptive dashboard summary --table
    """
    start_date, end_date = get_date_range(period, start, end)

    client = get_client()
    summary = client.get_dashboard_summary(start_date, end_date)

    if table:
        rows = [
            {"metric": "Date Range", "value": f"{summary.start_date} to {summary.end_date}"},
            {"metric": "Earnings", "value": f"${summary.earnings:.2f}"},
            {"metric": "RPM", "value": f"${summary.rpm:.2f}" if summary.rpm else "N/A"},
            {"metric": "Page RPM", "value": f"${summary.page_rpm:.2f}" if summary.page_rpm else "N/A"},
            {"metric": "Sessions", "value": f"{summary.sessions:,}" if summary.sessions else "N/A"},
            {"metric": "Pageviews", "value": f"{summary.pageviews:,}" if summary.pageviews else "N/A"},
        ]
        print_table(rows, ["metric", "value"], ["Metric", "Value"])
    else:
        print_json(summary)


@app.command("date-bounds")
@command
def dashboard_date_bounds(
    table: bool = typer.Option(
        False,
        "--table", "-t",
        help="Display as table",
    ),
):
    """
    Get the date bounds for available data.

    Shows the earliest and latest dates with data.
    """
    client = get_client()
    bounds = client.get_date_bounds()

    if table:
        rows = [
            {"field": "Earliest Date", "value": bounds.earliest_date},
            {"field": "Latest Date", "value": bounds.latest_date},
        ]
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(bounds)