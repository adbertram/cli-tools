"""Authentication commands for X CLI."""
from typing import Optional

import typer
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.output import command, print_json, print_table

from ..config import API_AUTH_TYPE, get_config


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="x",
)


@app.command("bearer-token")
@command
def save_bearer_token(
    profile: Optional[str] = typer.Option(None, "--profile", help="API auth profile; defaults to active API profile"),
    token_stdin: bool = typer.Option(False, "--stdin", help="Required: read bearer token from piped stdin"),
    table: bool = typer.Option(False, "--table", "-t", help="Display saved credential metadata as table"),
):
    """Save app bearer token in the secret manager for analytics usage/counts."""
    import sys

    if not token_stdin or sys.stdin.isatty():
        raise ValueError("Pipe the app bearer token to 'x auth bearer-token --stdin'; interactive prompting is handled by the shell.")
    config = get_config(profile=profile, profile_auth_type=API_AUTH_TYPE)
    token = sys.stdin.read().strip()
    if not token:
        raise ValueError("Bearer token must not be empty")
    config.save_credentials(X_BEARER_TOKEN=token)
    result = {"saved": True, "credential": "X_BEARER_TOKEN"}
    if table:
        print_table([result], ["saved", "credential"], ["Saved", "Credential"])
    else:
        print_json(result)
