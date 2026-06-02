"""Commands for managing reminder lists (calendars)."""

from typing import Optional

import typer
from cli_tools_shared.filters import apply_filters, validate_filters

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_error

app = typer.Typer(help="Manage reminder lists (calendars)")


@app.command("list")
def list_lists(
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of lists"),
    filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List all reminder lists."""
    try:
        calendars = get_client().list_calendars()

        if filter:
            validate_filters(filter)
            calendars = apply_filters(calendars, filter)
        if limit is not None:
            calendars = calendars[:limit]
        if properties:
            fields = [field.strip() for field in properties.split(",") if field.strip()]
            calendars = [{field: calendar.get(field) for field in fields} for calendar in calendars]

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",") if field.strip()]
                rows = [[calendar.get(field, "") for field in fields] for calendar in calendars]
                print_table(fields, rows)
                return
            headers = ["ID", "Title", "Color", "Type", "Modifiable"]
            rows = [
                [
                    cal["id"],
                    cal["title"],
                    cal["color"] or "",
                    cal["type"],
                    "Yes" if cal["allows_modification"] else "No",
                ]
                for cal in calendars
            ]
            print_table(headers, rows)
        else:
            print_json(calendars)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("show")
def show_list(
    list_id: str = typer.Argument(..., help="List ID to show"),
):
    """Show details of a specific reminder list."""
    try:
        client = get_client()
        calendars = client.list_calendars()

        calendar = next((c for c in calendars if c["id"] == list_id), None)
        if not calendar:
            print_error(f"List not found: {list_id}")
            raise typer.Exit(1)

        print_json(calendar)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)
