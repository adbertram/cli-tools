"""Filter translation module for Google APIs.

Translates standard CLI filter format (field:op:value) to Google API-specific query syntax.
"""
from typing import List, Optional, Tuple
from cli_tools_shared.filters import OPERATORS

# Extended operators that map to standard ones
OPERATOR_ALIASES = {
    'contains': 'like',
    'icontains': 'ilike',
}

# Combined operators including aliases
ALL_OPERATORS = OPERATORS | set(OPERATOR_ALIASES.keys())


def parse_filter_with_aliases(filter_string: str) -> List[Tuple[str, str, Optional[str]]]:
    """Parse filter string supporting both standard operators and aliases.

    Args:
        filter_string: Filter in format 'field:op:value' or 'field:value'

    Returns:
        List of (field, normalized_op, value) tuples
    """
    conditions = []
    parts = filter_string.split(',')

    for part in parts:
        part = part.strip()
        if not part:
            continue

        tokens = part.split(':')
        field = tokens[0]

        if len(tokens) >= 2 and tokens[1] in ALL_OPERATORS:
            op = tokens[1]
            # Normalize aliases to standard operators
            op = OPERATOR_ALIASES.get(op, op)
            if op in ('null', 'notnull'):
                val = None
            else:
                val = ':'.join(tokens[2:])
        else:
            op = 'eq'
            val = ':'.join(tokens[1:])

        conditions.append((field, op, val))

    return conditions


def translate_gmail_filters(filters: Optional[List[str]]) -> str:
    """Translate filters to Gmail query syntax.

    Args:
        filters: List of filter strings

    Returns:
        Gmail query string
    """
    if not filters:
        return ""

    query_parts = []

    for filter_str in filters:
        conditions = parse_filter_with_aliases(filter_str)
        for field, op, value in conditions:
            gmail_query = _translate_gmail_condition(field, op, value)
            if gmail_query:
                query_parts.append(gmail_query)

    return ' '.join(query_parts)


def _translate_gmail_condition(field: str, op: str, value: Optional[str]) -> str:
    """Translate a single condition to Gmail query syntax."""
    field_map = {
        'from': 'from',
        'sender': 'from',
        'to': 'to',
        'recipient': 'to',
        'subject': 'subject',
        'label': 'label',
        'cc': 'cc',
        'bcc': 'bcc',
    }

    gmail_field = field_map.get(field.lower(), field)

    if op == 'eq':
        if field.lower() in ['unread', 'read', 'starred', 'important', 'snoozed']:
            if value.lower() in ['true', '1', 'yes']:
                return f"is:{field.lower()}"
            else:
                return f"-is:{field.lower()}"
        elif field.lower() == 'attachment':
            if value.lower() in ['true', '1', 'yes']:
                return "has:attachment"
            else:
                return "-has:attachment"
        else:
            return f"{gmail_field}:{value}"

    elif op == 'ne':
        return f"-{gmail_field}:{value}"

    elif op == 'in':
        options = value.split('|')
        or_parts = [f"{gmail_field}:{opt.strip()}" for opt in options]
        return f"({' OR '.join(or_parts)})"

    elif op == 'nin':
        options = value.split('|')
        return ' '.join([f"-{gmail_field}:{opt.strip()}" for opt in options])

    elif op in ['like', 'ilike']:
        clean_value = value.replace('%', '')
        return f"{gmail_field}:{clean_value}"

    elif op in ['gt', 'gte', 'lt', 'lte']:
        if field.lower() in ['date', 'time', 'after', 'before']:
            if op in ['gt', 'gte']:
                return f"after:{value}"
            else:
                return f"before:{value}"

    return ""


def translate_drive_filters(filters: Optional[List[str]]) -> str:
    """Translate filters to Google Drive query syntax.

    Args:
        filters: List of filter strings

    Returns:
        Drive query string
    """
    if not filters:
        return ""

    query_parts = []

    for filter_str in filters:
        conditions = parse_filter_with_aliases(filter_str)
        for field, op, value in conditions:
            drive_query = _translate_drive_condition(field, op, value)
            if drive_query:
                query_parts.append(drive_query)

    return " and ".join(query_parts)


def _translate_drive_condition(field: str, op: str, value: Optional[str]) -> str:
    """Translate a single condition to Drive query syntax."""
    field_lower = field.lower()

    if field_lower in ['folder', 'parent', 'parentid']:
        if op == 'eq':
            return f"'{value}' in parents"
        elif op == 'ne':
            return f"not '{value}' in parents"

    elif field_lower in ['mimetype', 'type']:
        if op == 'eq':
            return f"mimeType='{value}'"
        elif op == 'ne':
            return f"mimeType!='{value}'"

    elif field_lower == 'name':
        if op == 'eq':
            return f"name='{value}'"
        elif op == 'ne':
            return f"name!='{value}'"
        elif op in ['like', 'ilike']:
            clean_value = value.replace('%', '')
            return f"name contains '{clean_value}'"

    elif field_lower == 'trashed':
        if op == 'eq':
            return f"trashed={value.lower()}"

    return ""


def translate_calendar_filters(filters: Optional[List[str]]) -> dict:
    """Translate filters to Google Calendar API parameters.

    Args:
        filters: List of filter strings

    Returns:
        Dictionary of API parameters to add to the request
    """
    if not filters:
        return {}

    params = {}
    query_parts = []

    for filter_str in filters:
        conditions = parse_filter_with_aliases(filter_str)
        for field, op, value in conditions:
            param_updates = _translate_calendar_condition(field, op, value)
            if 'q' in param_updates:
                query_parts.append(param_updates['q'])
                param_updates.pop('q')
            params.update(param_updates)

    if query_parts:
        params['q'] = ' '.join(query_parts)

    return params


def _translate_calendar_condition(field: str, op: str, value: Optional[str]) -> dict:
    """Translate a single condition to Calendar API parameters."""
    field_lower = field.lower()
    params = {}

    if field_lower in ['summary', 'title', 'description', 'location', 'q', 'query', 'name']:
        if op == 'eq':
            params['q'] = value
        elif op in ['like', 'ilike']:
            params['q'] = value.replace('%', '')

    elif field_lower in ['deleted', 'showdeleted']:
        if op == 'eq':
            params['showDeleted'] = value.lower() in ['true', '1', 'yes']

    elif field_lower in ['after', 'timemin', 'start']:
        if op in ['eq', 'gte', 'gt']:
            params['timeMin'] = value

    elif field_lower in ['before', 'timemax', 'end']:
        if op in ['eq', 'lte', 'lt']:
            params['timeMax'] = value

    return params


def translate_cloud_project_filters(filters: Optional[List[str]]) -> str:
    """Translate filters to Cloud Resource Manager query syntax.

    Args:
        filters: List of filter strings

    Returns:
        Cloud Resource Manager query string
    """
    if not filters:
        return ""

    query_parts = []

    for filter_str in filters:
        conditions = parse_filter_with_aliases(filter_str)
        for field, op, value in conditions:
            crm_query = _translate_cloud_project_condition(field, op, value)
            if crm_query:
                query_parts.append(crm_query)

    return " ".join(query_parts)


def _translate_cloud_project_condition(field: str, op: str, value: Optional[str]) -> str:
    """Translate a single condition to Cloud Resource Manager query syntax."""
    field_lower = field.lower()

    # Map common field names to CRM API field names
    field_map = {
        'name': 'name',
        'id': 'id',
        'projectid': 'id',
        'project_id': 'id',
        'state': 'state',
        'status': 'state',
        'displayname': 'displayName',
        'display_name': 'displayName',
        'parent': 'parent',
    }

    crm_field = field_map.get(field_lower)

    if crm_field and op == 'eq':
        # Quote values with spaces
        if ' ' in value:
            return f'{crm_field}:"{value}"'
        return f'{crm_field}:{value}'

    # Support labels.key:value syntax
    if field_lower.startswith('labels.') and op == 'eq':
        return f'{field}:{value}'

    return ""


def translate_chat_filters(filters: Optional[List[str]]) -> str:
    """Translate filters to Google Chat messages API filter syntax.

    Args:
        filters: List of filter strings

    Returns:
        Chat API filter string (conditions joined with AND)
    """
    if not filters:
        return ""

    query_parts = []

    for filter_str in filters:
        conditions = parse_filter_with_aliases(filter_str)
        for field, op, value in conditions:
            chat_query = _translate_chat_condition(field, op, value)
            if chat_query:
                query_parts.append(chat_query)

    return " AND ".join(query_parts)


def _translate_chat_condition(field: str, op: str, value: Optional[str]) -> str:
    """Translate a single condition to Chat API filter syntax."""
    field_lower = field.lower()

    if field_lower in ['after', 'createtime_after', 'start']:
        return f'createTime > "{value}"'

    elif field_lower in ['before', 'createtime_before', 'end']:
        return f'createTime < "{value}"'

    elif field_lower == 'thread':
        if op == 'eq':
            return f'thread.name = "{value}"'

    return ""


def translate_docs_filters(filters: Optional[List[str]]) -> str:
    """Translate filters to Google Docs/Drive query syntax."""
    return translate_drive_filters(filters)


def translate_sheets_filters(filters: Optional[List[str]]) -> str:
    """Translate filters to Google Sheets/Drive query syntax."""
    return translate_drive_filters(filters)
