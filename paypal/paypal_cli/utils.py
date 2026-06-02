"""Utility functions for PayPal CLI."""


def names_match(cell_text: str, target_name: str) -> bool:
    """Check if two names match using flexible matching.

    Matches on:
    - Exact match
    - Either name contains the other (min 3 chars)
    - First name match (e.g., "Noah Z" vs "Noah Zazula")

    Args:
        cell_text: Name from PayPal table cell (already lowercase)
        target_name: Name to search for (already lowercase)

    Returns:
        True if names match
    """
    if cell_text == target_name:
        return True
    if target_name in cell_text:
        return True
    if cell_text in target_name and len(cell_text) >= 3:
        return True

    # First name match
    cell_first = cell_text.split(' ')[0] if cell_text else ''
    target_first = target_name.split(' ')[0] if target_name else ''
    if cell_first and target_first and cell_first == target_first and len(cell_first) >= 3:
        return True

    return False
