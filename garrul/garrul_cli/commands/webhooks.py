"""Outbound webhook endpoints."""

COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "create": ["no_auth"],
    "update": ["no_auth"],
    "delete": ["no_auth"],
}

import sys
from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command

from ..client import get_client, segment
from ..parsers import WEBHOOK_EVENTS as EVENTS
from ..helpers import emit_record, emit_rows, mutate, selected, validated

app = typer.Typer(help="Manage webhook endpoints", no_args_is_help=True)

ADAPTERS = ("generic", "slack", "discord", "telegram")
COLUMNS = ["id", "url", "adapter", "events", "signing", "enabled"]
FIELDS = [*COLUMNS, "created_at"]


def _fields(url: str, adapter: str, events: List[str], enabled: bool, secret_stdin: bool, clear_secret: bool) -> dict:
    if adapter not in ADAPTERS:
        raise ClientError(f"Invalid --adapter {adapter!r}. Valid values: {', '.join(ADAPTERS)}.")
    unknown = [event for event in events if event not in EVENTS]
    if unknown:
        raise ClientError(f"Unknown --event {', '.join(unknown)}. Valid values: {', '.join(EVENTS)}.")
    if secret_stdin and clear_secret:
        raise ClientError("Pass either --secret-stdin or --clear-secret, not both.")
    fields: dict = {"url": url, "adapter": adapter, "events": events, "enabled": enabled}
    if clear_secret:
        fields["secret"] = None
    if secret_stdin:
        secret = sys.stdin.read().strip()
        if not secret:
            raise ClientError("--secret-stdin was given but stdin was empty.")
        fields["secret"] = secret
    return fields


def _redacted(fields: dict) -> dict:
    """Request preview with the signing secret masked."""
    return {**fields, "secret": "<redacted>"} if isinstance(fields.get("secret"), str) else fields


@app.command("list")
@command
def list_webhooks(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of endpoints"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List webhook endpoints. Garrul renders them all on one page."""
    filters = validated(filter, FIELDS)
    names = selected(properties, FIELDS)
    emit_rows(get_client().list_webhooks(), filters, limit, table, names, COLUMNS, "No webhook endpoints configured yet.")


@app.command("get")
@command
def get_webhook(
    webhook_id: str = typer.Argument(..., help="Webhook endpoint id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one webhook endpoint. The signing secret is write-only and never returned."""
    emit_record(get_client().get_webhook(webhook_id), table, properties)


@app.command("create")
@command
def create_webhook(
    url: str = typer.Option(..., "--url", help="https URL, or a Telegram chat id for the telegram adapter"),
    adapter: str = typer.Option(..., "--adapter", help="generic, slack, discord or telegram"),
    event: Optional[List[str]] = typer.Option(None, "--event", help="Event to deliver (repeatable). None means every event"),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Whether the endpoint delivers"),
    secret_stdin: bool = typer.Option(False, "--secret-stdin", help="Read a 16 to 256 character signing secret from stdin"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Create the endpoint"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Create a webhook endpoint."""
    fields = _fields(url, adapter, event or list(EVENTS), enabled, secret_stdin, False)
    mutate(
        "create a webhook endpoint",
        {"method": "POST", "path": "/admin/api/webhooks", "body": _redacted(fields)},
        yes,
        dry_run,
        lambda: get_client().create_webhook(fields),
    )


@app.command("update")
@command
def update_webhook(
    webhook_id: str = typer.Argument(..., help="Webhook endpoint id"),
    url: str = typer.Option(..., "--url", help="https URL, or a Telegram chat id for the telegram adapter"),
    adapter: str = typer.Option(..., "--adapter", help="generic, slack, discord or telegram"),
    event: Optional[List[str]] = typer.Option(None, "--event", help="Event to deliver (repeatable). None means every event"),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Whether the endpoint delivers"),
    secret_stdin: bool = typer.Option(False, "--secret-stdin", help="Rotate the signing secret to the value read from stdin"),
    clear_secret: bool = typer.Option(False, "--clear-secret", help="Remove signing from this endpoint"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Replace a webhook endpoint's url, adapter, events and enabled state.

    Garrul treats an update as a full replacement of those four fields. The
    signing secret is the exception: it is kept unless you rotate or clear it.
    """
    fields = _fields(url, adapter, event or list(EVENTS), enabled, secret_stdin, clear_secret)
    mutate(
        f"update webhook endpoint {webhook_id}",
        {"method": "PATCH", "path": f"/admin/api/webhooks/{segment(webhook_id)}", "body": _redacted(fields)},
        yes,
        dry_run,
        lambda: get_client().update_webhook(webhook_id, fields),
    )


@app.command("delete")
@command
def delete_webhook(
    webhook_id: str = typer.Argument(..., help="Webhook endpoint id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Delete the endpoint. This cannot be undone"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Permanently delete a webhook endpoint."""
    mutate(
        f"delete webhook endpoint {webhook_id}",
        {"method": "DELETE", "path": f"/admin/api/webhooks/{segment(webhook_id)}"},
        yes,
        dry_run,
        lambda: get_client().delete_webhook(webhook_id),
    )
