"""Translate standard CLI filters to Airtable formulas."""

import re
from typing import List, Optional
from .field_mappings import validate_field
from .filters import parse_filter_string


def escape_value(value: str) -> str:
    """Escape special characters for Airtable formulas.

    Handles: single quotes, backslashes
    """
    value = value.replace("\\", "\\\\")
    value = value.replace("'", "\\'")
    return value


def detect_date(value: str) -> bool:
    """Detect if value is ISO date format."""
    iso_date_pattern = r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$'
    return bool(re.match(iso_date_pattern, value))


def detect_boolean(value: str) -> Optional[str]:
    """Detect if value is a boolean and return Airtable boolean expression.

    Args:
        value: String value to check

    Returns:
        'TRUE()' or 'FALSE()' if boolean, None otherwise
    """
    if value.lower() in ('true', '1', 'yes'):
        return 'TRUE()'
    if value.lower() in ('false', '0', 'no'):
        return 'FALSE()'
    return None


def translate_operator(airtable_field: str, op: str, value: Optional[str]) -> str:
    """Translate single field:op:value to Airtable formula.

    Args:
        airtable_field: Airtable field name (e.g., 'Status')
        op: Operator (eq, ne, gt, gte, lt, lte, in, nin, like, ilike, contains, startswith, endswith, null, notnull)
        value: Filter value (can be None for null/notnull operators)

    Returns:
        Airtable formula string
    """
    field_ref = f"{{{airtable_field}}}"

    # Handle null/notnull (value is ignored)
    if op == 'null':
        return f"BLANK({field_ref})"
    if op == 'notnull':
        return f"NOT(BLANK({field_ref}))"

    # For other operators, value is required
    if value is None:
        raise ValueError(f"Operator '{op}' requires a value")

    # Determine value expression based on type
    bool_expr = detect_boolean(value)
    if bool_expr:
        # Boolean values use TRUE()/FALSE() in Airtable
        value_expr = bool_expr
    elif detect_date(value):
        # Wrap dates in DATETIME_PARSE
        value_expr = f"DATETIME_PARSE('{escape_value(value)}')"
    else:
        value_expr = f"'{escape_value(value)}'"

    # Simple comparison operators
    if op == 'eq':
        return f"{field_ref}={value_expr}"
    if op == 'ne':
        return f"NOT({field_ref}={value_expr})"
    if op == 'gt':
        return f"{field_ref}>{value_expr}"
    if op == 'gte':
        return f"{field_ref}>={value_expr}"
    if op == 'lt':
        return f"{field_ref}<{value_expr}"
    if op == 'lte':
        return f"{field_ref}<={value_expr}"

    # IN operator: val1|val2|val3 → OR({F}='v1',{F}='v2',{F}='v3')
    if op == 'in':
        values = value.split('|')
        conditions = [f"{field_ref}='{escape_value(v)}'" for v in values]
        return f"OR({','.join(conditions)})"

    # NIN operator: val1|val2|val3 → AND(NOT({F}='v1'),NOT({F}='v2'))
    if op == 'nin':
        values = value.split('|')
        conditions = [f"NOT({field_ref}='{escape_value(v)}')" for v in values]
        return f"AND({','.join(conditions)})"

    # String matching operators
    if op == 'like':
        # Case-sensitive substring match
        return f"SEARCH('{escape_value(value)}', {field_ref})"

    if op in ('ilike', 'contains'):
        # Case-insensitive substring match using LOWER()
        return f"SEARCH(LOWER('{escape_value(value)}'), LOWER({field_ref}))"

    if op == 'startswith':
        # LEFT({Field}, LEN('val'))='val'
        return f"LEFT({field_ref}, LEN('{escape_value(value)}'))='{escape_value(value)}'"

    if op == 'endswith':
        # RIGHT({Field}, LEN('val'))='val'
        return f"RIGHT({field_ref}, LEN('{escape_value(value)}'))='{escape_value(value)}'"

    raise ValueError(f"Unsupported operator: {op}")


def translate_filter_group(filter_str: str, table: str) -> str:
    """Translate comma-separated filters to AND() formula.

    Args:
        filter_str: Comma-separated filters (e.g., 'status:eq:Complete,order:gt:5')
        table: Table name for field validation

    Returns:
        Airtable formula with AND() wrapper
    """
    parsed = parse_filter_string(filter_str)

    if not parsed:
        raise ValueError("Empty filter string")

    conditions = []
    for field, op, value in parsed:
        airtable_field = validate_field(field, table)
        condition = translate_operator(airtable_field, op, value)
        conditions.append(condition)

    if len(conditions) == 1:
        return conditions[0]

    return f"AND({','.join(conditions)})"


def translate_filters(filter_strings: List[str], table: str) -> str:
    """Translate multiple filter groups to single Airtable formula.

    Multiple filter groups are combined with OR() logic.
    Within each group, comma-separated conditions are combined with AND().

    Args:
        filter_strings: List of filter strings from multiple --filter flags
        table: Table name for field validation

    Returns:
        Complete Airtable formula string

    Example:
        ['status:eq:Complete,order:gt:5', 'name:contains:intro']
        → OR(AND({Status}='Complete',{Order}>'5'),SEARCH('intro',{Name}))
    """
    if not filter_strings:
        return ""

    formulas = [translate_filter_group(fs, table) for fs in filter_strings]

    if len(formulas) == 1:
        return formulas[0]

    return f"OR({','.join(formulas)})"
