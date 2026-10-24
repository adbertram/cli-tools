"""Shared option handling for the scoped list commands.

Every message-derived group accepts the same scope: an optional session (by id
or title), an optional project, an optional source, and exactly one time
selector. Resolving that once keeps each command site short and keeps the
mutual-exclusion rules identical across groups.
"""
from typing import Optional, Tuple

import typer

from ..parsers import parse_since, resolve_date_selector


def resolve_session_arg(
    client,
    session_id: Optional[str],
    session_name: Optional[str],
    project: Optional[str] = None,
) -> Optional[str]:
    """Resolve an id/title pair to a session id, or None when neither is given.

    Raises:
        typer.BadParameter: when both are supplied. It never silently picks one.
    """
    if session_id is not None and session_name is not None:
        raise typer.BadParameter(
            "use only one of --session-id / --session-name, not both"
        )
    value = session_id if session_id is not None else session_name
    if value is None:
        return None
    return client.resolve_session_id(value, project=project)


def require_session_arg(
    client,
    session_id: Optional[str],
    session_name: Optional[str],
    project: Optional[str] = None,
) -> str:
    """Resolve a required id/title pair to a session id."""
    resolved = resolve_session_arg(client, session_id, session_name, project=project)
    if resolved is None:
        raise typer.BadParameter(
            "provide a session via the positional argument, --session-id, or --session-name"
        )
    return resolved


def resolve_time_scope(
    since: Optional[str] = None,
    date: Optional[str] = None,
    date_range: Optional[str] = None,
    date_alias: Optional[str] = None,
) -> Tuple[Optional[float], Optional[Tuple[float, float]]]:
    """Resolve the mutually exclusive time selectors to (since, date_bounds)."""
    provided = [
        name
        for name, value in (
            ("--since", since), ("--date", date),
            ("--date-range", date_range), ("--date-alias", date_alias),
        )
        if value
    ]
    if len(provided) > 1:
        raise typer.BadParameter(
            "use only one of --since / --date / --date-range / --date-alias "
            f"(got {', '.join(provided)})"
        )
    try:
        return parse_since(since), resolve_date_selector(date, date_range, date_alias)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))
