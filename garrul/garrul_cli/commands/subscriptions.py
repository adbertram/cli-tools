"""Email subscriptions to comment threads."""

COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "unsubscribe": ["no_auth"],
    "resend": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filter_map import FilterMap
from cli_tools_shared.output import command

from ..client import get_client, segment
from ..helpers import emit_record, emit_rows, mutate, page_hint, scan_filter, selected, server_params, validated

app = typer.Typer(help="Manage email subscriptions", no_args_is_help=True)

TRI_STATE = ("yes", "no")
COLUMNS = ["id", "status", "email", "post_slug", "created_at", "last_notified_at"]
SUBSCRIPTION_FILTERS = FilterMap().register_api_translator(
    "post_slug", lambda op, value: {"post_slug": value} if op == "eq" else {}
)


def _tri_state(name: str, value: Optional[str]) -> None:
    if value is not None and value not in TRI_STATE:
        raise ClientError(f"Invalid --{name} {value!r}. Valid values: yes, no.")


@app.command("list")
@command
def list_subscriptions(
    query: Optional[str] = typer.Option(None, "--q", "-q", help="Search by email address"),
    post_slug: Optional[str] = typer.Option(None, "--post-slug", help="Only this post slug"),
    confirmed: Optional[str] = typer.Option(None, "--confirmed", help="yes or no"),
    unsubscribed: Optional[str] = typer.Option(None, "--unsubscribed", help="yes or no"),
    host: Optional[str] = typer.Option(None, "--host", help="Only threads on this site host"),
    before: Optional[str] = typer.Option(None, "--before", help="Cursor from a previous page"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of subscriptions"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List subscriptions, newest first. Unsubscribed rows have no id (Garrul does not render one)."""
    _tri_state("confirmed", confirmed)
    _tri_state("unsubscribed", unsubscribed)
    filters = validated(filter, COLUMNS)
    names = selected(properties, COLUMNS)
    named = {"q": query, "post_slug": post_slug, "confirmed": confirmed, "unsubscribed": unsubscribed, "host": host}
    params = server_params(SUBSCRIPTION_FILTERS, filters)
    params.update({key: value for key, value in named.items() if value is not None})
    scan = scan_filter(SUBSCRIPTION_FILTERS, filters)
    result = get_client().list_subscriptions(params, limit, before, post_filter=scan)
    page_hint(result, limit)
    emit_rows(result["rows"], filters, limit, table, names, COLUMNS, "No subscriptions match.")


@app.command("get")
@command
def get_subscription(
    subscription_id: str = typer.Argument(..., help="Subscription id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one active subscription.

    Garrul has no single-subscription read, so this walks the active list until
    the id appears. Unsubscribed rows carry no id and cannot be fetched this way.
    """
    before = None
    while True:
        result = get_client().list_subscriptions({"unsubscribed": "no"}, 50, before)
        for row in result["rows"]:
            if row["id"] == subscription_id:
                emit_record(row, table, properties)
                return
        before = result["next_before"]
        if before is None:
            raise ClientError(f"No active subscription has id {subscription_id}.")


def _act(subscription_id: str, action: str, reason: Optional[str], yes: bool, dry_run: bool) -> None:
    body = {"action": action, **({"reason": reason} if reason is not None else {})}
    mutate(
        f"{action} subscription {subscription_id}",
        {"method": "POST", "path": f"/admin/api/subscriptions/{segment(subscription_id)}", "body": body},
        yes,
        dry_run,
        lambda: get_client().act_on_subscription(subscription_id, action, reason),
    )


@app.command("unsubscribe")
@command
def unsubscribe(
    subscription_id: str = typer.Argument(..., help="Subscription id"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason recorded in the audit log"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Stop emailing a subscriber about a thread."""
    _act(subscription_id, "unsubscribe", reason, yes, dry_run)


@app.command("resend")
@command
def resend_confirmation(
    subscription_id: str = typer.Argument(..., help="Subscription id"),
    reason: Optional[str] = typer.Option(None, "--reason", help="Reason recorded in the audit log"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Send the email"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Email a fresh confirmation link to a subscriber who has not confirmed yet."""
    _act(subscription_id, "resend", reason, yes, dry_run)
