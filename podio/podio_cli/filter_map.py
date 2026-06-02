"""Filter mapping module with Podio-specific utilities."""
from typing import Any

from cli_tools_shared import FilterMap  # noqa: F401


def apply_properties(data: Any, properties: str) -> Any:
    """
    Filter response data to include only specified properties.

    Args:
        data: Response data (list of dicts or single dict)
        properties: Comma-separated list of field names to include

    Returns:
        Filtered data with only specified properties
    """
    if not properties:
        return data

    prop_list = [p.strip() for p in properties.split(",")]

    if isinstance(data, dict):
        if 'items' in data and isinstance(data['items'], list):
            # Handle wrapped response
            data['items'] = [
                {k: v for k, v in item.items() if k in prop_list}
                for item in data['items']
            ]
        else:
            data = {k: v for k, v in data.items() if k in prop_list}
    elif isinstance(data, list):
        data = [
            {k: v for k, v in item.items() if k in prop_list}
            for item in data
        ]

    return data
