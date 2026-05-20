"""Session commands for Claude Code Sessions CLI."""
import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table, handle_error
from ..parsers import (
    format_local_time,
    resolve_date_selector,
    parse_include_prompts,
    extract_user_prompts,
    parse_full_session,
    extract_project_name,
    encode_project_path,
)

app = typer.Typer(help="List and query sessions", no_args_is_help=True)


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
    """
    List sessions. With no --project / --project-path, returns sessions across all projects.

    Example:
        claude-code-sessions sessions list --project Agent-ATABlogger
        claude-code-sessions sessions list --date-alias yesterday --limit 5
        claude-code-sessions sessions list --date 2026-05-15 --min-tool-calls 1
        claude-code-sessions sessions list --date-alias yesterday --include-prompts first:3,last:3 --prompts-clean
    """
    # Mutual exclusion between --date / --date-range / --date-alias / --since
    date_selectors = [
        ("--date", date),
        ("--date-range", date_range),
        ("--date-alias", date_alias),
        ("--since", since),
    ]
    provided = [name for name, value in date_selectors if value]
    if len(provided) > 1:
        raise typer.BadParameter(
            "use only one of --date / --date-range / --date-alias / --since "
            f"(got {', '.join(provided)})"
        )

    # Resolve date window (raises ValueError on invalid input)
    try:
        date_bounds = resolve_date_selector(date, date_range, date_alias)
    except ValueError as e:
        raise typer.BadParameter(str(e))

    # Parse --include-prompts
    first_n = 0
    last_n = 0
    if include_prompts:
        try:
            first_n, last_n = parse_include_prompts(include_prompts)
        except ValueError as e:
            raise typer.BadParameter(str(e))

    resolved = project_path or project

    try:
        client = get_client()
        sessions = client.list_sessions(
            project=resolved,
            limit=limit,
            since=since,
            date_bounds=date_bounds,
            min_tool_calls=min_tool_calls,
        )

        # Convert to dicts for filtering/output
        items = [s.model_dump() for s in sessions]

        # Apply client-side filters
        if filter:
            items = apply_filters(items, filter)

        # Embed user prompts when requested. This requires reparsing the .jsonl
        # for each surviving session to get the full message list.
        if include_prompts and (first_n > 0 or last_n > 0):
            for item in items:
                session_id = item.get("id")
                project_path_val = item.get("project_path")
                if not session_id or not project_path_val:
                    item["first_user_prompts"] = []
                    item["last_user_prompts"] = []
                    continue
                encoded = encode_project_path(project_path_val)
                session_file = client.projects_dir / encoded / f"{session_id}.jsonl"
                if not session_file.exists():
                    item["first_user_prompts"] = []
                    item["last_user_prompts"] = []
                    continue
                proj_name = extract_project_name(encoded)
                session = parse_full_session(session_file, proj_name)
                msgs = session.messages if session else []
                prompts = extract_user_prompts(
                    msgs,
                    first_n=first_n,
                    last_n=last_n,
                    max_chars=prompts_max_chars,
                    clean=prompts_clean,
                )
                item["first_user_prompts"] = prompts["first_user_prompts"]
                item["last_user_prompts"] = prompts["last_user_prompts"]

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            items = [{k: v for k, v in item.items() if k in prop_list} for item in items]

        if table:
            # Format token counts and start time for display
            for item in items:
                input_tok = item.get('total_input_tokens', 0)
                output_tok = item.get('total_output_tokens', 0)
                cache_read = item.get('total_cache_read_tokens', 0)
                cache_create = item.get('total_cache_creation_tokens', 0)
                effective = item.get('effective_tokens', 0)
                item['in_tok'] = f"{input_tok:,}" if input_tok else ''
                item['out_tok'] = f"{output_tok:,}" if output_tok else ''
                item['cache_read'] = f"{cache_read:,}" if cache_read else ''
                item['cache_create'] = f"{cache_create:,}" if cache_create else ''
                item['effective'] = f"{effective:,}" if effective else ''
                # Format start time (created_at) in local timezone
                item['start_time'] = format_local_time(item.get('created_at', ''))
            columns = ["id", "project_path", "start_time", "message_count", "tool_call_count", "in_tok", "out_tok", "cache_read", "cache_create", "effective", "has_errors"]
            headers = ["ID", "Project Path", "Started", "Msgs", "Tools", "In Tok", "Out Tok", "Cache Read", "Cache Create", "Effective", "Errors"]
            print_table(items, columns, headers)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_session(
    session_id: str = typer.Argument(..., help="Session UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get full session details including messages and tool calls.

    Example:
        claude-code-sessions sessions get abc123-def456-789
    """
    try:
        client = get_client()
        session = client.get_session(session_id)

        if table:
            rows = [
                {"field": "ID", "value": session.id},
                {"field": "Project", "value": session.project},
                {"field": "Project Path", "value": session.project_path or "N/A"},
                {"field": "Created", "value": format_local_time(session.created_at)},
                {"field": "Last Activity", "value": format_local_time(session.last_activity)},
                {"field": "Messages", "value": str(len(session.messages))},
                {"field": "Subagents", "value": str(len(session.subagents))},
                {"field": "Todos", "value": str(len(session.todos))},
                {"field": "Errors", "value": str(len(session.errors))},
                {"field": "Git Branch", "value": session.git_branch or "N/A"},
                {"field": "CWD", "value": session.cwd or "N/A"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(session.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def search_sessions(
    query: str = typer.Argument(..., help="Search query"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    project_path: Optional[str] = typer.Option(None, "--project-path", help="Project folder path"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    Search for sessions containing a query string.

    Example:
        claude-code-sessions sessions search "authentication" --project Agent-ATABlogger
        claude-code-sessions sessions search "error" --project-path /path/to/project --since 1d
    """
    resolved = project_path or project
    if not resolved:
        raise typer.BadParameter("Either --project or --project-path is required")

    try:
        client = get_client()
        sessions = client.search_sessions(query=query, project=resolved, limit=limit, since=since)

        # Convert to dicts for filtering/output
        items = [s.model_dump() for s in sessions]

        # Apply client-side filters
        if filter:
            items = apply_filters(items, filter)

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            items = [{k: v for k, v in item.items() if k in prop_list} for item in items]

        if table:
            # Format token counts and start time for display
            for item in items:
                input_tok = item.get('total_input_tokens', 0)
                output_tok = item.get('total_output_tokens', 0)
                cache_read = item.get('total_cache_read_tokens', 0)
                cache_create = item.get('total_cache_creation_tokens', 0)
                effective = item.get('effective_tokens', 0)
                item['in_tok'] = f"{input_tok:,}" if input_tok else ''
                item['out_tok'] = f"{output_tok:,}" if output_tok else ''
                item['cache_read'] = f"{cache_read:,}" if cache_read else ''
                item['cache_create'] = f"{cache_create:,}" if cache_create else ''
                item['effective'] = f"{effective:,}" if effective else ''
                # Format start time (created_at) in local timezone
                item['start_time'] = format_local_time(item.get('created_at', ''))
            columns = ["id", "project_path", "start_time", "message_count", "tool_call_count", "in_tok", "out_tok", "cache_read", "cache_create", "effective"]
            headers = ["ID", "Project Path", "Started", "Msgs", "Tools", "In Tok", "Out Tok", "Cache Read", "Cache Create", "Effective"]
            print_table(items, columns, headers)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
