"""Reminder commands."""

from datetime import datetime
from typing import Optional

import typer

from cli_tools_shared.filters import apply_filters, validate_filters
from cli_tools_shared.output import print_error, print_json, print_success, print_table

from ..client import ClientError, get_client


def _select_properties(items: list[dict], properties: Optional[str]) -> list[dict]:
    if not properties:
        return items
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return [{field: item.get(field) for field in fields} for item in items]


def list_reminders(
    list_id: Optional[str] = typer.Option(None, "--list", help="Filter by list ID"),
    completed: Optional[bool] = typer.Option(None, "--completed", help="Show only completed reminders"),
    incomplete: Optional[bool] = typer.Option(None, "--incomplete", help="Show only incomplete reminders"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of reminders"),
    filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List reminders with optional filtering."""
    try:
        completion_filter = None
        if completed:
            completion_filter = True
        elif incomplete:
            completion_filter = False

        reminders = get_client().list_reminders(
            calendar_id=list_id,
            completed=completion_filter,
            limit=limit,
        )

        if filter:
            validate_filters(filter)
            reminders = apply_filters(reminders, filter)

        reminders = _select_properties(reminders, properties)

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",") if field.strip()]
                rows = [[reminder.get(field, "") for field in fields] for reminder in reminders]
                print_table(fields, rows)
                return
            headers = ["ID", "Tags", "Title", "List", "Completed", "Due Date", "Priority"]
            rows = [
                [
                    reminder["id"][:8] + "...",
                    ", ".join(f"#{tag}" for tag in reminder.get("tags", [])) if reminder.get("tags") else "",
                    reminder["title"][:40],
                    reminder.get("calendar_title", ""),
                    "✓" if reminder.get("completed") else "",
                    reminder.get("due_date", "")[:10] if reminder.get("due_date") else "",
                    reminder.get("priority") or "",
                ]
                for reminder in reminders
            ]
            print_table(headers, rows)
            return

        print_json(reminders)
    except ClientError as error:
        print_error(str(error))
        raise typer.Exit(1)


def show_reminder(
    reminder_id: str = typer.Argument(..., help="Reminder ID to show"),
):
    """Show details of a specific reminder."""
    try:
        reminder = get_client().get_reminder(reminder_id)
        if not reminder:
            print_error(f"Reminder not found: {reminder_id}")
            raise typer.Exit(1)
        print_json(reminder)
    except ClientError as error:
        print_error(str(error))
        raise typer.Exit(1)


def create_reminder(
    title: str = typer.Argument(..., help="Reminder title"),
    list_id: Optional[str] = typer.Option(None, "--list", help="List ID (uses default if not specified)"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Reminder notes"),
    due_date: Optional[str] = typer.Option(None, "--due", "-d", help="Due date (YYYY-MM-DD or YYYY-MM-DD HH:MM)"),
    priority: int = typer.Option(0, "--priority", "-p", help="Priority (0=none, 1=high, 5=medium, 9=low)"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags (e.g., 'WF,urgent')"),
):
    """Create a new reminder."""
    try:
        parsed_due_date = None
        if due_date:
            try:
                if " " in due_date:
                    parsed_due_date = datetime.strptime(due_date, "%Y-%m-%d %H:%M")
                else:
                    parsed_due_date = datetime.strptime(due_date, "%Y-%m-%d").replace(hour=9, minute=0)
            except ValueError:
                print_error(f"Invalid date format: {due_date}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM")
                raise typer.Exit(1)

        parsed_tags = None
        if tags:
            parsed_tags = [tag.strip().lstrip("#") for tag in tags.split(",") if tag.strip()]

        reminder = get_client().create_reminder(
            title=title,
            calendar_id=list_id,
            notes=notes,
            due_date=parsed_due_date,
            priority=priority,
            tags=parsed_tags,
        )
        print_success(f"Created reminder: {reminder['title']}")
        print_json(reminder)
    except ClientError as error:
        print_error(str(error))
        raise typer.Exit(1)


def complete_reminder(
    reminder_id: str = typer.Argument(..., help="Reminder ID to complete"),
):
    """Mark a reminder as completed."""
    try:
        reminder = get_client().complete_reminder(reminder_id)
        print_success(f"Completed: {reminder['title']}")
        print_json(reminder)
    except ClientError as error:
        print_error(str(error))
        raise typer.Exit(1)


def uncomplete_reminder(
    reminder_id: str = typer.Argument(..., help="Reminder ID to mark incomplete"),
):
    """Mark a reminder as incomplete."""
    try:
        reminder = get_client().uncomplete_reminder(reminder_id)
        print_success(f"Marked incomplete: {reminder['title']}")
        print_json(reminder)
    except ClientError as error:
        print_error(str(error))
        raise typer.Exit(1)


def delete_reminder(
    reminder_id: str = typer.Argument(..., help="Reminder ID to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a reminder."""
    try:
        client = get_client()
        reminder = client.get_reminder(reminder_id)
        if not reminder:
            print_error(f"Reminder not found: {reminder_id}")
            raise typer.Exit(1)

        if not yes and not typer.confirm(f"Delete reminder '{reminder['title']}'?"):
            typer.echo("Cancelled")
            raise typer.Exit(0)

        client.delete_reminder(reminder_id)
        print_success(f"Deleted reminder: {reminder['title']}")
    except ClientError as error:
        print_error(str(error))
        raise typer.Exit(1)
