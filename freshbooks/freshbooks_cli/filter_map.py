"""Server-side filter translation for FreshBooks list commands.

FreshBooks exposes a ``search[<field>_like]`` family of query parameters on the
clients endpoint. Those parameters are a case-insensitive **substring** match and
they treat ``%`` as a literal character, while the shared CLI ``like`` operator
is SQL-LIKE (anchored, ``%`` is the wildcard). The two semantics do not line up,
so this module never uses a server parameter as the answer.

Instead every translation here is a deliberate **superset narrowing**: the value
sent to FreshBooks is a literal substring that *every* record matching the CLI
filter must contain. FreshBooks returns a superset of the real matches, and
``cli_tools_shared.filters.apply_filters`` remains the single authority for
whether a record actually matches. That keeps filter semantics identical to
every other CLI in this repo while still letting the API do the paging work.

Unsupported operators and unsupported fields translate to no parameter at all.
That is required, not optional: FreshBooks silently ignores unrecognized
``search[...]`` keys and returns the full collection, so emitting a guessed
parameter would look like a working filter while filtering nothing.
"""
from typing import Dict, Optional

from cli_tools_shared.filter_map import FilterMap

# Fields a caller may filter on. These are the keys produced by
# ``formatters.format_client_for_display`` / ``format_invoice_for_display``.
# Declaring them makes ``--filter company:like:%n8n%`` fail loudly instead of
# returning an empty list that reads as "no such customer".
CUSTOMER_FILTER_FIELDS = ("id", "organization", "name", "email")
INVOICE_FILTER_FIELDS = (
    "id",
    "number",
    "client",
    "status",
    "amount",
    "outstanding",
    "created",
    "due_date",
)

# Operators whose matches are guaranteed to contain a literal substring, so a
# ``search[<field>_like]`` narrowing cannot drop a real match.
_SUBSTRING_SAFE_OPERATORS = frozenset(
    {"eq", "like", "ilike", "contains", "startswith", "endswith"}
)


def search_literal(operator: str, value: Optional[str]) -> Optional[str]:
    """Return the literal substring every match of ``operator``/``value`` contains.

    Returns ``None`` when no such literal exists, which means the caller must not
    narrow server-side for this condition.

    ``like``/``ilike`` values are SQL-LIKE patterns. Leading and trailing ``%``
    are wildcards and get stripped, because FreshBooks matches ``%`` literally.
    An *interior* ``%`` (``goo%gle``) has no single contiguous literal, so it
    yields ``None`` rather than a narrowing that would exclude ``gooXgle``.
    """
    if operator not in _SUBSTRING_SAFE_OPERATORS or not value:
        return None

    if operator in ("like", "ilike"):
        value = value.strip("%")
        if "%" in value:
            return None

    return value or None


def _like_translator(search_key: str):
    """Build a translator that narrows a text field via ``search[<field>_like]``."""

    def translate(operator: str, value: str) -> Dict[str, str]:
        literal = search_literal(operator, value)
        if literal is None:
            return {}
        return {search_key: literal}

    return translate


def _userid_translator(operator: str, value: str) -> Dict[str, str]:
    """Narrow by client id. FreshBooks exposes this as ``search[userid]``."""
    if operator != "eq" or not value:
        return {}
    return {"search[userid]": value}


CUSTOMER_FILTER_MAP = (
    FilterMap()
    .register_api_translator("organization", _like_translator("search[organization_like]"))
    .register_api_translator("email", _like_translator("search[email_like]"))
    .register_api_translator("id", _userid_translator)
)
