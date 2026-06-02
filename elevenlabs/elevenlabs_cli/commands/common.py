"""Shared command helpers."""
from typing import Any, List, Optional

from pydantic import BaseModel


def model_to_dict(item: Any) -> dict:
    """Convert a Pydantic model or mapping to a dict."""
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    return dict(item)


def extract_field(item: Any, field: str):
    """Extract a dot-notation field value."""
    data = model_to_dict(item)
    value: Any = data
    for part in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def apply_properties(items: List[Any], properties: Optional[str]) -> List[Any]:
    """Select explicit fields from output rows."""
    if properties is None:
        return items
    fields = [field.strip() for field in properties.split(",")]
    return [{field: extract_field(item, field) for field in fields} for item in items]


def properties_columns(properties: Optional[str], default_columns: List[str]) -> List[str]:
    """Return table columns from requested properties or defaults."""
    if properties is None:
        return default_columns
    return [field.strip() for field in properties.split(",")]


def key_value_rows(item: Any) -> List[dict]:
    """Convert an object to key/value table rows."""
    data = model_to_dict(item)
    return [{"field": key, "value": str(value)} for key, value in data.items() if value is not None]
