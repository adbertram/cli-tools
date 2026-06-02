"""Measurement commands for MyFitnessPal CLI."""
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

app = typer.Typer(help="View body measurements", no_args_is_help=True)


@app.command("list")
def measurements_list(
    measurement: str = typer.Option("Weight", "--measurement", "-m", help="Measurement type (e.g., Weight, Body Fat)"),
    from_date: Optional[str] = typer.Option(None, "--from", help="Start date (YYYY-MM-DD)"),
    to_date: Optional[str] = typer.Option(None, "--to", help="End date (YYYY-MM-DD)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of entries to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List measurements by type and date range.

    Shows body measurements like Weight, Body Fat, etc.

    Examples:
        fitnesspal measurements list
        fitnesspal measurements list --measurement Weight
        fitnesspal measurements list --measurement "Body Fat"
        fitnesspal measurements list --from 2024-01-01 --to 2024-01-31
        fitnesspal measurements list --table --limit 10
        fitnesspal measurements list --filter "value:gt:150"
    """
    try:
        client = get_client()
        entries = client.list_measurements(
            measurement=measurement,
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
def measurements_get(
    date: str = typer.Argument(..., help="Date to get measurement for (YYYY-MM-DD)"),
    measurement: str = typer.Option("Weight", "--measurement", "-m", help="Measurement type (e.g., Weight, Body Fat)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get measurement for a specific date.

    Examples:
        fitnesspal measurements get 2024-01-15
        fitnesspal measurements get 2024-01-15 --measurement "Body Fat"
        fitnesspal measurements get 2024-01-15 --table
    """
    try:
        client = get_client()
        entries = client.list_measurements(
            measurement=measurement,
            lower_bound=date,
            upper_bound=date,
            limit=1,
        )

        if not entries:
            from cli_tools_shared.output import print_info
            print_info(f"No {measurement} measurement for {date}")
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
