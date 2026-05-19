"""Shared helpers for PartnerStack command modules."""
from typing import Any, List

from pydantic import BaseModel

from cli_tools_shared.exceptions import ClientError


def model_to_dict(item: Any) -> dict:
    """Convert a Pydantic model or dict to a dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    raise ClientError(f"Expected model or dict, got {type(item).__name__}")


def extract_field(item: Any, field: str) -> Any:
    """Extract a dot-notation field from a model or dict."""
    value: Any = model_to_dict(item)
    for part in field.split("."):
        if not isinstance(value, dict):
            raise ClientError(f"Field path '{field}' cannot descend into non-object value")
        if part not in value:
            raise ClientError(f"Field path '{field}' was not found")
        value = value[part]
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract selected dot-notation fields from each item."""
    return [{field: extract_field(item, field) for field in fields} for item in items]


def parse_properties(properties: str) -> List[str]:
    """Parse a comma-separated property list."""
    fields = [field.strip() for field in properties.split(",")]
    if not all(fields):
        raise ClientError("Properties must be a comma-separated list of field names")
    return fields
