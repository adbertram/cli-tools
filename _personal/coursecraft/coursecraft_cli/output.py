"""Output formatting helpers.

Re-exports standard output functions from cli_tools_shared.output.
CLI-specific helpers defined below.

Stream Usage:
    stdout (fd 1) -> Data only (JSON, tables) - via print_json(), print_table()
    stderr (fd 2) -> Messages only - via print_error(), print_warning(), print_success(), print_info()
"""

from cli_tools_shared.output import (  # noqa: F401
    print_json,
    print_table,
    print_error,
    print_success,
    print_info,
)
from cli_tools_shared.filters import (
    apply_properties_filter as _apply_properties_filter_shared,
)
from typing import Optional, List, Dict, Sequence
import sys


# --- CLI-specific helpers ---

# Top-level keys that live outside the Airtable ``fields`` object. Every
# CourseCraft record is Airtable-shaped: ``{"id", "createdTime", "fields": {...}}``.
_RECORD_TOP_LEVEL_KEYS = frozenset({"id", "createdTime"})


def _normalize_property_path(prop: str) -> str:
    """Resolve a ``--properties`` token to an explicit record path.

    CourseCraft records are Airtable-shaped, so every content field lives under
    the ``fields`` object, never at the top level. A bare field name such as
    ``Environment Spec`` therefore has exactly one meaning: the Airtable field
    ``fields.Environment Spec``. This rewrite is deterministic (one path per
    input form), not a fallback:

    - ``id`` / ``createdTime`` are the only top-level record keys and are kept
      as-is.
    - A token already rooted at ``fields`` (``fields`` or ``fields.<name>``) is
      kept as-is so the documented dot-notation contract is unchanged.
    - Any other token is a bare Airtable field name and is rooted at ``fields``.

    Field names may contain spaces and dots-in-names are not used by CourseCraft
    tables, so only the first path segment is inspected.
    """
    if prop in _RECORD_TOP_LEVEL_KEYS:
        return prop
    if prop == "fields" or prop.startswith("fields."):
        return prop
    return f"fields.{prop}"


def _normalize_properties(properties: Sequence[str]) -> str:
    """Flatten every ``--properties`` value into one normalized path list.

    ``--properties`` is a repeatable option, so Typer hands this helper a
    sequence of raw values. Both supported input forms carry the same meaning
    and are unioned, never overwritten:

    - one value per flag (``-p "fields.Platform" -p "fields.Status"``)
    - a comma-separated value (``-p "fields.Platform,fields.Status"``)

    Order follows the command line, left to right. A projection request that
    resolves to zero property names is malformed and raises, because silently
    returning the unprojected record would let the caller mistake a full record
    for a projection.
    """
    if isinstance(properties, str):
        raise TypeError(
            "properties must be a sequence of --properties values, not a bare "
            "string; iterating a string would project one path per character. "
            'Pass ["id,fields.Name"], not "id,fields.Name".'
        )

    tokens = [
        token.strip()
        for value in properties
        for token in value.split(",")
        if token.strip()
    ]
    if not tokens:
        raise ValueError(
            "--properties was given but names no property. "
            'Pass at least one field, e.g. -p "fields.Name".'
        )
    return ",".join(_normalize_property_path(token) for token in tokens)


def apply_properties_filter(
    data: List[Dict], properties: Optional[Sequence[str]]
) -> List[Dict]:
    """Project CourseCraft records to ``--properties``, resolving bare field names.

    Wraps the shared ``apply_properties_filter`` so both bare Airtable field
    names (``--properties "Environment Spec"``) and the documented dot-notation
    form (``--properties "fields.Environment Spec"``) resolve to the same
    populated value. Repeated ``--properties`` flags accumulate into one
    projection. Empty or absent requested fields still project an explicit
    ``null`` (the shared helper never drops a requested key), so this is used by
    every CourseCraft ``get`` and ``list`` projection path.
    """
    if not properties:
        return data

    normalized = _normalize_properties(properties)
    if not data:
        return data

    return _apply_properties_filter_shared(data, normalized)


def project_record(record: Dict, properties: Optional[Sequence[str]]) -> Dict:
    """Project a single CourseCraft record to ``--properties`` (the ``get`` path).

    Every ``get`` command holds exactly one already-existence-checked record and
    needs the same ``[record] -> project -> [0]`` idiom. Callers must pass a real
    record (guard with the ``if not record`` existence check first); when
    ``properties`` is falsy the record is returned unchanged.
    """
    return apply_properties_filter([record], properties)[0]


def warn_policy(rule: str, message: str) -> None:
    """Report a CourseCraft workflow reminder without blocking the operation.

    CourseCraft workflow rules are advisory in this CLI: lifecycle order,
    readiness, review state, and inheritance rules are reported here and
    enforced by the owning artifact's ``requirements.md`` / ``checks.json`` and
    by the reviewer, never by refusing a write. ``rule`` names the reminder so a
    reader can find the owning contract; ``message`` states what changed or what
    is not yet true.

    This is deliberately NOT used for broken input, unreadable contracts,
    missing records, or a write that failed to persist. Those are real errors
    and still raise.
    """
    yellow = "\033[93m"
    bold = "\033[1m"
    reset = "\033[0m"
    print(
        f"{yellow}{bold}⚠ REMINDER{reset} {yellow}[{rule}]{reset} {message}",
        file=sys.stderr,
    )


def print_mandatory_review(
    title: str,
    action: str,
    reason: str,
    preview: str | None = None,
):
    """Print a prominent mandatory review warning box.

    Args:
        title: What needs review (e.g., "Action Summary", "Script")
        action: What must be done (e.g., "update to match the new Script")
        reason: Why this is required
        preview: Optional preview of the existing content
    """
    red = "\033[91m"
    yellow = "\033[93m"
    bold = "\033[1m"
    reset = "\033[0m"

    print("", file=sys.stderr)
    print(f"{red}{bold}{'─' * 70}{reset}", file=sys.stderr)
    print(f"{red}{bold}🛑 MANDATORY REVIEW: {title}{reset}", file=sys.stderr)
    print(f"{red}{bold}{'─' * 70}{reset}", file=sys.stderr)
    print(f"{yellow}   Action Required: {action}{reset}", file=sys.stderr)
    print(f"   Reason: {reason}", file=sys.stderr)
    if preview:
        truncated = f"{preview[:80]}..." if len(preview) > 80 else preview
        print(f"   Preview: {truncated}", file=sys.stderr)
    print(f"{red}{bold}{'─' * 70}{reset}", file=sys.stderr)
    print("", file=sys.stderr)
