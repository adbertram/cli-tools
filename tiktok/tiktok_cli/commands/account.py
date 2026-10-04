"""Read the current TikTok browser account identity."""
from typing import Optional

import typer
from cli_tools_shared.output import command, print_json, print_table

from ..client import TikTokWebClient

app = typer.Typer(help="Read verified current account identity")
COMMAND_CREDENTIALS = {"get": ["browser_session"]}


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
