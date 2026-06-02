"""Notification commands for Notifier CLI."""
from typing import Optional

import typer
from cli_tools_shared.output import handle_error, print_error, print_success

from .client import ClientError, get_client


def send_notification(
    message: Optional[str] = typer.Option(
        None, "--message", "-m", help="Notification message (or pipe via stdin)"
    ),
    title: Optional[str] = typer.Option(
        None, "--title", "-T", help="Notification title"
    ),
    subtitle: Optional[str] = typer.Option(
        None, "--subtitle", "-s", help="Notification subtitle"
    ),
    sound: Optional[str] = typer.Option(
        None,
        "--sound",
        help="Sound to play (e.g., 'default', 'Basso', 'Blow', 'Bottle')",
    ),
    ignore_dnd: bool = typer.Option(
        False, "--ignore-dnd", help="Send even if Do Not Disturb is enabled"
    ),
):
    """
    Send a desktop notification.

    The message can be provided via --message or piped from stdin.

    Examples:
        notifier send --message "Hello World"
        notifier send -m "Build complete" -T "CI/CD" --sound default
        echo "Task finished" | notifier send -T "Background Job"
        notifier send -m "Urgent" --ignore-dnd
    """
    try:
        result = get_client().send_notification(
            message=message,
            title=title,
            subtitle=subtitle,
            sound=sound,
            ignore_dnd=ignore_dnd,
        )

        if result.success:
            print_success(result.message or "Notification sent")
            return

        print_error(result.message or "Failed to send notification")
        raise typer.Exit(1)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
