"""Subscriber commands."""
COMMAND_CREDENTIALS = {
    "create": [
        "api_key"
    ],
    "delete": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "remind": [
        "api_key"
    ],
    "send-link": [
        "api_key"
    ],
    "update": [
        "api_key"
    ]
}

from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from .common import confirm_delete, emit, parse_json_object


app = typer.Typer(help="Manage subscribers", no_args_is_help=True)


@app.command("list")
def subscribers_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of subscribers"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List subscribers."""
    try:
        # filter_map translation happens in the client with Buttondown query params.
        subscribers = get_client().list_subscribers(limit=limit, filters=filter)
        emit(subscribers, table, properties, ["id", "email_address", "type", "source", "creation_date"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def subscribers_get(
    id_or_email: str = typer.Argument(..., help="Subscriber ID or email address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a subscriber."""
    try:
        emit(get_client().get_subscriber(id_or_email), table, properties, ["id", "email_address", "type"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("create")
def subscribers_create(
    email_address: str = typer.Option(..., "--email", "-e", help="Subscriber email address"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Private notes"),
    metadata: Optional[str] = typer.Option(None, "--metadata", help="Metadata JSON object"),
    tag: Optional[List[str]] = typer.Option(None, "--tag", help="Tag to assign; repeatable"),
    subscriber_type: Optional[str] = typer.Option(None, "--type", help="Subscriber type"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Create a subscriber."""
    try:
        subscriber = get_client().create_subscriber(
            email_address=email_address,
            notes=notes,
            metadata=parse_json_object(metadata, "--metadata"),
            tags=tag,
            subscriber_type=subscriber_type,
        )
        emit(subscriber, table, properties, ["id", "email_address", "type"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("update")
def subscribers_update(
    id_or_email: str = typer.Argument(..., help="Subscriber ID or email address"),
    email_address: Optional[str] = typer.Option(None, "--email", "-e", help="Updated email address"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Private notes"),
    metadata: Optional[str] = typer.Option(None, "--metadata", help="Metadata JSON object"),
    tag: Optional[List[str]] = typer.Option(None, "--tag", help="Replacement tag; repeatable"),
    subscriber_type: Optional[str] = typer.Option(None, "--type", help="Subscriber type"),
    commenting_disabled: Optional[bool] = typer.Option(None, "--commenting-disabled/--commenting-enabled", help="Commenting state"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Update a subscriber."""
    try:
        subscriber = get_client().update_subscriber(
            id_or_email,
            email_address=email_address,
            notes=notes,
            metadata=parse_json_object(metadata, "--metadata"),
            tags=tag,
            type=subscriber_type,
            commenting_disabled=commenting_disabled,
        )
        emit(subscriber, table, properties, ["id", "email_address", "type"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("delete")
def subscribers_delete(
    id_or_email: str = typer.Argument(..., help="Subscriber ID or email address"),
    force: bool = typer.Option(False, "--force", "-F", help="Delete without confirmation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Delete a subscriber."""
    try:
        confirm_delete("subscriber", id_or_email, force)
        emit(get_client().delete_subscriber(id_or_email), table, None, ["ok", "action", "id"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("send-link")
def subscribers_send_link(
    id_or_email: str = typer.Argument(..., help="Subscriber ID or email address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Send a subscriber magic link."""
    try:
        emit(get_client().send_magic_link(id_or_email), table, None, ["ok", "action", "id"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("remind")
def subscribers_remind(
    id_or_email: str = typer.Argument(..., help="Subscriber ID or email address"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Send a subscriber reminder."""
    try:
        emit(get_client().send_reminder(id_or_email), table, None, ["ok", "action", "id"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
