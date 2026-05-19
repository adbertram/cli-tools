"""Output formatting helpers.

Re-exports standard output functions from cli_tools_shared.output.
CLI-specific helpers defined below.

Stream Usage:
    stdout (fd 1) -> Data only (JSON, tables) - via print_json(), print_table()
    stderr (fd 2) -> Messages only - via print_error(), print_warning(), print_success(), print_info()
"""

from cli_tools_shared.output import (  # noqa: F401
    console,
    _format_cell_value,
    _serialize_for_json,
    print_json,
    print_table,
    print_output,
    print_error,
    print_warning,
    print_success,
    print_info,
    handle_error,
)
from typing import Dict, List, Optional


# --- CLI-specific helpers ---
max_columns = 6


def apply_limit(data: List[Dict], limit: Optional[int]) -> List[Dict]:
    """Apply client-side limit to data.

    Args:
        data: List of dictionaries
        limit: Maximum number of items to return (None for no limit)

    Returns:
        Limited list of dictionaries
    """
    if limit is None or limit <= 0:
        return data
    return data[:limit]


def apply_properties(data: List[Dict], properties: Optional[str]) -> List[Dict]:
    """Apply client-side property extraction.

    Args:
        data: List of dictionaries
        properties: Comma-separated list of properties to extract (None for all)

    Returns:
        List of dictionaries with only specified properties
    """
    if not properties or not data:
        return data

    props = [p.strip() for p in properties.split(",")]

    result = []
    for item in data:
        filtered = {}
        for prop in props:
            # Support dot notation for nested properties
            if "." in prop:
                parts = prop.split(".")
                value = item
                for part in parts:
                    if isinstance(value, dict) and part in value:
                        value = value[part]
                    else:
                        value = None
                        break
                filtered[prop] = value
            else:
                filtered[prop] = item.get(prop)
        result.append(filtered)

    return result
