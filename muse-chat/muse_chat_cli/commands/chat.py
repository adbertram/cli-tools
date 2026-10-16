"""Commands for main and existing Muse chats."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.output import command

from ..client import DEFAULT_TIMEOUT_SECONDS, get_client
from ..filters import filter_rows
from ._common import emit_monitor_result, render_record, render_rows


app = typer.Typer(help="Send, monitor, and inspect Muse chats", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "send": ["browser_session"],
    "monitor": ["browser_session"],
    "list": ["browser_session"],
    "get": ["browser_session"],
}


@app.command("send")
@command
def send(
    message: str = typer.Argument(..., help="Message to submit"),
    chat_id: Optional[str] = typer.Option(
        None,
        "--chat-id",
        help="Side-chat UUID; omit to send only to the main chat",
    ),
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
    """Submit one message to the main chat or an exact side-chat UUID."""
    client = get_client(profile=profile)
    try:
        result = client.send(
            message,
            chat_id=chat_id or "main",
            monitor=monitor,
            timeout=timeout,
        )
        if table:
            render_record(
                result,
                table=True,
                properties=None,
                default_columns=["status", "chat_id", "response"],
            )
        else:
            emit_monitor_result(result)
        if table and result.get("status") == "timeout":
            raise typer.Exit(1)
    finally:
        client.close()


@app.command("monitor")
@command
def monitor(
    chat_id: str = typer.Argument(..., help="Side-chat UUID or 'main'"),
    timeout: int = typer.Option(
        DEFAULT_TIMEOUT_SECONDS,
        "--timeout",
        min=1,
        help="Positive monitor timeout in seconds",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
):
    """Wait for the final response to the latest user turn in one chat."""
    client = get_client(profile=profile)
    try:
        result = client.monitor(chat_id, timeout=timeout)
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


@app.command("list")
@command
def list_chats(
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum chats"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results with field:op:value syntax",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
):
    """List the main chat and side chats with durable IDs."""
    client = get_client(profile=profile)
    try:
        rows = filter_rows(client.list_chats(limit=limit), filter)
        render_rows(
            rows,
            table=table,
            properties=properties,
            default_columns=["id", "title", "kind"],
        )
    finally:
        client.close()


@app.command("get")
@command
def get_chat(
    chat_id: str = typer.Argument(..., help="Side-chat UUID or 'main'"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Authentication profile"),
):
    """Get one chat and its current message history."""
    client = get_client(profile=profile)
    try:
        render_record(
            client.get_chat(chat_id),
            table=table,
            properties=properties,
            default_columns=["id", "url", "typing"],
        )
    finally:
        client.close()
