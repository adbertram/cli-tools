"""Main entry point for Reminders CLI."""
import typer
from typing import Optional
from datetime import datetime

from . import __version__
from cli_tools_shared import create_app, run_app
from .client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_error, print_success

app = create_app(
    name="reminders",
    help="CLI for managing macOS Reminders",
    version=__version__,
    cache_support=False,
)

# Register lists subcommand
from .commands import lists
app.add_typer(lists.app, name="lists", help="Manage reminder lists")


@app.command("list")
def list_reminders(
    list_id: Optional[str] = typer.Option(None, "--list", "-l", help="Filter by list ID"),
    completed: Optional[bool] = typer.Option(None, "--completed", "-c", help="Show only completed"),
    incomplete: Optional[bool] = typer.Option(None, "--incomplete", "-i", help="Show only incomplete"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum number of reminders"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List reminders with optional filtering."""
    try:
        client = get_client()

        # Determine completion filter
        completion_filter = None
        if completed:
            completion_filter = True
        elif incomplete:
            completion_filter = False

        reminders = client.list_reminders(
            calendar_id=list_id,
            completed=completion_filter,
            limit=limit,
        )

        if table:
            headers = ["ID", "Tags", "Title", "List", "Completed", "Due Date", "Priority"]
            rows = [
                [
                    r["id"][:8] + "...",  # Truncate ID for table display
                    ", ".join(f"#{t}" for t in r.get("tags", [])) if r.get("tags") else "",
                    r["title"][:40],  # Truncate title
                    r["calendar_title"],
                    "✓" if r["completed"] else "",
                    r.get("due_date", "")[:10] if r.get("due_date") else "",
                    r["priority"] if r["priority"] else "",
                ]
                for r in reminders
            ]
            print_table(headers, rows)
        else:
            print_json(reminders)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("show")
def show_reminder(
    reminder_id: str = typer.Argument(..., help="Reminder ID to show"),
):
    """Show details of a specific reminder."""
    try:
        client = get_client()
        reminder = client.get_reminder(reminder_id)

        if not reminder:
            print_error(f"Reminder not found: {reminder_id}")
            raise typer.Exit(1)

        print_json(reminder)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("create")
def create_reminder(
    title: str = typer.Argument(..., help="Reminder title"),
    list_id: Optional[str] = typer.Option(None, "--list", "-l", help="List ID (uses default if not specified)"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Reminder notes"),
    due_date: Optional[str] = typer.Option(None, "--due", "-d", help="Due date (YYYY-MM-DD or YYYY-MM-DD HH:MM)"),
    priority: int = typer.Option(0, "--priority", "-p", help="Priority (0=none, 1=high, 5=medium, 9=low)"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags (e.g., 'WF,urgent')"),
):
    """Create a new reminder."""
    try:
        client = get_client()

        # Parse due date if provided
        due_dt = None
        if due_date:
            try:
                # Try with time first
                if " " in due_date:
                    due_dt = datetime.strptime(due_date, "%Y-%m-%d %H:%M")
                else:
                    # Just date, set to 9 AM
                    due_dt = datetime.strptime(due_date, "%Y-%m-%d").replace(hour=9, minute=0)
            except ValueError:
                print_error(f"Invalid date format: {due_date}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM")
                raise typer.Exit(1)

        # Parse tags if provided
        tag_list = None
        if tags:
            tag_list = [t.strip().lstrip('#') for t in tags.split(',') if t.strip()]

        reminder = client.create_reminder(
            title=title,
            calendar_id=list_id,
            notes=notes,
            due_date=due_dt,
            priority=priority,
            tags=tag_list,
        )

        print_success(f"Created reminder: {reminder['title']}")
        print_json(reminder)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("complete")
def complete_reminder(
    reminder_id: str = typer.Argument(..., help="Reminder ID to complete"),
):
    """Mark a reminder as completed."""
    try:
        client = get_client()
        reminder = client.complete_reminder(reminder_id)

        print_success(f"Completed: {reminder['title']}")
        print_json(reminder)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("uncomplete")
def uncomplete_reminder(
    reminder_id: str = typer.Argument(..., help="Reminder ID to mark incomplete"),
):
    """Mark a reminder as incomplete."""
    try:
        client = get_client()
        reminder = client.uncomplete_reminder(reminder_id)

        print_success(f"Marked incomplete: {reminder['title']}")
        print_json(reminder)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("delete")
def delete_reminder(
    reminder_id: str = typer.Argument(..., help="Reminder ID to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a reminder."""
    try:
        client = get_client()

        # Get reminder details for confirmation
        reminder = client.get_reminder(reminder_id)
        if not reminder:
            print_error(f"Reminder not found: {reminder_id}")
            raise typer.Exit(1)

        # Confirm deletion
        if not yes:
            confirm = typer.confirm(f"Delete reminder '{reminder['title']}'?")
            if not confirm:
                typer.echo("Cancelled")
                raise typer.Exit(0)

        client.delete_reminder(reminder_id)
        print_success(f"Deleted reminder: {reminder['title']}")

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
