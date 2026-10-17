"""Commands for creating Muse side chats."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.output import command

from ..client import DEFAULT_TIMEOUT_SECONDS, get_client
from ._common import emit_monitor_result, render_record


app = typer.Typer(help="Create Muse side chats", no_args_is_help=True)

COMMAND_CREDENTIALS = {"create": ["browser_session"]}


@app.command("create")
@command
def create(
    message: str = typer.Argument(..., help="First message for the new side chat"),
    monitor: bool = typer.Option(False, "--monitor", help="Wait for the final response"),
    timeout: int = typer.Option(
        DEFAULT_TIMEOUT_SECONDS,
        "--timeout",
        min=1,
        help="Positive monitor timeout in seconds",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
):
    """Create a side chat, submit one message, and return its durable UUID."""
    client = get_client(profile=profile)
    try:
        result = client.create_side(message, monitor=monitor, timeout=timeout)
        if table:
            render_record(
                result,
                table=True,
                properties=None,
                default_columns=["status", "chat_id", "response"],
            )
            if result.get("status") == "timeout":
                raise typer.Exit(1)
        else:
            emit_monitor_result(result)
    finally:
        client.close()
