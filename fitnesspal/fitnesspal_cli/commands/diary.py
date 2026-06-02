"""Diary commands for MyFitnessPal CLI."""
import typer
from typing import Optional, List
from datetime import date as dt_date, timedelta

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

app = typer.Typer(help="View food diary entries", no_args_is_help=True)


@app.command("list")
def diary_list(
    days: int = typer.Option(7, "--days", "-d", help="Number of recent days to list"),
    period: Optional[str] = typer.Option(None, "--period", help="Date period shortcut: today, yesterday, last_week (overrides --days)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of entries to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List recent diary day summaries.

    Shows nutrition totals for the last N days.

    Examples:
        fitnesspal diary list
        fitnesspal diary list --days 14
        fitnesspal diary list --period today
        fitnesspal diary list --period yesterday
        fitnesspal diary list --period last_week
        fitnesspal diary list --table
        fitnesspal diary list --filter "complete:true"
    """
    try:
        client = get_client()
        today = dt_date.today()
        summaries = []

        if period:
            period_lower = period.lower()
            if period_lower == "today":
                start_date = today
                num_days = 1
            elif period_lower == "yesterday":
                start_date = today - timedelta(days=1)
                num_days = 1
            elif period_lower == "last_week":
                start_date = today
                num_days = 7
            else:
                from cli_tools_shared.exceptions import ClientError
                raise ClientError(f"Invalid period: '{period}'. Use today, yesterday, or last_week.")
        else:
            start_date = today
            num_days = days

        for i in range(min(num_days, limit)):
            target = start_date - timedelta(days=i)
            day = client.get_diary(target.isoformat())
            summaries.append({
                "date": day.date,
                "calories": day.totals.get("calories", 0),
                "carbohydrates": day.totals.get("carbohydrates", 0),
                "fat": day.totals.get("fat", 0),
                "protein": day.totals.get("protein", 0),
                "water": day.water,
                "complete": day.complete,
            })

        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")
            summaries = apply_filters(summaries, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            summaries = [{k: item[k] for k in fields if k in item} for item in summaries]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(summaries, fields, fields)
            else:
                print_table(
                    summaries,
                    ["date", "calories", "carbohydrates", "fat", "protein", "complete"],
                    ["Date", "Calories", "Carbs", "Fat", "Protein", "Complete"],
                )
        else:
            print_json(summaries)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def diary_get(
    date: str = typer.Argument("today", help="Date to get diary for (today, yesterday, YYYY-MM-DD)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get the food diary for a specific date.

    Shows all meals, entries, nutrition totals, goals, notes, and water intake.

    Examples:
        fitnesspal diary get
        fitnesspal diary get today
        fitnesspal diary get yesterday
        fitnesspal diary get 2024-01-15
        fitnesspal diary get --table
    """
    try:
        client = get_client()
        day = client.get_diary(date)

        if table:
            rows = []
            for meal in day.meals:
                for entry in meal.entries:
                    nutrition = entry.nutrition_information
                    rows.append({
                        "meal": meal.name,
                        "food": entry.name,
                        "calories": nutrition.get("calories", 0),
                        "carbohydrates": nutrition.get("carbohydrates", 0),
                        "fat": nutrition.get("fat", 0),
                        "protein": nutrition.get("protein", 0),
                    })
            if rows:
                print_table(
                    rows,
                    ["meal", "food", "calories", "carbohydrates", "fat", "protein"],
                    ["Meal", "Food", "Calories", "Carbs", "Fat", "Protein"],
                )
            else:
                from cli_tools_shared.output import print_info
                print_info(f"No diary entries for {date}")
        else:
            print_json(day)

    except Exception as e:
        raise typer.Exit(handle_error(e))
