"""Helpers for rendering Yubico search results."""

from pydantic import BaseModel


def model_to_dict(item):
    """Convert a model or dict into a plain dict."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a dotted field path from a model or dict."""
    value = model_to_dict(item)
    for part in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def extract_fields(items: list, fields: list[str]) -> list[dict]:
    """Project each item to the requested field list."""
    projected = []
    for item in items:
        row = {}
        for field in fields:
            row[field] = extract_field(item, field)
        projected.append(row)
    return projected
