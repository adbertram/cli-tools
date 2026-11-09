"""Normalise the ``--properties`` option shared by the list commands."""
from typing import List, Optional


def parse_properties(properties: Optional[List[str]]) -> Optional[List[str]]:
    """Flatten ``--properties`` values into one list of property names.

    Typer hands back one list item per ``--properties`` flag, so
    ``--properties id,name`` arrives as ``["id,name"]``. Split every item on
    commas and strip whitespace so comma-separated and repeated flags both work.
    Returns None when no property was requested.
    """
    if not properties:
        return None
    names = [name.strip() for item in properties for name in item.split(",") if name.strip()]
    return names or None
