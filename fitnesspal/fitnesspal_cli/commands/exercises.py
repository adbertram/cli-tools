"""Exercise commands for MyFitnessPal CLI."""
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

app = typer.Typer(help="View exercise entries", no_args_is_help=True)


@app.command("list")
def exercises_list(
    days: int = typer.Option(7, "--days", "-d", help="Number of recent days to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of entries to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List recent exercise summaries.

    Shows exercises from the last N days.

    Examples:
        fitnesspal exercises list
        fitnesspal exercises list --days 14
        fitnesspal exercises list --table
    """
    try:
        client = get_client()
        today = dt_date.today()
        rows = []

        for i in range(min(days, limit)):
            target = today - timedelta(days=i)
            exercise_day = client.get_exercises(target.isoformat())
            for group in exercise_day.exercises:
                for entry in group.entries:
                    nutrition = entry.nutrition_information
                    rows.append({
                        "date": exercise_day.date,
                        "type": group.name,
                        "exercise": entry.name,
                        "calories_burned": nutrition.get("calories burned", 0),
                    })

        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")
            rows = apply_filters(rows, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            rows = [{k: item[k] for k in fields if k in item} for item in rows]

        rows = rows[:limit]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(rows, fields, fields)
            else:
                print_table(
                    rows,
                    ["date", "type", "exercise", "calories_burned"],
                    ["Date", "Type", "Exercise", "Calories Burned"],
                )
        else:
            print_json(rows)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def exercises_get(
    date: str = typer.Argument("today", help="Date to get exercises for (today, yesterday, YYYY-MM-DD)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get exercises for a specific date.

    Shows all exercise groups and individual exercise entries with
    nutrition information (calories burned, etc.).

    Examples:
        fitnesspal exercises get
        fitnesspal exercises get today
        fitnesspal exercises get yesterday
        fitnesspal exercises get 2024-01-15
        fitnesspal exercises get --table
    """
    try:
        client = get_client()
        exercise_day = client.get_exercises(date)

        if table:
            rows = []
            for group in exercise_day.exercises:
                for entry in group.entries:
                    nutrition = entry.nutrition_information
                    rows.append({
                        "type": group.name,
                        "exercise": entry.name,
                        "calories_burned": nutrition.get("calories burned", 0),
                    })
            if rows:
                print_table(
                    rows,
                    ["type", "exercise", "calories_burned"],
                    ["Type", "Exercise", "Calories Burned"],
                )
            else:
                from cli_tools_shared.output import print_info
                print_info(f"No exercises for {date}")
        else:
            print_json(exercise_day)

    except Exception as e:
        raise typer.Exit(handle_error(e))
