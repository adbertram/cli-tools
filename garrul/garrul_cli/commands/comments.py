"""Comment moderation, replies, and public thread reads."""

COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "approve": ["no_auth"],
    "spam": ["no_auth"],
    "delete": ["no_auth"],
    "restore": ["no_auth"],
    "bulk": ["no_auth"],
    "reply": ["no_auth"],
    "preview": ["browser_session"],
    "resolve-reports": ["no_auth"],
    "thread": ["no_auth"],
    "counts": ["no_auth"],
    "feed": ["no_auth"],
    "permalink": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filter_map import FilterMap
from cli_tools_shared.output import command, print_json

from ..client import BULK_LIMIT, get_client, segment

from ..helpers import emit_record, emit_rows, filter_fields, mutate, page_hint, scan_filter, selected, server_params, validated

app = typer.Typer(help="Moderate comments and read threads", no_args_is_help=True)

STATUSES = ("pending", "approved", "spam", "deleted", "all")
ACTIONS = ("approve", "spam", "delete", "restore")
COLUMNS = ["id", "status", "post_slug", "author_name", "created_at", "open_reports"]
# parent_id and body_md exist only on a comment's own page, so they cost one request per row.
DETAIL_FIELDS = {"parent_id", "body_md"}
FIELDS = [
    "id", "status", "post_slug", "post_title", "post_url", "host", "author_name", "author_user_id",
    "author_is_admin", "author_is_banned", "author_provider", "created_at", "score_up", "score_down",
    "open_reports", "comment_notes", "user_notes", "last_action", "body_html", "body_text", "parent_id", "body_md",
]

# Equality filters Garrul can apply itself, keyed by the CLI record field.
QUEUE_FILTERS = (
    FilterMap()
    .register_api_translator("status", lambda op, value: {"status": value} if op == "eq" and value in STATUSES else {})
    .register_api_translator("post_slug", lambda op, value: {"post_slug": value} if op == "eq" else {})
    .register_api_translator("author_user_id", lambda op, value: {"user_id": value} if op == "eq" else {})
    .register_api_translator("host", lambda op, value: {"host": value} if op == "eq" else {})
)


@app.command("list")
@command
def list_comments(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="pending, approved, spam, deleted or all (default: all)"),
    query: Optional[str] = typer.Option(None, "--q", "-q", help="Search comment bodies"),
    post_slug: Optional[str] = typer.Option(None, "--post-slug", help="Only this post slug"),
    user_id: Optional[str] = typer.Option(None, "--user-id", help="Only comments by this user id"),
    date_from: Optional[str] = typer.Option(None, "--from", help="Earliest day, YYYY-MM-DD (UTC)"),
    date_to: Optional[str] = typer.Option(None, "--to", help="Latest day, YYYY-MM-DD (UTC, inclusive)"),
    host: Optional[str] = typer.Option(None, "--host", help="Only comments posted on this site host"),
    reported: bool = typer.Option(False, "--reported", help="Only comments with open reader reports, any status"),
    before: Optional[str] = typer.Option(None, "--before", help="Cursor from a previous page"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of comments"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List the moderation queue, newest first."""
    if status is not None and status not in STATUSES:
        raise ClientError(f"Invalid --status {status!r}. Valid values: {', '.join(STATUSES)}.")
    filters = validated(filter, FIELDS)
    names = selected(properties, FIELDS)
    named = {"status": status, "q": query, "post_slug": post_slug, "user_id": user_id, "from": date_from, "to": date_to, "host": host}
    # Named options win over a translated --filter, which wins over the default.
    params = {"status": "all", **server_params(QUEUE_FILTERS, filters)}
    params.update({key: value for key, value in named.items() if value is not None})
    if reported:
        params["reported"] = "1"
    client = get_client()
    # A filter on parent_id/body_md can't be evaluated until add_comment_details runs below,
    # so it can't drive _pages' scan either; it stays a pure post-detail filter in emit_rows,
    # same as before this fix.
    scan = None if DETAIL_FIELDS & filter_fields(filters) else scan_filter(QUEUE_FILTERS, filters)
    result = client.list_comments(params, limit, before, post_filter=scan)
    page_hint(result, limit)
    rows = result["rows"]
    wanted = set(FIELDS) if names is None else {name.split(".")[0] for name in names}
    if DETAIL_FIELDS & (wanted | filter_fields(filters)):
        rows = client.add_comment_details(rows)
    emit_rows(rows, filters, limit, table, names, COLUMNS, "No comments match.")


@app.command("get")
@command
def get_comment(
    comment_id: str = typer.Argument(..., help="Comment id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one comment with its markdown source, parent, replies, reports and audit history."""
    emit_record(get_client().get_comment(comment_id), table, properties)


def _moderate(action: str, comment_id: str, reason: Optional[str], yes: bool, dry_run: bool) -> None:
    body = {"action": action, **({"reason": reason} if reason is not None else {})}
    mutate(
        f"{action} comment {comment_id}",
        {"method": "POST", "path": f"/admin/api/comments/{segment(comment_id)}", "body": body},
        yes,
        dry_run,
        lambda: get_client().moderate_comment(comment_id, action, reason),
    )


@app.command("approve")
@command
def approve_comment(
    comment_id: str = typer.Argument(..., help="Comment id"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason recorded in the audit log"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Approve a comment so it is published."""
    _moderate("approve", comment_id, reason, yes, dry_run)


@app.command("spam")
@command
def spam_comment(
    comment_id: str = typer.Argument(..., help="Comment id"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason recorded in the audit log"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Mark a comment as spam."""
    _moderate("spam", comment_id, reason, yes, dry_run)


@app.command("delete")
@command
def delete_comment(
    comment_id: str = typer.Argument(..., help="Comment id"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason recorded in the audit log"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Delete a comment. It stays restorable with `comments restore`."""
    _moderate("delete", comment_id, reason, yes, dry_run)


@app.command("restore")
@command
def restore_comment(
    comment_id: str = typer.Argument(..., help="Comment id"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason recorded in the audit log"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Restore a deleted or spam comment to approved."""
    _moderate("restore", comment_id, reason, yes, dry_run)


@app.command("bulk")
@command
def bulk_comments(
    action: str = typer.Argument(..., help="approve, spam, delete or restore"),
    comment_ids: List[str] = typer.Argument(..., help=f"Comment ids (at most {BULK_LIMIT})"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Apply one moderation action to up to 100 comments in a single request."""
    if action not in ACTIONS:
        raise ClientError(f"Invalid action {action!r}. Valid values: {', '.join(ACTIONS)}.")
    if len(comment_ids) > BULK_LIMIT:
        raise ClientError(f"Garrul accepts at most {BULK_LIMIT} ids per bulk request; got {len(comment_ids)}.")
    mutate(
        f"{action} {len(comment_ids)} comments",
        {"method": "POST", "path": "/admin/api/comments/bulk", "body": {"ids": comment_ids, "action": action}},
        yes,
        dry_run,
        lambda: get_client().bulk_moderate(comment_ids, action),
    )


@app.command("reply")
@command
def reply_to_comment(
    comment_id: str = typer.Argument(..., help="Comment id to answer"),
    body_md: str = typer.Option(..., "--body-md", "-b", help="Reply text in markdown"),
    notify: bool = typer.Option(True, "--notify/--no-notify", help="Email the thread's subscribers"),
    saved_reply_id: Optional[str] = typer.Option(None, "--saved-reply-id", help="Saved reply this text came from (audit only)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Post the reply"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Post a public reply as the signed-in moderator. It publishes immediately."""
    body = {"body_md": body_md, "notify": notify, **({"saved_reply_id": saved_reply_id} if saved_reply_id is not None else {})}
    mutate(
        f"reply to comment {comment_id}",
        {"method": "POST", "path": f"/admin/api/comments/{segment(comment_id)}/reply", "body": body},
        yes,
        dry_run,
        lambda: get_client().reply_to_comment(comment_id, body_md, notify, saved_reply_id),
    )


@app.command("preview")
@command
def preview_markdown(
    body_md: str = typer.Option(..., "--body-md", "-b", help="Markdown to render"),
):
    """Render markdown exactly as Garrul would store it. Nothing is saved."""
    print_json(get_client().preview_markdown(body_md))


@app.command("resolve-reports")
@command
def resolve_reports(
    comment_id: str = typer.Argument(..., help="Comment id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Dismiss every open reader report on a comment. The comment itself is unchanged."""
    mutate(
        f"resolve reports on comment {comment_id}",
        {"method": "POST", "path": f"/admin/api/comments/{segment(comment_id)}/reports/resolve", "body": {}},
        yes,
        dry_run,
        lambda: get_client().resolve_reports(comment_id),
    )


@app.command("thread")
@command
def get_thread(
    slug: str = typer.Argument(..., help="Post slug"),
    sort: Optional[str] = typer.Option(None, "--sort", help="new, top or old. Default: the instance setting"),
    before: Optional[str] = typer.Option(None, "--before", help="next_cursor from a previous page"),
):
    """Read a post's public comment tree, as the widget sees it (approved comments only)."""
    if sort is not None and sort not in ("new", "top", "old"):
        raise ClientError(f"Invalid --sort {sort!r}. Valid values: new, top, old.")
    print_json(get_client().get_thread(slug, sort, before))


@app.command("counts")
@command
def get_counts(
    slugs: List[str] = typer.Argument(..., help="One or more post slugs"),
    include: Optional[List[str]] = typer.Option(None, "--include", help="Also return votes and/or reactions"),
):
    """Get approved-comment counts for one or more post slugs."""
    extras = include or []
    for extra in extras:
        if extra not in ("votes", "reactions"):
            raise ClientError(f"Invalid --include {extra!r}. Valid values: votes, reactions.")
    print_json(get_client().get_counts(slugs, extras))


@app.command("feed")
@command
def get_feed(slug: str = typer.Argument(..., help="Post slug")):
    """Print the Atom feed of a post's latest approved comments."""
    typer.echo(get_client().get_feed(slug))


@app.command("permalink")
@command
def get_permalink(comment_id: str = typer.Argument(..., help="Comment id")):
    """Resolve a published comment's permalink to the page URL it lives on."""
    print_json(get_client().resolve_permalink(comment_id))
