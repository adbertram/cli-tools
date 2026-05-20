"""WordPress.com organization token commands."""

from __future__ import annotations

from typing import Optional

import typer

from cli_tools_shared.output import command, print_json, print_success

from ..config import get_config
from ..wpcom import acquire_wpcom_access_token, save_wpcom_credentials


app = typer.Typer(help="Manage WordPress.com organization access")
token_app = typer.Typer(
    help="Acquire and store the WordPress.com OAuth token used by Jetpack plugin updates."
)

COMMAND_CREDENTIALS = {
    "token": ["no_auth"],
}

app.add_typer(token_app, name="token", help="Manage the WordPress.com OAuth token")


@token_app.callback(invoke_without_command=True)
@command
def token(
    ctx: typer.Context,
    client_id: Optional[str] = typer.Option(None, "--client-id", help="WordPress.com OAuth client id"),
    client_secret: Optional[str] = typer.Option(None, "--client-secret", help="WordPress.com OAuth client secret"),
    username: Optional[str] = typer.Option(None, "--username", help="WordPress.com username"),
    password: Optional[str] = typer.Option(None, "--password", help="WordPress.com password"),
    site: Optional[str] = typer.Option(None, "--site", help="WordPress.com site identifier"),
) -> None:
    """Acquire and save a WordPress.com OAuth access token."""
    if ctx.invoked_subcommand is not None:
        return

    config = get_config()
    result = acquire_wpcom_access_token(
        config,
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
        site=site,
    )
    print_success(f"WordPress.com access token saved for {result['site']}")
    print_json(result)


@token_app.command("save-credential")
@command
def save_credential(
    client_id: Optional[str] = typer.Option(None, "--client-id", help="WordPress.com OAuth client id"),
    client_secret: Optional[str] = typer.Option(None, "--client-secret", help="WordPress.com OAuth client secret"),
    username: Optional[str] = typer.Option(None, "--username", help="WordPress.com username"),
    password: Optional[str] = typer.Option(None, "--password", help="WordPress.com password"),
    site: Optional[str] = typer.Option(None, "--site", help="WordPress.com site identifier"),
) -> None:
    """Save the WordPress.com credential bundle used to acquire Jetpack tokens."""
    config = get_config()
    result = save_wpcom_credentials(
        config,
        client_id=client_id,
        client_secret=client_secret,
        username=username,
        password=password,
        site=site,
    )
    print_success(f"WordPress.com credentials saved for {result['site']}")
    print_json(result)
