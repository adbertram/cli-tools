"""Report commands for MyFitnessPal CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.exceptions import ClientError

COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ]
}

app = typer.Typer(help="View nutrition and fitness reports", no_args_is_help=True)


@app.command("list")
def reports_list(
    report_name: str = typer.Option("Net Calories", "--name", "-n", help="Report metric (e.g., Net Calories, Total Calories)"),
    category: str = typer.Option("Nutrition", "--category", "-c", help="Report category (e.g., Nutrition, Exercise)"),
    from_date: Optional[str] = typer.Option(None, "--from", help="Start date (YYYY-MM-DD)"),
    to_date: Optional[str] = typer.Option(None, "--to", help="End date (YYYY-MM-DD)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of entries to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List report data by metric and date range.

    Examples:
        fitnesspal reports list
        fitnesspal reports list --name "Net Calories"
        fitnesspal reports list --name "Total Calories" --category Nutrition
        fitnesspal reports list --from 2024-01-01 --to 2024-01-31
        fitnesspal reports list --table --limit 7
        fitnesspal reports list --filter "value:gt:1500"
    """
    try:
        client = get_client()
        entries = client.get_report(
            report_name=report_name,
            report_category=category,
            lower_bound=from_date,
            upper_bound=to_date,
            limit=limit,
        )

        items = [e.to_dict() for e in entries]

        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")
            items = apply_filters(items, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            items = [{k: item[k] for k in fields if k in item} for item in items]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(items, fields, fields)
            else:
                print_table(items, ["date", "value"], ["Date", "Value"])
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def reports_get(
    date: str = typer.Argument(..., help="Date to get report for (YYYY-MM-DD)"),
    report_name: str = typer.Option("Net Calories", "--name", "-n", help="Report metric (e.g., Net Calories, Total Calories)"),
    category: str = typer.Option("Nutrition", "--category", "-c", help="Report category (e.g., Nutrition, Exercise)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get report value for a specific date.

    Examples:
        fitnesspal reports get 2024-01-15
        fitnesspal reports get 2024-01-15 --name "Total Calories"
        fitnesspal reports get 2024-01-15 --table
    """
    try:
        client = get_client()
        entries = client.get_report(
            report_name=report_name,
            report_category=category,
            lower_bound=date,
            upper_bound=date,
            limit=1,
        )

        if not entries:
            from cli_tools_shared.output import print_info
            print_info(f"No {report_name} report data for {date}")
            raise typer.Exit(0)

        entry = entries[0]

        if table:
            item_dict = entry.to_dict()
            rows = [{"field": k, "value": str(v)} for k, v in item_dict.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(entry)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
