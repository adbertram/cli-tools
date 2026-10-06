"""Read the current TikTok browser account identity."""
from typing import List, Optional

import typer
from cli_tools_shared.output import command, print_json, print_table

from ..client import TikTokWebClient

app = typer.Typer(help="Read verified current account identity")
COMMAND_CREDENTIALS = {"get": ["browser_session"], "check": ["browser_session"]}


@app.command("get")
@command
def account_get(
    expected_username: Optional[str] = typer.Option(None, "--expected-username", help="Fail unless the current username matches this handle"),
    expected_account_id: Optional[str] = typer.Option(None, "--expected-account-id", help="Fail unless the current numeric account ID matches exactly"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get the authenticated account ID and username from TikTok's account endpoint.

    Numeric account IDs remain strings to preserve 64-bit precision. Optional
    expected-identity guards fail before returning data if the session differs.
    """
    client = TikTokWebClient()
    try:
        result = client.get_account(expected_username=expected_username, expected_account_id=expected_account_id)
    finally:
        client.close()
    if table:
        columns = ["profile", "account_id", "username", "observed_at"]
        print_table([result], columns, columns)
    else:
        print_json(result)


@app.command("check")
@command
def account_check(
    username: str = typer.Option(..., "--username", "-u", help="Exact session owner handle"),
    expected_account_id: Optional[str] = typer.Option(None, "--expected-account-id", help="Fail unless the current numeric account ID matches exactly"),
    limit: int = typer.Option(20, "--limit", "-l", help="Most recent posts to check"),
    video_id: Optional[List[str]] = typer.Option(None, "--video-id", help="Also check this post ID, even if Studio no longer lists it (repeatable)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display posts as table"),
):
    """Report each recent post's For You eligibility, restriction reason, and appeal state.

    Read-only. Unreadable values stay null. TikTok web has no Account check
    page, so account standing is always null; per-post penalties are real.
    """
    client = TikTokWebClient()
    try:
        result = client.check_account(username, limit=limit, expected_account_id=expected_account_id, video_ids=video_id)
    finally:
        client.close()
    if table:
        rows = [{**post, "reason": "; ".join(reason["title"] or f"code {reason['code']}" for reason in post["reasons"])}
                for post in result["posts"]]
        columns = ["id", "eligibility", "reason", "appeal_status", "in_studio_feed", "posted_at"]
        print_table(rows, columns, columns)
    else:
        print_json(result)
