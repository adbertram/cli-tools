"""Pre-written moderator replies."""

COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "create": ["no_auth"],
    "update": ["no_auth"],
    "delete": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command

from ..client import get_client, segment
from ..helpers import emit_record, emit_rows, mutate, selected, validated

app = typer.Typer(help="Manage saved replies", no_args_is_help=True)

SCOPES = ("private", "shared")
COLUMNS = ["id", "title", "scope", "owner_id"]
FIELDS = [*COLUMNS, "body_md"]


def _fields(title: str, body_md: str, scope: str) -> dict:
    if scope not in SCOPES:
        raise ClientError(f"Invalid --scope {scope!r}. Valid values: {', '.join(SCOPES)}.")
    return {"title": title, "body_md": body_md, "scope": scope}


@app.command("list")
@command
def list_saved_replies(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of saved replies"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List your saved replies plus every shared one. Garrul returns them all in one response."""
    filters = validated(filter, FIELDS)
    names = selected(properties, FIELDS)
    emit_rows(get_client().list_saved_replies(), filters, limit, table, names, COLUMNS, "No saved replies yet.")


@app.command("get")
@command
def get_saved_reply(
    reply_id: str = typer.Argument(..., help="Saved reply id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one saved reply."""
    emit_record(get_client().get_saved_reply(reply_id), table, properties)


@app.command("create")
@command
def create_saved_reply(
    title: str = typer.Option(..., "--title", help="Title, at most 120 characters"),
    body_md: str = typer.Option(..., "--body-md", "-b", help="Reply text in markdown, at most 8000 characters"),
    scope: str = typer.Option(..., "--scope", help="private (only you) or shared (every moderator)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Create the saved reply"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Create a saved reply."""
    fields = _fields(title, body_md, scope)
    mutate(
        "create a saved reply",
        {"method": "POST", "path": "/admin/api/saved-replies", "body": fields},
        yes,
        dry_run,
        lambda: get_client().create_saved_reply(fields),
    )


@app.command("update")
@command
def update_saved_reply(
    reply_id: str = typer.Argument(..., help="Saved reply id"),
    title: str = typer.Option(..., "--title", help="Title, at most 120 characters"),
    body_md: str = typer.Option(..., "--body-md", "-b", help="Reply text in markdown, at most 8000 characters"),
    scope: str = typer.Option(..., "--scope", help="private or shared"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Replace a saved reply you own. Garrul requires all three fields on every update."""
    fields = _fields(title, body_md, scope)
    mutate(
        f"update saved reply {reply_id}",
        {"method": "PATCH", "path": f"/admin/api/saved-replies/{segment(reply_id)}", "body": fields},
        yes,
        dry_run,
        lambda: get_client().update_saved_reply(reply_id, fields),
    )


@app.command("delete")
@command
def delete_saved_reply(
    reply_id: str = typer.Argument(..., help="Saved reply id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Delete the saved reply. This cannot be undone"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Permanently delete a saved reply you own."""
    mutate(
        f"delete saved reply {reply_id}",
        {"method": "DELETE", "path": f"/admin/api/saved-replies/{segment(reply_id)}"},
        yes,
        dry_run,
        lambda: get_client().delete_saved_reply(reply_id),
    )
