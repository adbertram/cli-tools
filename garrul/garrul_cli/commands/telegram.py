"""Link the signed-in admin's Telegram account."""

COMMAND_CREDENTIALS = {
    "status": ["browser_session"],
    "link": ["no_auth"],
    "unlink": ["no_auth"],
    "digest": ["no_auth"],
}

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command, print_json

from ..client import get_client
from ..helpers import mutate

app = typer.Typer(help="Manage your Telegram operator link", no_args_is_help=True)


@app.command("status")
@command
def telegram_status():
    """Show bot configuration and whether your account is linked."""
    print_json(get_client().get_telegram())


@app.command("link")
@command
def telegram_link(
    yes: bool = typer.Option(False, "--yes", "-y", help="Issue the code"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Issue a one-time link code. Send `/start <code>` to the bot within 10 minutes."""
    mutate(
        "issue a Telegram link code",
        {"method": "POST", "path": "/admin/api/telegram/link", "body": {}},
        yes,
        dry_run,
        lambda: get_client().create_telegram_link_code(),
    )


@app.command("unlink")
@command
def telegram_unlink(
    yes: bool = typer.Option(False, "--yes", "-y", help="Remove the link"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Unlink your Telegram account."""
    mutate(
        "unlink the Telegram account",
        {"method": "DELETE", "path": "/admin/api/telegram/link"},
        yes,
        dry_run,
        lambda: get_client().delete_telegram_link(),
    )


@app.command("digest")
@command
def telegram_digest(
    state: str = typer.Argument(..., help="on or off"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Turn the daily operator digest on or off for your linked account."""
    if state not in ("on", "off"):
        raise ClientError(f"Invalid state {state!r}. Valid values: on, off.")
    mutate(
        f"turn the Telegram digest {state}",
        {"method": "POST", "path": "/admin/api/telegram/digest", "body": {"digest": state == "on"}},
        yes,
        dry_run,
        lambda: get_client().set_telegram_digest(state == "on"),
    )
