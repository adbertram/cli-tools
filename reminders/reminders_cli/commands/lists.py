"""Commands for managing reminder lists (calendars)."""
import typer
from typing import Optional

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_error

app = typer.Typer(help="Manage reminder lists (calendars)")


@app.command("list")
def list_lists(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List all reminder lists."""
    try:
        client = get_client()
        calendars = client.list_calendars()

        if table:
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
