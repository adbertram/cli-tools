"""Open and close comment threads."""

COMMAND_CREDENTIALS = {"close": ["no_auth"], "open": ["no_auth"]}

import typer
from cli_tools_shared.output import command

from ..client import get_client
from ..helpers import mutate

app = typer.Typer(help="Open or close a post's comment thread", no_args_is_help=True)


def _set_closed(slug: str, closed: bool, yes: bool, dry_run: bool) -> None:
    mutate(
        f"{'close' if closed else 'open'} comments on {slug}",
        {"method": "POST", "path": "/admin/api/posts/close", "body": {"slug": slug, "closed": closed}},
        yes,
        dry_run,
        lambda: get_client().set_post_closed(slug, closed),
    )


@app.command("close")
@command
def close_post(
    slug: str = typer.Argument(..., help="Post slug"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Stop a post from accepting new comments. Works before the first comment arrives."""
    _set_closed(slug, True, yes, dry_run)


@app.command("open")
@command
def open_post(
    slug: str = typer.Argument(..., help="Post slug"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Let a closed post accept comments again."""
    _set_closed(slug, False, yes, dry_run)
