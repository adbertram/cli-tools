"""Profile commands for Upwork CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    validate_filters,
)
from cli_tools_shared.output import (
    command,
    handle_error,
    print_error,
)

from ..client import ClientError, get_client
from ..parsers import (
    editable_profile_fields,
    field_definition,
    normalize_profile_updates,
)
from ._render import render_list, render_record

COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "update": ["no_auth"],
    "fields": ["no_auth"],
    "fields list": ["no_auth"],
    "fields get": ["no_auth"],
}

FIELD_COLUMNS = ["name", "label", "editable", "type", "page"]
FILTERABLE_FIELDS = {"name", "label", "editable", "type", "page"}

app = typer.Typer(help="Read and update freelancer profile attributes", no_args_is_help=True)
fields_app = typer.Typer(help="Inspect supported profile fields", no_args_is_help=True)


def _validate_filters(filters: Optional[list[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters, FILTERABLE_FIELDS)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _field_rows(limit: int, filters: Optional[list[str]]) -> list[dict]:
    _validate_filters(filters)
    rows = editable_profile_fields(include_read_only=True)[:limit]
    if filters:
        rows = apply_filters(rows, filters, FILTERABLE_FIELDS)
    return rows


def _render_rows(
    rows: list[dict],
    *,
    table: bool,
    properties: Optional[str],
    columns: list[str],
    empty: str,
) -> None:
    render_list(
        rows,
        table=table,
        properties=properties,
        default_columns=columns,
        empty=empty,
    )


def _render_record(record: dict, *, table: bool, properties: Optional[str]) -> None:
    render_record(
        record,
        table=table,
        properties=properties,
        key_value_columns=("name", "value"),
        json_on_properties=True,
    )


def _load_updates(set_values: Optional[list[str]], file: Optional[Path]) -> dict:
    if set_values and file:
        print_error("Use either --set or --file, not both.")
        raise typer.Exit(1)
    if not set_values and not file:
        print_error("Provide at least one --set FIELD=VALUE or --file profile.json.")
        raise typer.Exit(1)

    updates = {}
    if file:
        try:
            payload = json.loads(file.read_text())
        except json.JSONDecodeError as exc:
            print_error(f"Invalid JSON in {file}: {exc}")
            raise typer.Exit(1)
        if not isinstance(payload, dict):
            print_error("--file must contain one JSON object of profile fields.")
            raise typer.Exit(1)
        updates.update(payload)

    for item in set_values or []:
        if "=" not in item:
            print_error(f"Invalid --set value '{item}'. Expected FIELD=VALUE.")
            raise typer.Exit(1)
        key, value = item.split("=", 1)
        if not key.strip():
            print_error(f"Invalid --set value '{item}'. Field cannot be empty.")
            raise typer.Exit(1)
        updates[key.strip()] = value

    return normalize_profile_updates(updates)


@app.command("list")
@command
def profile_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of fields"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """List supported profile fields."""
    try:
        _render_rows(
            _field_rows(limit, filter),
            table=table,
            properties=properties,
            columns=FIELD_COLUMNS,
            empty="No profile fields found.",
        )
    except FilterValidationError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
@command
def profile_get(
    field: Optional[str] = typer.Argument(None, help="Optional profile field name or alias"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """Report disabled live profile reads or show one field definition."""
    if field:
        try:
            _render_record(field_definition(field), table=table, properties=properties)
        except ClientError as exc:
            raise typer.Exit(handle_error(exc))
        return

    client = get_client()
    try:
        _render_record(client.get_profile(), table=table, properties=properties)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    finally:
        client.close()


@app.command("update")
@command
def profile_update(
    set_values: Optional[list[str]] = typer.Option(
        None,
        "--set",
        help="Set a field value, e.g. --set title='Automation Consultant'",
    ),
    file: Optional[Path] = typer.Option(
        None,
        "--file",
        exists=True,
        dir_okay=False,
        help="JSON object containing profile fields to update",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and print requested updates without changing Upwork",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Apply changes without an interactive confirmation prompt",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """Validate profile updates or report disabled live profile writes."""
    updates = _load_updates(set_values, file)
    if dry_run:
        _render_record(
            {"dry_run": True, "requested": updates},
            table=table,
            properties=properties,
        )
        return
    if not yes:
        print_error("Profile updates require --yes. Use --dry-run to preview changes.")
        raise typer.Exit(1)

    client = get_client()
    try:
        _render_record(
            client.update_profile(updates),
            table=table,
            properties=properties,
        )
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    finally:
        client.close()


@fields_app.command("list")
@command
def fields_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of fields"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (field:op:value)",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """List supported profile fields."""
    try:
        _render_rows(
            _field_rows(limit, filter),
            table=table,
            properties=properties,
            columns=FIELD_COLUMNS,
            empty="No profile fields found.",
        )
    except FilterValidationError as exc:
        raise typer.Exit(handle_error(exc))


@fields_app.command("get")
@command
def fields_get(
    field: str = typer.Argument(..., help="Profile field name or alias"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """Show one supported profile field."""
    try:
        _render_record(field_definition(field), table=table, properties=properties)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


app.add_typer(fields_app, name="fields")
