"""Theme commands for WordPress CLI."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters, apply_limit
from cli_tools_shared.output import handle_error, print_json, print_table

from ..theme_files import push_theme_file
from . import extract_fields


app = typer.Typer(help="Manage WordPress themes", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "list": ["username_password"],
    "get": ["username_password"],
    "file-push": ["no_auth"],
}


def get_client():
    from ..client import get_client as _get_client

    return _get_client()


@app.command("list")
def themes_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of themes to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
) -> None:
    """List installed WordPress themes."""
    try:
        themes = get_client().list_themes()
        if status:
            themes = [theme for theme in themes if theme.get("status") == status]
        if filter:
            themes = apply_filters(themes, filter)
        themes = apply_limit(themes, limit)
        if properties:
            fields = [field.strip() for field in properties.split(",")]
            themes = extract_fields(themes, fields)

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",")]
                print_table(themes, fields, fields)
            else:
                print_table(
                    themes,
                    ["theme", "name", "version", "status"],
                    ["Theme", "Name", "Version", "Status"],
                )
        else:
            print_json(themes)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def themes_get(
    theme: str = typer.Argument(..., help="Theme stylesheet, textdomain, or exact name from themes list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
) -> None:
    """Get details for a specific WordPress theme."""
    try:
        result = get_client().get_theme(theme)
        if properties:
            fields = [field.strip() for field in properties.split(",")]
            result = extract_fields([result], fields)[0]

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",")]
                print_table([result], fields, fields)
            else:
                rows = [{"field": key, "value": str(value)} for key, value in result.items() if value is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("file-push")
def themes_file_push(
    theme: str = typer.Argument(..., help="Theme directory name under wp-content/themes"),
    local_file: Path = typer.Argument(..., help="Local file to upload"),
    remote_file: str = typer.Argument(..., help="Relative destination path inside the theme"),
    remote_root: str = typer.Option(..., "--remote-root", help="Absolute remote WordPress root path"),
    host: str = typer.Option(..., "--host", help="SSH host"),
    user: Optional[str] = typer.Option(None, "--user", help="SSH user"),
    port: int = typer.Option(22, "--port", help="SSH port"),
    identity_file: Optional[Path] = typer.Option(None, "--identity-file", help="SSH identity file"),
    backup: bool = typer.Option(False, "--backup", help="Back up the existing remote file before overwrite"),
    yes: bool = typer.Option(False, "--yes", help="Upload and overwrite the remote file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show readback without uploading"),
) -> None:
    """Push a local file to a remote WordPress theme through SSH."""
    try:
        result = push_theme_file(
            theme=theme,
            local_file=local_file,
            remote_file=remote_file,
            remote_root=remote_root,
            host=host,
            user=user,
            port=port,
            identity_file=identity_file,
            backup=backup,
            yes=yes,
            dry_run=dry_run,
        )
        print_json(result)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
