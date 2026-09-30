"""Command surface for the official ntfy wrapper."""

import sys
from typing import Optional

import typer
from cli_tools_shared import ClientError, apply_filters, apply_limit, apply_properties_filter, create_app, run_app
from cli_tools_shared.output import command, confirm_destructive_action, print_json, print_table

from . import __version__
from .client import get_client
from .commands.auth import app as auth_app
from .commands.common import usage_error
from .commands.messages import app as messages_app
from .parsers import parse_server_table

app = create_app(name="ntfy", help="Structured wrapper for the official ntfy CLI", version=__version__, cache_support=False)
server = typer.Typer(help="Administer a local ntfy server when upstream supports it", no_args_is_help=True)
users = typer.Typer(help="Manage local server users", no_args_is_help=True)
password = typer.Typer(help="Manage user passwords", no_args_is_help=True)
role = typer.Typer(help="Manage user roles", no_args_is_help=True)
access = typer.Typer(help="Manage local server access rules", no_args_is_help=True)
tokens = typer.Typer(help="Manage local server tokens", no_args_is_help=True)


def _server(args: list[str], *, destructive: bool = False, force: bool = False, resource: Optional[str] = None, table: bool = False, limit: int = 100, filter: Optional[list[str]] = None, properties: Optional[str] = None, stdin: Optional[str] = None) -> None:
    if destructive:
        confirm_destructive_action(
            "Apply this ntfy server change?",
            assume_yes=force,
            action_description="modify ntfy server state",
            skip_flag_hint="--force",
        )
    client = get_client()
    client.require_server()
    result = client.run(args, stdin=stdin)
    if resource:
        from .client import SERVER_TABLE_SCHEMA
        rows = apply_limit(parse_server_table(result.stdout, SERVER_TABLE_SCHEMA[resource]), limit)
        rows = apply_filters(rows, filter)
        rows = apply_properties_filter(rows, properties)
        if table:
            output_columns = list(rows[0]) if rows else list(SERVER_TABLE_SCHEMA[resource])
            print_table(rows, output_columns, [item.title() for item in output_columns])
        else:
            print_json(rows)
    elif result.stdout:
        sys.stdout.write(result.stdout)


@server.command("serve", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
@command
def serve(ctx: typer.Context) -> None:
    """Run upstream ntfy server in the foreground."""
    raise typer.Exit(get_client().passthrough(["serve", *ctx.args]))


@users.command("list")
@command
def users_list(limit: int = typer.Option(100, "--limit", "-l"), filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"), properties: Optional[str] = typer.Option(None, "--properties", "-p"), table: bool = typer.Option(False, "--table", "-t")) -> None: _server(["user", "list"], resource="users", limit=limit, filter=filter, properties=properties, table=table)
@users.command("get")
@command
def users_get(username: str, table: bool = typer.Option(False, "--table", "-t")) -> None: _server(["user", "list", username], resource="users", table=table)
@users.command("create")
@command
def users_create(username: str, role: Optional[str] = typer.Option(None, "--role")) -> None:
    args = ["user", "add"] + (["--role", role] if role else []) + [username]; _server(args)
@users.command("delete")
@command
def users_delete(username: str, force: bool = typer.Option(False, "--force", "-F")) -> None: _server(["user", "del", username], destructive=True, force=force)
@password.command("update")
@command
def password_update(username: str, password_stdin: bool = typer.Option(False, "--password-stdin", help="Read replacement password from stdin")) -> None:
    secret = sys.stdin.read() if password_stdin else None
    if password_stdin and not secret:
        usage_error("stdin password is empty")
    _server(["user", "change-pass", username], stdin=secret)
@role.command("update")
@command
def role_update(username: str, value: str) -> None: _server(["user", "change-role", username, value])

@access.command("list")
@command
def access_list(limit: int = typer.Option(100, "--limit", "-l"), filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"), properties: Optional[str] = typer.Option(None, "--properties", "-p"), table: bool = typer.Option(False, "--table", "-t")) -> None: _server(["access"], resource="access", limit=limit, filter=filter, properties=properties, table=table)
@access.command("get")
@command
def access_get(username: str, table: bool = typer.Option(False, "--table", "-t")) -> None: _server(["access", username], resource="access", table=table)
@access.command("set")
@command
def access_set(username: str, topic: str, permission: str, force: bool = typer.Option(False, "--force", "-F")) -> None: _server(["access", username, topic, permission], destructive=True, force=force)
@access.command("reset")
@command
def access_reset(username: Optional[str] = None, topic: Optional[str] = None, force: bool = typer.Option(False, "--force", "-F")) -> None: _server(["access", "--reset", *([username] if username else []), *([topic] if topic else [])], destructive=True, force=force)

@tokens.command("list")
@command
def tokens_list(username: Optional[str] = None, limit: int = typer.Option(100, "--limit", "-l"), filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"), properties: Optional[str] = typer.Option(None, "--properties", "-p"), table: bool = typer.Option(False, "--table", "-t")) -> None: _server(["token", "list", *([username] if username else [])], resource="tokens", limit=limit, filter=filter, properties=properties, table=table)
@tokens.command("get")
@command
def tokens_get(username: str, table: bool = typer.Option(False, "--table", "-t")) -> None: _server(["token", "list", username], resource="tokens", table=table)
@tokens.command("create")
@command
def tokens_create(username: str, expires: Optional[str] = typer.Option(None, "--expires"), label: Optional[str] = typer.Option(None, "--label"), force: bool = typer.Option(False, "--force", "-F")) -> None: _server(["token", "add", *(["--expires", expires] if expires else []), *(["--label", label] if label else []), username], destructive=True, force=force)
@tokens.command("delete")
@command
def tokens_delete(username: str, token: str, force: bool = typer.Option(False, "--force", "-F")) -> None: _server(["token", "remove", username, token], destructive=True, force=force)
@tokens.command("generate")
@command
def tokens_generate() -> None: _server(["token", "generate"])

users.add_typer(password, name="password")
users.add_typer(role, name="role")
server.add_typer(users, name="users")
server.add_typer(access, name="access")
server.add_typer(tokens, name="tokens")
app.add_typer(auth_app, name="auth")
app.add_typer(messages_app, name="messages")
app.add_typer(server, name="server")


@app.command("upstream", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
@command
def upstream(ctx: typer.Context) -> None:
    """Pass arguments to ntfy unchanged, preserving stdout, stderr, and exit code."""
    raise typer.Exit(get_client().passthrough(ctx.args))


def main() -> None:
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
