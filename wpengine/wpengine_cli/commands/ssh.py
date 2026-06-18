"""WP Engine SSH helper and SSH key commands."""

from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, confirm_destructive_action

from ..client import get_client
from ._render import render_list, render_record

app = typer.Typer(help="Build SSH connection details and manage SSH keys", no_args_is_help=True)
connection_app = typer.Typer(help="Build SSH connection details", no_args_is_help=True)
config_app = typer.Typer(help="Build OpenSSH config entries", no_args_is_help=True)
keys_app = typer.Typer(help="Manage WP Engine SSH keys", no_args_is_help=True)

DEFAULT_KEY_COLUMNS = ["id", "uuid", "fingerprint", "comment", "created_at"]
TEMPLATE_ENVIRONMENT = "ENVIRONMENT_NAME"


def _apply_template_filters(rows: list[dict[str, object]], filters: Optional[list[str]]) -> list[dict[str, object]]:
    if not filters:
        return rows
    return apply_filters(rows, filters)


def _ssh_host(environment_name: str) -> str:
    return f"{environment_name}.ssh.wpengine.net"


def build_ssh_connection(environment_name: str) -> dict[str, object]:
    """Build documented SSH connection details for a WP Engine environment."""
    host = _ssh_host(environment_name)
    user = environment_name
    return {
        "id": environment_name,
        "name": environment_name,
        "environment_name": environment_name,
        "host": host,
        "remote_host": host,
        "user": user,
        "port": 22,
        "remote_root": f"/sites/{environment_name}",
        "command": f"ssh {user}@{host}",
    }


def build_ssh_config(environment_name: str) -> dict[str, object]:
    """Build a documented OpenSSH config entry for a WP Engine environment."""
    connection = build_ssh_connection(environment_name)
    alias = f"{environment_name}-wpengine"
    config = "\n".join(
        [
            f"Host {alias}",
            f"  HostName {connection['host']}",
            f"  User {connection['user']}",
            f"  Port {connection['port']}",
            "  ForwardAgent yes",
        ]
    )
    return {**connection, "alias": alias, "config": config}


@connection_app.command("list")
@command
def ssh_connection_list(
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
    """List documented SSH connection template rows."""
    rows = _apply_template_filters([build_ssh_connection(TEMPLATE_ENVIRONMENT)], filter)[:limit]
    render_list(rows, table=table, properties=properties, default_columns=["id", "host", "user", "port"])


@connection_app.command("get")
@command
def ssh_connection_get(
    environment_name: str = typer.Argument(..., help="WP Engine environment name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Return documented SSH host, user, and remote path details."""
    render_record(
        build_ssh_connection(environment_name),
        table=table,
        properties=properties,
        default_columns=["host", "user", "port", "remote_root"],
    )


@config_app.command("list")
@command
def ssh_config_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of config templates to return"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """List documented OpenSSH config template rows."""
    rows = _apply_template_filters([build_ssh_config(TEMPLATE_ENVIRONMENT)], filter)[:limit]
    render_list(rows, table=table, properties=properties, default_columns=["id", "alias", "host", "user", "port"])


@config_app.command("get")
@command
def ssh_config_get(
    environment_name: str = typer.Argument(..., help="WP Engine environment name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Return an OpenSSH config entry for a WP Engine environment."""
    render_record(
        build_ssh_config(environment_name),
        table=table,
        properties=properties,
        default_columns=["alias", "host", "user", "port"],
    )


@keys_app.command("list")
@command
def ssh_keys_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of SSH keys to return"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (for example, comment:contains:laptop)",
    ),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """List SSH keys attached to the authenticated WP Engine user."""
    keys = get_client().list_ssh_keys(limit=limit, filters=filter)
    render_list(keys, table=table, properties=properties, default_columns=DEFAULT_KEY_COLUMNS)


@keys_app.command("get")
@command
def ssh_keys_get(
    ssh_key_id: str = typer.Argument(..., help="WP Engine SSH key ID or UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Get one SSH key attached to the authenticated WP Engine user."""
    key = get_client().get_ssh_key(ssh_key_id)
    render_record(key, table=table, properties=properties)


@keys_app.command("add")
@command
def ssh_keys_add(
    public_key: str = typer.Argument(..., help="SSH public key text"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Add an SSH public key to WP Engine."""
    key = get_client().add_ssh_key(public_key)
    render_record(key, table=table, properties=properties)


@keys_app.command("delete")
@command
def ssh_keys_delete(
    ssh_key_id: str = typer.Argument(..., help="WP Engine SSH key ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Delete without interactive confirmation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
) -> None:
    """Delete an SSH key from WP Engine."""
    confirm_destructive_action(
        f"Delete WP Engine SSH key {ssh_key_id}?",
        assume_yes=yes,
        action_description=f"delete WP Engine SSH key {ssh_key_id}",
    )
    result = get_client().delete_ssh_key(ssh_key_id)
    render_record(
        result,
        table=table,
        properties=properties,
        default_columns=["deleted", "ssh_key_id"],
    )


app.add_typer(connection_app, name="connection", help="Build SSH connection details")
app.add_typer(config_app, name="config", help="Build OpenSSH config entries")
app.add_typer(keys_app, name="keys", help="Manage WP Engine SSH keys")

COMMAND_CREDENTIALS = {
    "connection": ["no_auth"],
    "config": ["no_auth"],
    "keys": ["username_password"],
}
