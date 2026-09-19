"""User accounts: bans, roles, sessions, and personal-data requests."""

COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "ban": ["no_auth"],
    "unban": ["no_auth"],
    "revoke-sessions": ["no_auth"],
    "export": ["browser_session"],
    "erase": ["no_auth"],
    "role": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command, print_json

from ..client import get_client, segment
from ..helpers import emit_record, emit_rows, mutate, page_hint, scan_filter, selected, validated

app = typer.Typer(help="Manage commenter accounts", no_args_is_help=True)

ROLES = ("user", "mod", "admin")
COLUMNS = ["id", "name", "email", "provider", "is_banned", "joined_on"]


@app.command("list")
@command
def list_users(
    query: Optional[str] = typer.Option(None, "--q", "-q", help="Search by display name"),
    before: Optional[str] = typer.Option(None, "--before", help="Cursor from a previous page"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of users"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List users, newest first."""
    filters = validated(filter, COLUMNS)
    names = selected(properties, COLUMNS)
    # Garrul has no query parameter for any user field, so a --filter is always client-side.
    scan = scan_filter(None, filters)
    result = get_client().list_users(query, limit, before, post_filter=scan)
    page_hint(result, limit)
    emit_rows(result["rows"], filters, limit, table, names, COLUMNS, "No users match.")


@app.command("get")
@command
def get_user(
    user_id: str = typer.Argument(..., help="User id"),
    before: Optional[str] = typer.Option(None, "--before", help="comments_next_before from a previous call"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one user with role, ban state, notes, audit history and their latest 50 comments."""
    emit_record(get_client().get_user(user_id, before), table, properties)


def _set_banned(user_id: str, banned: bool, reason: Optional[str], from_comment: Optional[str], yes: bool, dry_run: bool) -> None:
    body = {"banned": banned}
    if reason is not None:
        body["reason"] = reason
    if from_comment is not None:
        body["from_comment"] = from_comment
    mutate(
        f"{'ban' if banned else 'unban'} user {user_id}",
        {"method": "POST", "path": f"/admin/api/users/{segment(user_id)}", "body": body},
        yes,
        dry_run,
        lambda: get_client().set_user_banned(user_id, banned, reason, from_comment),
    )


@app.command("ban")
@command
def ban_user(
    user_id: str = typer.Argument(..., help="User id"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason recorded in the audit log"),
    from_comment: Optional[str] = typer.Option(None, "--from-comment", help="Comment id that prompted the ban (audit only)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Ban a user. For an anonymous author this blocks their hashed IP."""
    _set_banned(user_id, True, reason, from_comment, yes, dry_run)


@app.command("unban")
@command
def unban_user(
    user_id: str = typer.Argument(..., help="User id"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason recorded in the audit log"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Lift a ban."""
    _set_banned(user_id, False, reason, None, yes, dry_run)


@app.command("revoke-sessions")
@command
def revoke_sessions(
    user_id: str = typer.Argument(..., help="User id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Sign a user out everywhere. Aimed at your own id, it also ends this CLI's session."""
    mutate(
        f"revoke every session of user {user_id}",
        {"method": "POST", "path": f"/admin/api/users/{segment(user_id)}/revoke-sessions", "body": {}},
        yes,
        dry_run,
        lambda: get_client().revoke_user_sessions(user_id),
    )


@app.command("export")
@command
def export_user(user_id: str = typer.Argument(..., help="User id")):
    """Print everything the instance holds about a user (GDPR access request). Writes an audit row."""
    print_json(get_client().export_user(user_id))


@app.command("erase")
@command
def erase_user(
    user_id: str = typer.Argument(..., help="User id"),
    redact_bodies: bool = typer.Option(False, "--redact-bodies", help="Also blank their comment text and mark it deleted"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason recorded in the audit log"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Erase the data. This cannot be undone"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Irreversibly erase a user's personal data (GDPR erasure request)."""
    body = {"confirm": "ERASE", "redact_bodies": redact_bodies, **({"reason": reason} if reason is not None else {})}
    mutate(
        f"erase the personal data of user {user_id}",
        {"method": "POST", "path": f"/admin/api/users/{segment(user_id)}/erase", "body": body},
        yes,
        dry_run,
        lambda: get_client().erase_user(user_id, redact_bodies, reason),
    )


@app.command("role")
@command
def set_role(
    user_id: str = typer.Argument(..., help="User id"),
    role: str = typer.Argument(..., help="user, mod or admin"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason recorded in the audit log"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Change a user's role. Garrul refuses to change your own role or remove the last admin."""
    if role not in ROLES:
        raise ClientError(f"Invalid role {role!r}. Valid values: {', '.join(ROLES)}.")
    body = {"role": role, **({"reason": reason} if reason is not None else {})}
    mutate(
        f"set user {user_id} to role {role}",
        {"method": "POST", "path": f"/admin/api/users/{segment(user_id)}/role", "body": body},
        yes,
        dry_run,
        lambda: get_client().set_user_role(user_id, role, reason),
    )
