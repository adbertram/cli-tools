"""Session commands."""
from pathlib import Path
from typing import List, Optional

import typer

from ..client import get_client
from ..parsers import (
    extract_user_prompts,
    parse_include_prompts,
    resolve_date_selector,
)
from .common import emit_list, emit_one, model_to_dict

app = typer.Typer(help="List, get, and search Codex sessions", no_args_is_help=True)
COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"], "search": ["custom"]}

SESSION_COLUMNS = ["id", "project", "last_activity", "message_count", "tool_call_count", "has_errors"]
SESSION_HEADERS = ["ID", "Project", "Last Activity", "Messages", "Tools", "Errors"]


@app.command("list")
def list_sessions(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    project_path: Optional[str] = typer.Option(None, "--project-path", help="Project folder path"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    date: Optional[str] = typer.Option(None, "--date", help="Filter to sessions whose last_activity falls on this local-calendar date (YYYY-MM-DD). Mutually exclusive with --date-range, --date-alias, --since."),
    date_range: Optional[str] = typer.Option(None, "--date-range", help="Inclusive local-calendar range START..END (YYYY-MM-DD..YYYY-MM-DD). Mutually exclusive with --date, --date-alias, --since."),
    date_alias: Optional[str] = typer.Option(None, "--date-alias", help="One of today, yesterday, this_week, last_week (ISO weeks, Monday-Sunday). Mutually exclusive with --date, --date-range, --since."),
    min_tool_calls: Optional[int] = typer.Option(None, "--min-tool-calls", help="Drop sessions whose tool_call_count is below this threshold."),
    include_prompts: Optional[str] = typer.Option(None, "--include-prompts", help="Embed first/last user prompts on each session row. Format: first:N,last:N (either part optional, e.g., first:3 or first:3,last:3)."),
    prompts_clean: bool = typer.Option(False, "--prompts-clean", help="When --include-prompts is set, skip system reminders, Caveat: lines, and tool-result content."),
    prompts_max_chars: int = typer.Option(400, "--prompts-max-chars", help="Truncate each embedded prompt to this many characters (default 400)."),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """List Codex sessions."""
    # Mutual exclusion: --date / --date-range / --date-alias / --since
    selectors = [
        ("--date", date),
        ("--date-range", date_range),
        ("--date-alias", date_alias),
        ("--since", since),
    ]
    provided = [name for name, val in selectors if val is not None]
    if len(provided) > 1:
        raise typer.BadParameter(
            f"--date, --date-range, --date-alias, and --since are mutually exclusive "
            f"(got: {', '.join(provided)}). Use only one."
        )

    try:
        date_window = resolve_date_selector(date, date_range, date_alias)
    except ValueError as error:
        raise typer.BadParameter(str(error))

    if include_prompts is not None:
        try:
            first_n, last_n = parse_include_prompts(include_prompts)
        except ValueError as error:
            raise typer.BadParameter(str(error))
        if prompts_max_chars <= 0:
            raise typer.BadParameter("--prompts-max-chars must be > 0")
    else:
        first_n = last_n = 0

    items = get_client().list_sessions(
        project,
        project_path,
        since,
        limit,
        date_window=date_window,
        min_tool_calls=min_tool_calls,
    )

    if include_prompts is not None:
        rows = []
        for item in items:
            row = model_to_dict(item)
            rollout_path = Path(row["path"])
            prompts = extract_user_prompts(
                rollout_path,
                first_n=first_n,
                last_n=last_n,
                max_chars=prompts_max_chars,
                clean=prompts_clean,
            )
            row["first_user_prompts"] = prompts["first_user_prompts"]
            row["last_user_prompts"] = prompts["last_user_prompts"]
            rows.append(row)
        emit_list(rows, table, SESSION_COLUMNS, SESSION_HEADERS, filter=filter, properties=properties)
        return

    emit_list(items, table, SESSION_COLUMNS, SESSION_HEADERS, filter=filter, properties=properties)


@app.command("get")
def get_session(
    session_id: str = typer.Argument(..., help="Session/thread UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """Get full details for a session."""
    emit_one(get_client().get_session(session_id), table, SESSION_COLUMNS, properties)


@app.command("search")
def search_sessions(
    query: str = typer.Argument(..., help="Search query"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    project_path: Optional[str] = typer.Option(None, "--project-path", help="Project folder path"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields"),
):
    """Search Codex session transcript content."""
    items = get_client().search_sessions(query, project, project_path, since, limit)
    emit_list(items, table, SESSION_COLUMNS, SESSION_HEADERS, filter=filter, properties=properties)
