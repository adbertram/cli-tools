"""The moderation audit log."""

COMMAND_CREDENTIALS = {"list": ["browser_session"]}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filter_map import FilterMap
from cli_tools_shared.output import command

from ..client import get_client
from ..helpers import emit_rows, page_hint, scan_filter, selected, server_params, validated

app = typer.Typer(help="Read the moderation audit log", no_args_is_help=True)

TARGET_KINDS = ("comment", "user", "subscription", "system")
COLUMNS = ["created_at", "action", "admin_name", "target_kind", "target_id_prefix", "reason"]
FIELDS = [*COLUMNS, "target_id", "meta"]
AUDIT_FILTERS = (
    FilterMap()
    .register_api_translator("action", lambda op, value: {"action": value} if op == "eq" else {})
    .register_api_translator("target_kind", lambda op, value: {"target_kind": value} if op == "eq" else {})
)


@app.command("list")
@command
def list_audit(
    admin_id: Optional[str] = typer.Option(None, "--admin-id", help="Only actions by this moderator's user id"),
    action: Optional[str] = typer.Option(None, "--action", help="Only this action, for example approve or bulk.spam"),
    target_kind: Optional[str] = typer.Option(None, "--target-kind", help="comment, user, subscription or system"),
    target_id: Optional[str] = typer.Option(None, "--target-id", help="Only actions on this full target id"),
    date_from: Optional[str] = typer.Option(None, "--from", help="Earliest day, YYYY-MM-DD (UTC)"),
    date_to: Optional[str] = typer.Option(None, "--to", help="Latest day, YYYY-MM-DD (UTC, inclusive)"),
    host: Optional[str] = typer.Option(None, "--host", help="Only actions on comments from this site host"),
    before: Optional[str] = typer.Option(None, "--before", help="Cursor from a previous page"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of audit rows"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List audit rows, newest first. Garrul renders no row id, so there is no `audit get`."""
    if target_kind is not None and target_kind not in TARGET_KINDS:
        raise ClientError(f"Invalid --target-kind {target_kind!r}. Valid values: {', '.join(TARGET_KINDS)}.")
    filters = validated(filter, FIELDS)
    names = selected(properties, FIELDS)
    named = {
        "admin_id": admin_id,
        "action": action,
        "target_kind": target_kind,
        "target_id": target_id,
        "from": date_from,
        "to": date_to,
        "host": host,
    }
    params = server_params(AUDIT_FILTERS, filters)
    params.update({key: value for key, value in named.items() if value is not None})
    scan = scan_filter(AUDIT_FILTERS, filters)
    result = get_client().list_audit(params, limit, before, post_filter=scan)
    page_hint(result, limit)
    emit_rows(result["rows"], filters, limit, table, names, COLUMNS, "No audit rows.")
