"""WP Engine SFTP helper commands."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command

from ._render import render_list, render_record

app = typer.Typer(help="Build SFTP connection details", no_args_is_help=True)
connection_app = typer.Typer(help="Build SFTP connection details", no_args_is_help=True)
TEMPLATE_ENVIRONMENT = "ENVIRONMENT_NAME"


def _sftp_user(environment_name: str, username: Optional[str]) -> Optional[str]:
    if not username:
        return None
    if username.startswith(f"{environment_name}-"):
        return username
    return f"{environment_name}-{username}"


def build_sftp_connection(environment_name: str, username: Optional[str] = None) -> dict[str, object]:
    """Build documented SFTP host and username details for a WP Engine environment."""
    host = f"{environment_name}.sftp.wpengine.com"
    user = _sftp_user(environment_name, username)
    command_user = user or f"{environment_name}-<username>"
    return {
        "id": environment_name,
        "name": environment_name,
        "environment_name": environment_name,
        "host": host,
        "remote_host": host,
        "port": 2222,
        "protocol": "sftp",
        "user": user,
        "username_pattern": f"{environment_name}-<username>",
        "command": f"sftp -P 2222 {command_user}@{host}",
        "password_source": "WP Engine User Portal SFTP user",
    }


@connection_app.command("list")
@command
def sftp_connection_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of connection templates to return"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """List documented SFTP connection template rows."""
    rows = [build_sftp_connection(TEMPLATE_ENVIRONMENT)]
    if filter:
        rows = apply_filters(rows, filter)
    render_list(rows[:limit], table=table, properties=properties, default_columns=["id", "host", "port", "user"])


@connection_app.command("get")
@command
def sftp_connection_get(
    environment_name: str = typer.Argument(..., help="WP Engine environment name"),
    username: Optional[str] = typer.Option(
        None,
        "--username",
        "-u",
        help="WP Engine SFTP username suffix or full environment-prefixed username",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Return documented SFTP host, port, username pattern, and command details."""
    render_record(
        build_sftp_connection(environment_name, username),
        table=table,
        properties=properties,
        default_columns=["host", "port", "user", "username_pattern"],
    )


app.add_typer(connection_app, name="connection", help="Build SFTP connection details")

COMMAND_CREDENTIALS = {
    "connection": ["no_auth"],
}
