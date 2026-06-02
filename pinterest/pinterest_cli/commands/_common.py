"""Shared command helpers for Pinterest CLI."""

from typing import Any, Iterable, Optional

from cli_tools_shared.filters import apply_properties_filter
from pydantic import BaseModel

from ..parsers import format_local_time


def model_to_dict(value: Any) -> dict:
    """Convert a model or dict to a plain dictionary."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    raise TypeError(f"Expected dict or BaseModel, got {type(value).__name__}")


def apply_properties_to_items(items: Iterable[Any], properties: Optional[str]) -> list[dict]:
    """Apply --properties selection to a sequence of models or dicts."""
    rows = [model_to_dict(item) for item in items]
    return apply_properties_filter(rows, properties)


def apply_properties_to_item(item: Any, properties: Optional[str]) -> dict:
    """Apply --properties selection to a single model or dict."""
    rows = apply_properties_to_items([item], properties)
    return rows[0]


def format_timestamp_columns(rows: list[dict]) -> list[dict]:
    """Format timestamp-like columns for table output."""
    formatted_rows: list[dict] = []
    for row in rows:
        formatted = dict(row)
        for key, value in list(formatted.items()):
            if key.endswith("_at") and isinstance(value, str) and value:
                formatted[key] = format_local_time(value)
        formatted_rows.append(formatted)
    return formatted_rows


def detail_rows(item: Any) -> list[dict]:
    """Render a model or dict as field/value rows for table output."""
    record = model_to_dict(item)
    rows: list[dict] = []
    for key, value in record.items():
        if value is None:
            continue
        display_value = value
        if key.endswith("_at") and isinstance(value, str) and value:
            display_value = format_local_time(value)
        rows.append({"field": key, "value": display_value})
    return rows
