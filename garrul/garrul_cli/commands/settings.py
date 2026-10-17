"""Runtime settings overrides."""

COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "update": ["no_auth"],
    "reset": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command

from ..client import get_client
import re

from ..helpers import emit_record, emit_rows, mutate, selected, validated

app = typer.Typer(help="Read and change runtime settings", no_args_is_help=True)

COLUMNS = ["key", "group", "value"]
BOOLEANS = {"true": True, "false": False}


def _pairs(option: str, items: Optional[List[str]]) -> dict:
    pairs = {}
    for item in items or []:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise ClientError(f"{option} expects key=value, got {item!r}.")
        if key in pairs:
            raise ClientError(f"{option} names {key} twice.")
        pairs[key] = value
    return pairs


@app.command("list")
@command
def list_settings(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of settings"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List every runtime setting with its resolved value. Garrul renders them all on one page."""
    filters = validated(filter, COLUMNS)
    names = selected(properties, COLUMNS)
    emit_rows(get_client().list_settings(), filters, limit, table, names, COLUMNS, "No settings found.")


@app.command("get")
@command
def get_setting(
    key: str = typer.Argument(..., help="Setting key, for example comments_enabled"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one runtime setting."""
    for row in get_client().list_settings():
        if row["key"] == key:
            emit_record(row, table, properties)
            return
    raise ClientError(f"Garrul has no setting named {key!r}. Run 'garrul settings list' for the valid keys.")


@app.command("update")
@command
def update_settings(
    flag: Optional[List[str]] = typer.Option(None, "--flag", help="Boolean setting as key=true or key=false (repeatable)"),
    number: Optional[List[str]] = typer.Option(None, "--number", help="Numeric setting as key=123 (repeatable)"),
    string: Optional[List[str]] = typer.Option(None, "--string", help="Enumerated setting as key=value (repeatable)"),
    text: Optional[List[str]] = typer.Option(None, "--text", help="Free-text setting as key=value (repeatable)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the change"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Override runtime settings. Each key belongs to one group; `settings list` shows which."""
    payload: dict = {}
    flags = {}
    for key, value in _pairs("--flag", flag).items():
        if value not in BOOLEANS:
            raise ClientError(f"--flag {key} must be true or false, got {value!r}.")
        flags[key] = BOOLEANS[value]
    numbers = {}
    for key, value in _pairs("--number", number).items():
        if re.fullmatch(r"-?[0-9]+", value) is None:
            raise ClientError(f"--number {key} must be a whole number, got {value!r}.")
        numbers[key] = int(value)
    for group, values in (("flags", flags), ("numbers", numbers), ("strings", _pairs("--string", string)), ("texts", _pairs("--text", text))):
        if values:
            payload[group] = values
    if not payload:
        raise ClientError("Nothing to update. Pass at least one --flag, --number, --string or --text.")
    mutate(
        "update runtime settings",
        {"method": "POST", "path": "/admin/settings", "body": payload},
        yes,
        dry_run,
        lambda: get_client().update_settings(payload),
    )


@app.command("reset")
@command
def reset_settings(
    yes: bool = typer.Option(False, "--yes", "-y", help="Clear every override. This cannot be undone"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request without sending it"),
):
    """Clear every settings override so all values return to the instance defaults."""
    mutate(
        "reset every runtime setting",
        {"method": "POST", "path": "/admin/settings", "body": {"reset": True}},
        yes,
        dry_run,
        lambda: get_client().reset_settings(),
    )
