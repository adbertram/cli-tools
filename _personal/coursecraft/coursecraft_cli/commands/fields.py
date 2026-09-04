"""Airtable schema-field commands scoped to the CourseCraft base."""
COMMAND_CREDENTIALS = {
    "get-formula": ["custom"],
    "schema": ["custom"],
    "rename": ["custom"],
    "update-formula": ["custom"],
}

from pathlib import Path
from typing import List, Optional

import typer

from ..client import ClientError, get_client
from cli_tools_shared.output import command, print_error, print_json, print_success


app = typer.Typer(help="Manage CourseCraft Airtable schema fields", no_args_is_help=True)


def _parse_field_types(value: Optional[str]) -> Optional[List[str]]:
    """Split a comma-separated ``--type`` value; every item must be non-empty."""
    if value is None:
        return None
    types = [item.strip() for item in value.split(",")]
    if any(not item for item in types):
        raise typer.BadParameter(
            "Every comma-separated item must be a non-empty Airtable field type.",
            param_hint="--type",
        )
    return types


@app.command("schema")
@command
def schema_fields(
    table: str = typer.Option(..., "--table", help="CourseCraft Airtable table name"),
    field_types: Optional[str] = typer.Option(
        None,
        "--type",
        callback=_parse_field_types,
        help="Comma-separated Airtable field types to keep, e.g. rollup,count,formula",
    ),
):
    """List one table's schema fields as JSON rows of id, name, and type."""
    try:
        fields = get_client().list_fields(table)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    if field_types is not None:
        fields = [field for field in fields if field["type"] in field_types]
    print_json(fields)


@app.command("rename")
@command
def rename_field(
    table: str = typer.Argument(..., help="CourseCraft Airtable table name"),
    current_name: str = typer.Argument(..., help="Current Airtable field name"),
    new_name: str = typer.Argument(..., help="New Airtable field name"),
):
    """Rename one CourseCraft Airtable field and verify the schema read-back."""
    try:
        field = get_client().rename_field(table, current_name, new_name)
        print_success(
            f"Renamed {table}.{current_name} to {new_name} ({field['id']})"
        )
        print_json(field)
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("get-formula")
@command
def get_formula_field(
    table: str = typer.Argument(..., help="CourseCraft Airtable table name"),
    field_name: str = typer.Argument(..., help="Formula field name"),
):
    """Read one formula field's current schema definition."""
    try:
        print_json(get_client().get_formula_field(table, field_name))
    except ClientError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("update-formula")
@command
def update_formula_field(
    table: str = typer.Argument(..., help="CourseCraft Airtable table name"),
    field_name: str = typer.Argument(..., help="Formula field name"),
    formula_file: Path = typer.Option(
        ...,
        "--formula-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="UTF-8 file containing the complete formula",
    ),
):
    """Update one formula field and verify byte-equivalent schema read-back."""
    try:
        if not formula_file.is_file():
            raise ClientError(f"Formula file is not a regular file: {formula_file}")
        formula_bytes = formula_file.read_bytes()
        if not formula_bytes:
            raise ClientError(f"Formula file is empty: {formula_file}")
        try:
            formula = formula_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ClientError(f"Formula file must be valid UTF-8: {formula_file}") from exc

        field = get_client().update_formula_field(table, field_name, formula)
        print_success(f"Updated formula for {table}.{field_name} ({field['id']})")
        print_json(field)
    except (ClientError, OSError) as exc:
        print_error(str(exc))
        raise typer.Exit(1)
