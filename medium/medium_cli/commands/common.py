"""Shared output helpers for Medium commands."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import print_info, print_json, print_table


def property_fields(properties: Optional[str]) -> Optional[list[str]]:
    """Parse a comma-separated property list."""
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def emit_rows(rows: list[dict], table: bool, properties: Optional[str], columns: list[str], empty: str) -> None:
    """Render a row collection in JSON or table form."""
    fields = property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    output_columns = fields or [column for column in columns if column in rows[0]]
    print_table(rows, output_columns, [column.replace("_", " ").title() for column in output_columns])


def emit_row(row: dict, table: bool, properties: Optional[str], columns: Optional[Iterable[str]] = None) -> None:
    """Render a single record in JSON or table form."""
    fields = property_fields(properties)
    if fields:
        row = apply_properties_filter([row], properties)[0]
    if not table:
        print_json(row)
        return
    output_columns = list(fields or columns or row.keys())
    print_table([row], output_columns, [column.replace("_", " ").title() for column in output_columns])


def read_content(content: Optional[str], content_file: Optional[Path]) -> str:
    """Return exactly one content source."""
    if (content is None) == (content_file is None):
        raise ClientError("Provide exactly one of --content or --content-file.")
    if content_file is not None:
        return content_file.read_text(encoding="utf-8")
    return content
