"""Session commands for the DeepSeek Sessions CLI."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "search": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, handle_error, print_json, print_table

from ..client import ClientError, get_client
from ..parsers import (
    extract_user_prompts,
    format_local_time,
    parse_full_session,
    parse_include_prompts,
    resolve_date_selector,
)
from ._render import add_time, add_tokens, blank_none, fetch_limit, render_table, select_properties, to_items
from .session_arg import require_session_arg

app = typer.Typer(help="List and query sessions", no_args_is_help=True)

# Default table: what identifies a session and what it cost.
LEAN = [
    ("name", "Name"),
    ("id", "ID"),
    ("project", "Project"),
    ("start_time", "Started"),
    ("message_count", "Msgs"),
    ("tool_call_count", "Tools"),
    ("effective", "Effective"),
]
# --wide adds the model, the dsh-native fields, and the raw token breakdown.
EXTRA = [
    ("model", "Model"),
    ("origin", "Origin"),
    ("turn_count", "Turns"),
    ("retry_count", "Retries"),
    ("in_tok", "In Tok"),
    ("out_tok", "Out Tok"),
    ("cache_read", "Cache Read"),
    ("reasoning", "Reasoning"),
    ("has_errors", "Errors"),
]


def _render_session_table(items: List[dict], wide: bool) -> None:
    """Format session rows and print them as a table."""
    add_tokens(items)
    add_time(items, "created_at", "start_time")
    blank_none(items, "model", "origin")
    for item in items:
        # Blank rather than "None" when a session was never given a title.
        item["name"] = item.get("custom_title") or ""
    render_table(items, LEAN, EXTRA, wide)


@app.command("list")
@command
def list_sessions(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name, path, or directory key"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    date: Optional[str] = typer.Option(None, "--date", help="Sessions whose last activity falls on this local date (YYYY-MM-DD). Mutually exclusive with --date-range, --date-alias, --since."),
    date_range: Optional[str] = typer.Option(None, "--date-range", help="Inclusive local range START..END (YYYY-MM-DD..YYYY-MM-DD)."),
    date_alias: Optional[str] = typer.Option(None, "--date-alias", help="One of today, yesterday, this_week, last_week (ISO weeks, Monday-Sunday)."),
    min_tool_calls: Optional[int] = typer.Option(None, "--min-tool-calls", help="Drop sessions whose tool_call_count is below this threshold."),
    subagents: bool = typer.Option(True, "--subagents/--no-subagents", help="Include spawned subagent sessions (origin=subagent)"),
    include_prompts: Optional[str] = typer.Option(None, "--include-prompts", help="Embed first/last user prompts on each row. Format: first:N,last:N."),
    prompts_clean: bool = typer.Option(False, "--prompts-clean", help="With --include-prompts, skip harness-injected tag messages."),
    prompts_max_chars: int = typer.Option(400, "--prompts-max-chars", help="Truncate each embedded prompt to this many characters."),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., origin:eq:subagent, turn_count:gt:3)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List sessions. With no --project, returns sessions across all projects.

    Example:
        deepseek-sessions sessions list --table
        deepseek-sessions sessions list --project LegoScout --no-subagents
        deepseek-sessions sessions list --date-alias yesterday --limit 5
        deepseek-sessions sessions list --filter "origin:eq:subagent" --table
        deepseek-sessions sessions list --date-alias today --include-prompts first:2,last:1
    """
    provided = [
        name
        for name, value in (
            ("--date", date), ("--date-range", date_range),
            ("--date-alias", date_alias), ("--since", since),
        )
        if value
    ]
    if len(provided) > 1:
        raise typer.BadParameter(
            "use only one of --date / --date-range / --date-alias / --since "
            f"(got {', '.join(provided)})"
        )

    try:
        date_bounds = resolve_date_selector(date, date_range, date_alias)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    first_n = last_n = 0
    if include_prompts:
        try:
            first_n, last_n = parse_include_prompts(include_prompts)
        except ValueError as e:
            raise typer.BadParameter(str(e))

    try:
        client = get_client()
        sessions = client.list_sessions(
            project=project,
            limit=fetch_limit(limit, filter),
            since=since,
            date_bounds=date_bounds,
            min_tool_calls=min_tool_calls,
            include_subagents=subagents,
        )

        items = to_items(sessions)
        if filter:
            items = items
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items, None)

        if include_prompts and (first_n > 0 or last_n > 0):
            for item in items:
                log, project_name = client.load_session_log(item["id"])
                messages = parse_full_session(log, project_name).messages
                item.update(
                    extract_user_prompts(
                        messages,
                        first_n=first_n,
                        last_n=last_n,
                        max_chars=prompts_max_chars,
                        clean=prompts_clean,
                    )
                )

        items = items
        if None:
            items = apply_filters(items, None)
        items = select_properties(items[:limit], properties)

        if table:
            _render_session_table(items, wide)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_session(
    session_id: Optional[str] = typer.Argument(None, help="Session ID or title; omit when using --session-name"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get full session details including messages, tool calls, and subagents.

    Example:
        deepseek-sessions sessions get session-53a213f2-c5ac-4950-a2c7-8011f2281e55
        deepseek-sessions sessions get "Fix Lego deal run issues" --table
    """
    try:
        client = get_client()
        session = client.get_session(require_session_arg(client, session_id, session_name))

        if table:
            rows = [
                {"field": "ID", "value": session.id},
                {"field": "Title", "value": session.custom_title or "N/A"},
                {"field": "Project", "value": session.project},
                {"field": "CWD", "value": session.cwd or "N/A"},
                {"field": "Created", "value": format_local_time(session.created_at)},
                {"field": "Last Activity", "value": format_local_time(session.last_activity)},
                {"field": "Model", "value": session.model or "N/A"},
                {"field": "Provider", "value": session.provider or "N/A"},
                {"field": "Context Window", "value": str(session.context_window or "N/A")},
                {"field": "Origin", "value": session.origin or "root"},
                {"field": "Parent Session", "value": session.parent_session or "N/A"},
                {"field": "Delegation Depth", "value": str(session.delegation_depth)},
                {"field": "Agent Preset", "value": session.agent_preset or "N/A"},
                {"field": "Permission Preset", "value": session.permission_preset or "N/A"},
                {"field": "Sandbox Mode", "value": session.sandbox_mode or "N/A"},
                {"field": "Approval Policy", "value": session.approval_policy or "N/A"},
                {"field": "Messages", "value": str(len(session.messages))},
                {"field": "Subagents", "value": str(len(session.subagents))},
                {"field": "Todos", "value": str(len(session.todos))},
                {"field": "Errors", "value": str(len(session.errors))},
                {"field": "Truncated Log", "value": str(session.truncated)},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(session.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
@command
def search_sessions(
    query: str = typer.Argument(..., help="Search query"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name, path, or directory key"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Search for sessions whose transcript contains a query string.

    Returns session summaries. Use `search run` for matching snippets.

    Example:
        deepseek-sessions sessions search "legoscout"
        deepseek-sessions sessions search "timeout" --since 7d --table
    """
    try:
        sessions = get_client().search_sessions(
            query=query, project=project, limit=fetch_limit(limit, filter), since=since
        )
        items = to_items(sessions)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            _render_session_table(items, wide)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
