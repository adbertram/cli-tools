"""Filter mapping module with WordPress-specific extensions."""
from typing import List, Dict, Any

from cli_tools_shared import FilterMap
from cli_tools_shared.filters import parse_filter_string


class WordPressFilterMap(FilterMap):
    """FilterMap with WordPress-specific get_untranslatable_filters method."""

    # Fields where the API translator is a pre-filter (e.g., search) that still
    # needs client-side filtering to apply the exact operator.
    _ALWAYS_CLIENT_SIDE = {'name'}

    def get_untranslatable_filters(self, filters: List[str]) -> List[str]:
        """
        Return filter strings that need client-side filtering.

        Includes fields with no API translator AND fields in _ALWAYS_CLIENT_SIDE
        (where the API translator only narrows results but doesn't apply the exact operator).

        Args:
            filters: List of standard filter strings

        Returns:
            List of filter strings needing client-side filtering
        """
        if not filters:
            return []

        untranslatable = []
        for f_str in filters:
            conditions = parse_filter_string(f_str)
            client_side = []
            for field, op, val in conditions:
                if field not in self._api_translators or field in self._ALWAYS_CLIENT_SIDE:
                    if val is not None:
                        client_side.append(f"{field}:{op}:{val}")
                    else:
                        client_side.append(f"{field}:{op}")
            if client_side:
                untranslatable.extend(client_side)

        return untranslatable


# WordPress-specific filter map configuration
def _translate_tags(op: str, val: str) -> Dict[str, Any]:
    """
    Translate tags filter to WordPress REST API parameters.

    Supports:
        - tags:contains:7 -> {'tags': '7'} (include posts with tag)
        - tags:notcontains:7 -> {'tags_exclude': '7'} (exclude posts with tag)
        - tags:eq:7 -> {'tags': '7'} (alias for contains)
        - tags:in:7|8|9 -> {'tags': '7,8,9'} (include posts with any of these tags)
        - tags:nin:7|8|9 -> {'tags_exclude': '7,8,9'} (exclude posts with any of these tags)
    """
    if op in ('contains', 'eq'):
        return {'tags': val}
    elif op == 'notcontains':
        return {'tags_exclude': val}
    elif op == 'in':
        # Convert pipe-separated to comma-separated for API
        return {'tags': val.replace('|', ',')}
    elif op == 'nin':
        return {'tags_exclude': val.replace('|', ',')}
    return {}


def _translate_categories(op: str, val: str) -> Dict[str, Any]:
    """
    Translate categories filter to WordPress REST API parameters.

    Supports:
        - categories:contains:5 -> {'categories': '5'} (include posts in category)
        - categories:notcontains:5 -> {'categories_exclude': '5'} (exclude posts in category)
        - categories:eq:5 -> {'categories': '5'} (alias for contains)
        - categories:in:5|6|7 -> {'categories': '5,6,7'} (include posts in any of these categories)
        - categories:nin:5|6|7 -> {'categories_exclude': '5,6,7'} (exclude posts in any of these categories)
    """
    if op in ('contains', 'eq'):
        return {'categories': val}
    elif op == 'notcontains':
        return {'categories_exclude': val}
    elif op == 'in':
        return {'categories': val.replace('|', ',')}
    elif op == 'nin':
        return {'categories_exclude': val.replace('|', ',')}
    return {}


def _translate_name(op: str, val: str) -> Dict[str, Any]:
    """
    Translate name filter to WordPress REST API 'search' parameter.

    The WordPress REST API does not support exact name matching server-side,
    but its 'search' parameter narrows results to items containing the term.
    Client-side filtering then applies the exact operator (eq, like, contains, etc.).

    Supports:
        - name:eq:Sponsored -> {'search': 'Sponsored'} (API narrows, client-side exact match)
        - name:like:%sponsor% -> {'search': 'sponsor'} (API narrows, client-side like)
        - name:contains:sponsor -> {'search': 'sponsor'} (API narrows, client-side contains)
        - name:startswith:Spon -> {'search': 'Spon'} (API narrows, client-side startswith)
        - name:endswith:red -> {'search': 'red'} (API narrows, client-side endswith)
        - name:ilike:%sponsor% -> {'search': 'sponsor'} (API narrows, client-side ilike)
    """
    # Strip SQL-style wildcards for the API search parameter
    search_val = val.strip('%')
    if search_val:
        return {'search': search_val}
    return {}


def _translate_slug(op: str, val: str) -> Dict[str, Any]:
    """
    Translate slug filter to WordPress REST API 'slug' parameter.

    The WordPress REST API supports exact slug matching directly.

    Supports:
        - slug:eq:sponsored -> {'slug': 'sponsored'} (exact match)
    """
    if op == 'eq':
        return {'slug': val}
    # For other operators, use search to narrow results for client-side filtering
    search_val = val.strip('%')
    if search_val:
        return {'search': search_val}
    return {}


wordpress_filter_map = (
    WordPressFilterMap()
    # Map CLI argument names to filter fields
    .add_argument_mapping('status')  # status=draft -> status:eq:draft
    .add_argument_mapping('author')  # author=1 -> author:eq:1
    .add_argument_mapping('search')  # search=keyword -> search:eq:keyword
    .add_argument_mapping('after')   # after=2024-01-01 -> after:eq:2024-01-01
    .add_argument_mapping('before')  # before=2024-12-31 -> before:eq:2024-12-31

    # Register API translators for WordPress REST API
    .register_api_translator('status', lambda op, val: {'status': val} if op == 'eq' else {})
    .register_api_translator('author', lambda op, val: {'author': val} if op == 'eq' else {})
    .register_api_translator('search', lambda op, val: {'search': val} if op == 'eq' else {})
    .register_api_translator('after', lambda op, val: {'after': val} if op == 'eq' else {})
    .register_api_translator('before', lambda op, val: {'before': val} if op == 'eq' else {})
    .register_api_translator('tags', _translate_tags)
    .register_api_translator('categories', _translate_categories)
    .register_api_translator('name', _translate_name)
    .register_api_translator('slug', _translate_slug)
)
