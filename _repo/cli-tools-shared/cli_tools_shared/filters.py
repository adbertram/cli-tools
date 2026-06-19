"""Filter validation and application module."""
import re
from decimal import Decimal, InvalidOperation
from typing import List, Set, Dict, Any, Tuple, Optional, Iterable

class FilterValidationError(Exception):
    """Custom exception for filter validation errors."""
    pass

# Supported operators
OPERATORS: Set[str] = {
    'eq', 'ne', 'gt', 'gte', 'lt', 'lte',
    'in', 'nin', 'like', 'ilike', 'null', 'notnull',
    'contains', 'startswith', 'endswith'
}

# Operators that don't require a value
NO_VALUE_OPERATORS: Set[str] = {'null', 'notnull'}

def validate_filters(
    filter_strings: List[str],
    allowed_fields: Optional[Iterable[str]] = None,
) -> List[str]:
    """
    Validates a list of filter strings.

    Args:
        filter_strings: List of filter strings from command line
        allowed_fields: Optional iterable of field names that may be filtered.
            When provided, any filter referencing a field outside this set
            raises ``FilterValidationError`` listing the supported fields. This
            is opt-in: when ``None`` (the default), no field-name restriction is
            applied and behavior is unchanged for callers that do not declare
            their filterable fields.

            Pass this whenever the data being filtered only carries a known,
            fixed set of fields (e.g. a metadata-only listing). Without it, a
            filter on a non-existent field silently matches nothing and a caller
            cannot tell "no rows matched" apart from "that field isn't
            filterable" -- a false negative.

    Returns:
        The validated filter strings

    Raises:
        FilterValidationError: If any filter string is invalid, or references a
            field not in ``allowed_fields`` when that set is provided.
    """
    if not filter_strings:
        return []

    allowed_set = _normalize_allowed_fields(allowed_fields)

    for filter_string in filter_strings:
        if not filter_string:
            continue

        # Split by comma for AND logic
        parts = filter_string.split(',')

        for part in parts:
            _validate_part(part.strip(), allowed_set)

    return filter_strings

def apply_filters(
    data: List[Dict],
    filter_strings: Optional[List[str]],
    allowed_fields: Optional[Iterable[str]] = None,
) -> List[Dict]:
    """
    Apply filters to a list of dictionaries (client-side filtering).

    Args:
        data: List of dictionaries to filter
        filter_strings: List of filter strings (field:op:value)
        allowed_fields: Optional iterable of filterable field names. When
            provided, a filter on any other field raises
            ``FilterValidationError`` instead of silently returning an empty
            list. See :func:`validate_filters`. Opt-in; ``None`` preserves the
            previous unrestricted behavior.

    Returns:
        Filtered list of dictionaries

    Raises:
        FilterValidationError: If a filter is malformed, or references a field
            outside ``allowed_fields`` when that set is provided.
    """
    # Field validation must run even when there is nothing to filter against.
    # An unsupported-field filter is a caller error regardless of whether the
    # dataset happens to be empty; skipping validation here would let
    # `Username:like:%x%` look like a clean "no matches" on an empty list.
    if not filter_strings:
        return data

    validate_filters(filter_strings, allowed_fields)

    if not data:
        return data

    filtered_data = []

    parsed_filters = [parse_filter_string(fs) for fs in filter_strings]

    for item in data:
        # OR logic: item matches if it satisfies ANY of the parsed_filters groups
        matches_any_group = False

        for conditions in parsed_filters:
            # AND logic: item must match ALL conditions in this group
            matches_all_conditions = True
            for field, op, val in conditions:
                if not _matches_condition(item, field, op, val):
                    matches_all_conditions = False
                    break

            if matches_all_conditions:
                matches_any_group = True
                break

        if matches_any_group:
            filtered_data.append(item)

    return filtered_data

def _normalize_allowed_fields(
    allowed_fields: Optional[Iterable[str]],
) -> Optional[Set[str]]:
    """Normalize an allowed-field declaration into a set, or None when unset.

    Returns ``None`` when ``allowed_fields`` is ``None`` (no restriction).
    Raises ``FilterValidationError`` for an explicitly empty allowlist, because
    "filtering is enabled but no field is filterable" is a caller bug, not a
    silent no-op.
    """
    if allowed_fields is None:
        return None
    allowed_set = {str(f) for f in allowed_fields}
    if not allowed_set:
        raise FilterValidationError(
            "No filterable fields are configured for this command, so --filter "
            "cannot be satisfied."
        )
    return allowed_set


def _check_field_allowed(field: str, allowed_set: Optional[Set[str]]):
    """Raise a clear error if ``field`` is not filterable.

    The check is case-sensitive and exact. Field lookup at match time
    (``get_nested_value``) is itself case-sensitive, so accepting a different
    case here (e.g. ``Name`` for ``name``) would let the filter pass validation
    and then silently match nothing -- recreating the very false-negative this
    validation exists to prevent. Reject a wrong-case field loudly instead.
    A no-op when ``allowed_set`` is ``None`` (no restriction configured).
    """
    if allowed_set is None:
        return
    if field not in allowed_set:
        supported = ", ".join(sorted(allowed_set))
        raise FilterValidationError(
            f"Field '{field}' is not filterable. Supported fields: {supported}."
        )


def _validate_part(part: str, allowed_set: Optional[Set[str]] = None):
    """Validate a single filter part (field:op:value)."""
    if not part:
        raise FilterValidationError("Empty filter part")

    tokens = part.split(':')

    if len(tokens) < 2:
        raise FilterValidationError(f"Invalid format '{part}'. Expected field:value or field:op:value")

    field = tokens[0]
    if not field:
        raise FilterValidationError(f"Field cannot be empty in '{part}'")

    _check_field_allowed(field, allowed_set)

    # Check if second token is an operator
    second_token = tokens[1]

    if second_token in OPERATORS:
        op = second_token
        if op in NO_VALUE_OPERATORS:
            if len(tokens) > 2:
                 raise FilterValidationError(f"Operator '{op}' does not expect a value in '{part}'")
        else:
            if len(tokens) < 3:
                 raise FilterValidationError(f"Operator '{op}' requires a value in '{part}'")

            value = ":".join(tokens[2:])
            if not value:
                raise FilterValidationError(f"Value cannot be empty for operator '{op}' in '{part}'")
    else:
        value = ":".join(tokens[1:])
        if not value:
             raise FilterValidationError(f"Value cannot be empty in '{part}'")

def parse_filter_string(filter_string: str) -> List[Tuple[str, str, Optional[str]]]:
    """Parses a filter string into a list of (field, op, value) tuples (AND logic)."""
    conditions = []
    parts = filter_string.split(',')
    for part in parts:
        part = part.strip()
        if not part: continue

        tokens = part.split(':')
        field = tokens[0]

        if len(tokens) >= 2 and tokens[1] in OPERATORS:
            op = tokens[1]
            if op in NO_VALUE_OPERATORS:
                val = None
            else:
                val = ":".join(tokens[2:])
        else:
            op = 'eq'
            val = ":".join(tokens[1:])

        conditions.append((field, op, val))
    return conditions

def _cast_value(value: str, target_type: type) -> Any:
    """Attempts to cast string value to target type."""
    try:
        if target_type == bool:
            return value.lower() in ('true', '1', 'yes', 'on')
        if target_type == int:
            return int(value)
        if target_type == float:
            return float(value)
    except (ValueError, TypeError):
        pass
    return value

def _as_decimal(value: Any) -> Optional[Decimal]:
    """Return Decimal for numeric filter values; non-numeric values stay non-numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
    return None

def _comparison_values(item_val: Any, filter_val: str) -> Tuple[Any, Any]:
    item_number = _as_decimal(item_val)
    filter_number = _as_decimal(filter_val)
    if item_number is not None and filter_number is not None:
        return item_number, filter_number
    return item_val, _cast_value(filter_val, type(item_val))

def _matches_condition(item: Dict, field: str, op: str, value: Optional[str]) -> bool:
    """Check if item matches the condition."""
    item_val = get_nested_value(item, field)

    if op == 'null':
        return item_val is None
    if op == 'notnull':
        return item_val is not None

    if item_val is None:
        return False

    # Cast filter value to match item value type for comparison
    typed_filter_val = _cast_value(value, type(item_val))

    if op == 'eq':
        return item_val == typed_filter_val
    if op == 'ne':
        return item_val != typed_filter_val

    # Comparison operators
    if op in ('gt', 'gte', 'lt', 'lte'):
        left, right = _comparison_values(item_val, value)
        try:
            if op == 'gt':
                return left > right
            if op == 'gte':
                return left >= right
            if op == 'lt':
                return left < right
            if op == 'lte':
                return left <= right
        except TypeError:
            return False

    if op == 'in':
        options = value.split('|')
        typed_options = [_cast_value(opt, type(item_val)) for opt in options]
        return item_val in typed_options

    if op == 'nin':
        options = value.split('|')
        typed_options = [_cast_value(opt, type(item_val)) for opt in options]
        return item_val not in typed_options

    if op in ('like', 'ilike'):
        # SQL-LIKE semantics: '%' is a wildcard. Both 'like' and 'ilike' are
        # case-insensitive here. Users expect `name:like:%google%` to match an
        # entry named "Google" (the same way SQL LIKE is case-insensitive on
        # most default collations); a case-sensitive 'like' silently drops
        # real matches and reads as "not found". 'ilike' is kept as an explicit
        # synonym. Case-insensitive is a strict superset of the old behavior,
        # so existing 'like' callers keep matching everything they matched
        # before.
        pattern = re.escape(value).replace('%', '.*')
        return bool(re.search(f"^{pattern}$", str(item_val), re.IGNORECASE))

    if op == 'contains':
        return value.lower() in str(item_val).lower()

    if op == 'startswith':
        return str(item_val).lower().startswith(value.lower())

    if op == 'endswith':
        return str(item_val).lower().endswith(value.lower())

    return False


def get_nested_value(obj: Dict, path: str) -> Any:
    """
    Get value from nested dict using dot notation.

    Args:
        obj: Dictionary to extract value from
        path: Dot-separated path (e.g., 'fields.Name' or 'metadata.created_at')

    Returns:
        The value at the path, or None if not found
    """
    keys = path.split(".")
    value = obj
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value


def apply_properties_filter(data: List[Dict], properties: Optional[str]) -> List[Dict]:
    """
    Filter dictionary keys to only include specified properties.

    Args:
        data: List of dictionaries to filter
        properties: Comma-separated list of property names (supports dot notation)

    Returns:
        List of dictionaries with only the specified properties
    """
    if not properties or not data:
        return data

    prop_list = [p.strip() for p in properties.split(",") if p.strip()]
    if not prop_list:
        return data

    filtered_data = []
    for item in data:
        filtered_item = {}
        for prop in prop_list:
            # Always project the requested property, even when its value is
            # None or the field is absent. Emit an explicit null instead of
            # silently dropping the key, so a missing/empty value can never be
            # mistaken for "this property was not requested." Dropping the key
            # here would let a populated-but-currently-empty field read as gone.
            filtered_item[prop] = get_nested_value(item, prop)
        filtered_data.append(filtered_item)

    return filtered_data


def apply_limit(data: List[Any], limit: Optional[int]) -> List[Any]:
    """
    Apply limit to a list of items.

    Args:
        data: List to limit
        limit: Maximum number of items to return

    Returns:
        Sliced list if limit is specified, otherwise original list
    """
    if limit is not None and limit > 0:
        return data[:limit]
    return data
