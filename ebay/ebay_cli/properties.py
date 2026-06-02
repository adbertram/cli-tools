"""Properties filtering utility with strict validation."""
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


class PropertyValidationError(Exception):
    """Raised when a requested property does not exist in the data."""
    pass


def add_template_property_aliases(templates: list[dict]) -> list[dict]:
    """Expose a stable id alias for template property selection."""
    return [{"id": template.get("name", ""), **template} for template in templates]


def add_image_property_aliases(images: list[dict]) -> list[dict]:
    """Expose stable id/name aliases for image property selection."""
    aliased = []
    for image in images:
        original = image.get("original", "")
        parsed = urlparse(original)
        candidate = parsed.path if parsed.scheme else original
        aliased.append(
            {
                "id": image.get("image_id", ""),
                "name": Path(candidate).name,
                **image,
            }
        )
    return aliased


def validate_and_filter_properties(data: Any, properties: str, item_key: Optional[str] = None) -> Any:
    """
    Filter response data to include only specified properties.
    Raises PropertyValidationError if any requested property doesn't exist.

    Args:
        data: Response data (list of dicts or single dict)
        properties: Comma-separated list of field names to include
        item_key: Key name if data is wrapped (e.g., 'orders', 'policies')

    Returns:
        Filtered data with only specified properties

    Raises:
        PropertyValidationError: If any property doesn't exist in the data
    """
    if not properties:
        return data

    prop_list = [p.strip() for p in properties.split(",")]

    # Get sample item to validate properties exist
    sample_item = None
    if isinstance(data, dict):
        if item_key and item_key in data and isinstance(data[item_key], list):
            items = data[item_key]
            if items:
                sample_item = items[0]
        else:
            sample_item = data
    elif isinstance(data, list) and data:
        sample_item = data[0]

    # Validate all requested properties exist
    if sample_item:
        available_keys = set(sample_item.keys())
        missing = [p for p in prop_list if p not in available_keys]
        if missing:
            raise PropertyValidationError(
                f"Unknown properties: {', '.join(missing)}. "
                f"Available: {', '.join(sorted(available_keys))}"
            )

    # Apply filtering
    if isinstance(data, dict):
        if item_key and item_key in data and isinstance(data[item_key], list):
            data[item_key] = [
                {k: v for k, v in item.items() if k in prop_list}
                for item in data[item_key]
            ]
        else:
            data = {k: v for k, v in data.items() if k in prop_list}
    elif isinstance(data, list):
        data = [
            {k: v for k, v in item.items() if k in prop_list}
            for item in data
        ]

    return data
