"""Notification commands for Bricklink CLI (browser-based)."""
COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "send-wanted-list": [
        "browser_session"
    ]
}

import typer
from typing import Optional, List

from ..display import print_detail
from cli_tools_shared.output import print_json, print_success, handle_error
from . import render_list, run_browser

app = typer.Typer(help="Manage notifications (browser)", no_args_is_help=True)


WANTED_LIST_NOTIFICATION = {
    "type": "wanted_list",
    "name": "Wanted List Notification",
    "description": "Send wanted list notification to matching stores",
    "command": "bricklink notification send-wanted-list",
}


def _get_notification(notification_type: str) -> dict | None:
    if notification_type == WANTED_LIST_NOTIFICATION["type"]:
        return WANTED_LIST_NOTIFICATION
    if notification_type.lower() == WANTED_LIST_NOTIFICATION["name"].lower():
        return WANTED_LIST_NOTIFICATION
    return None


@app.command("list")
def notification_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    List available notification actions.

    Shows the notification types that can be sent via the browser.

    Examples:
        bricklink notification list
        bricklink notification list --table
        bricklink notification list --filter type:eq:wanted_list
        bricklink notification list --properties type,name
    """
    try:
        render_list(
            [WANTED_LIST_NOTIFICATION],
            table,
            properties,
            ["type", "name", "description"],
            ["Type", "Name", "Description"],
            filter=filter,
            limit=limit,
        )

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def notification_get(
    notification_type: str = typer.Argument("wanted_list", help="Notification type"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details about a notification type.

    Examples:
        bricklink notification get wanted_list
        bricklink notification get wanted_list --table
    """
    try:
        data = _get_notification(notification_type)
        if not data:
            from cli_tools_shared.output import print_error
            print_error(f"Unknown notification type: {notification_type}. Available: {WANTED_LIST_NOTIFICATION['type']}")
            raise typer.Exit(1)

        print_detail(data, table)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send-wanted-list")
def notification_send_wanted_list():
    """
    Send wanted list notification to all matching stores.

    Examples:
        bricklink notification send-wanted-list
    """
    send_wanted_list_notification()


def send_wanted_list_notification():
    """Send wanted list notification to all matching stores."""
    try:
        result = run_browser(lambda browser: browser.send_wanted_list_notification())
        if result.get("success"):
            print_success("Wanted list notification sent")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
