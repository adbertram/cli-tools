"""RSS-to-email (external feeds) commands."""
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
    "update": [
        "api_key"
    ]
}

from pathlib import Path
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from .common import confirm_delete, emit, parse_json_object, read_body


app = typer.Typer(help="Manage RSS-to-email external feeds", no_args_is_help=True)


_DEFAULT_COLUMNS = ["id", "url", "cadence", "behavior", "status", "last_checked_date", "label"]


@app.command("list")
def feeds_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of feeds"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List external RSS feeds."""
    try:
        feeds = get_client().list_external_feeds(limit=limit, filters=filter)
        emit(feeds, table, properties, _DEFAULT_COLUMNS)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def feeds_get(
    feed_id: str = typer.Argument(..., help="External feed ID (rss_...)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a single RSS feed."""
    try:
        emit(get_client().get_external_feed(feed_id), table, properties, _DEFAULT_COLUMNS)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("create")
def feeds_create(
    url: str = typer.Option(..., "--url", "-u", help="Feed URL"),
    subject: str = typer.Option(..., "--subject", "-s", help="Subject line template"),
    body: Optional[str] = typer.Option(None, "--body", help="Body template"),
    body_file: Optional[Path] = typer.Option(None, "--body-file", help="Read body template from file"),
    cadence: str = typer.Option(..., "--cadence", "-c", help="Cadence: every | daily | weekly | monthly"),
    behavior: str = typer.Option(..., "--behavior", "-b", help="Behavior: draft | emails"),
    cadence_metadata: Optional[str] = typer.Option(None, "--cadence-metadata", help="Cadence metadata JSON object"),
    filters: Optional[str] = typer.Option(None, "--filters", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    label: Optional[str] = typer.Option(None, "--label", help="Internal label"),
    metadata: Optional[str] = typer.Option(None, "--metadata", help="Metadata JSON object"),
    skip_old_items: Optional[bool] = typer.Option(None, "--skip-old-items/--no-skip-old-items", help="Skip old items"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Create a new RSS feed."""
    try:
        feed = get_client().create_external_feed(
            url=url,
            subject=subject,
            body=read_body(body, body_file),
            cadence=cadence,
            behavior=behavior,
            cadence_metadata=parse_json_object(cadence_metadata, "--cadence-metadata")
            if cadence_metadata is not None
            else {},
            filters=parse_json_object(filters, "--filters")
            if filters is not None
            else {"filters": [], "groups": [], "predicate": "and"},
            label=label,
            metadata=parse_json_object(metadata, "--metadata"),
            skip_old_items=skip_old_items,
        )
        emit(feed, table, properties, _DEFAULT_COLUMNS)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("update")
def feeds_update(
    feed_id: str = typer.Argument(..., help="External feed ID (rss_...)"),
    subject: Optional[str] = typer.Option(None, "--subject", "-s", help="Subject line template"),
    body: Optional[str] = typer.Option(None, "--body", help="Body template"),
    body_file: Optional[Path] = typer.Option(None, "--body-file", help="Read body template from file"),
    cadence: Optional[str] = typer.Option(None, "--cadence", "-c", help="Cadence: every | daily | weekly | monthly"),
    behavior: Optional[str] = typer.Option(None, "--behavior", "-b", help="Behavior: draft | emails"),
    cadence_metadata: Optional[str] = typer.Option(None, "--cadence-metadata", help="Cadence metadata JSON object"),
    filters: Optional[str] = typer.Option(None, "--filters", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    label: Optional[str] = typer.Option(None, "--label", help="Internal label"),
    metadata: Optional[str] = typer.Option(None, "--metadata", help="Metadata JSON object"),
    status: Optional[str] = typer.Option(None, "--status", help="Status: active | inactive"),
    skip_old_items: Optional[bool] = typer.Option(None, "--skip-old-items/--no-skip-old-items", help="Skip old items"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Update an existing RSS feed."""
    try:
        feed = get_client().update_external_feed(
            feed_id,
            subject=subject,
            body=read_body(body, body_file),
            cadence=cadence,
            behavior=behavior,
            cadence_metadata=parse_json_object(cadence_metadata, "--cadence-metadata"),
            filters=parse_json_object(filters, "--filters"),
            label=label,
            metadata=parse_json_object(metadata, "--metadata"),
            status=status,
            skip_old_items=skip_old_items,
        )
        emit(feed, table, properties, _DEFAULT_COLUMNS)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("delete")
def feeds_delete(
    feed_id: str = typer.Argument(..., help="External feed ID (rss_...)"),
    force: bool = typer.Option(False, "--force", "-F", help="Delete without confirmation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Delete an RSS feed."""
    try:
        confirm_delete("external feed", feed_id, force)
        emit(get_client().delete_external_feed(feed_id), table, None, ["ok", "action", "id"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
