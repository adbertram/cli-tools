"""Command modules for Wordpress CLI."""
from typing import List, Optional

from cli_tools_shared.filters import apply_filters
from ..filter_map import wordpress_filter_map


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


def apply_client_side_filters(items: list, filter_strings: Optional[List[str]]) -> list:
    """Apply client-side filtering for filters not handled by the API.

    Converts models to dicts, applies filters, returns filtered dicts.
    """
    if not filter_strings:
        return items

    untranslatable = wordpress_filter_map.get_untranslatable_filters(filter_strings)
    if not untranslatable:
        return items

    # Convert models to dicts for filtering
    dicts = [model_to_dict(item) for item in items]
    filtered = apply_filters(dicts, untranslatable)

    return filtered
