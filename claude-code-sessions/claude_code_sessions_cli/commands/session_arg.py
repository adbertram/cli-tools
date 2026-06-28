"""Shared resolution for the --session-id / --session-name command options.

Every command that accepts a session may receive it as:
- a positional/`--session-id` value (UUID or name, auto-detected), or
- an explicit `--session-name` value (always treated as a name).

These sources are mutually exclusive. This helper centralizes the exclusion
check and the resolve call so each command site stays a single line.
"""
from typing import Optional

import typer


def resolve_session_arg(
    client,
    session_id: Optional[str],
    session_name: Optional[str],
    project: Optional[str] = None,
) -> Optional[str]:
    """Resolve a session id/name pair to a session id.

    Args:
        client: ClaudeCodeSessionsClient (provides resolve_session_id).
        session_id: Positional/`--session-id` value (UUID or name), or None.
        session_name: Explicit `--session-name` value (always a name), or None.
        project: Optional project name to scope name resolution.

    Returns:
        The resolved session id, or None when neither source was provided
        (used by optional session filters).

    Raises:
        typer.BadParameter: if both sources are provided (usage error to
            stderr, non-zero exit). Never silently picks one.
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
    """Resolve a required session id/name pair to a session id.

    Like resolve_session_arg, but for commands where a session is mandatory:
    raises a usage error if neither source was provided.

    Raises:
        typer.BadParameter: if both sources are given, or if neither is.
    """
    resolved = resolve_session_arg(client, session_id, session_name, project=project)
    if resolved is None:
        raise typer.BadParameter(
            "provide a session via the positional argument, --session-id, "
            "or --session-name"
        )
    return resolved
