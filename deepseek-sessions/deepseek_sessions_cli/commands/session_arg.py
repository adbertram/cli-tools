"""Shared resolution for the --session-id / --session-name command options.

A session may arrive as a positional/`--session-id` value (an id or a title,
auto-detected) or as an explicit `--session-name`. The two are mutually
exclusive; this helper enforces that once so each command site stays one line.
"""
from typing import Optional

import typer


def resolve_session_arg(
    client,
    session_id: Optional[str],
    session_name: Optional[str],
    project: Optional[str] = None,
) -> Optional[str]:
    """Resolve an id/name pair to a session id, or None when neither is given.

    Raises:
        typer.BadParameter: if both sources are provided. It never silently
            picks one.
    """
    if session_id is not None and session_name is not None:
        raise typer.BadParameter(
            "use only one of --session-id / --session-name (or the positional "
            "session argument), not both"
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
    """Resolve a required id/name pair to a session id."""
    resolved = resolve_session_arg(client, session_id, session_name, project=project)
    if resolved is None:
        raise typer.BadParameter(
            "provide a session via the positional argument, --session-id, "
            "or --session-name"
        )
    return resolved
