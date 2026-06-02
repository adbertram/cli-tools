"""Timeline commands for Claude Code Sessions CLI."""
import json
import typer
from typing import Optional, List, Any
from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table, handle_error
from ..parsers import format_local_time_only

app = typer.Typer(help="View unified activity timeline", no_args_is_help=True)


def format_event_type(event_type: str) -> str:
    """Format event type for display."""
    # Handle enum objects by converting to string value
    if hasattr(event_type, 'value'):
        event_type = event_type.value
    labels = {
        'user_message': 'user',
        'assistant_message': 'assistant',
        'thinking': 'thinking',
        'agent_warmup': 'warmup',
        'skill': 'skill',
        'tool_call': 'tool',
        'subagent_start': 'agent',
        'subagent_tool': 'agent-tool',
        'error': 'error',
    }
    return labels.get(event_type, event_type)


def format_status(status: str) -> str:
    """Format status with symbols."""
    if status == 'error':
        return '✗'
    elif status == 'success':
        return '✓'
    elif status == 'invoked':
        return '→'
    return status or ''


def truncate_value(value: Any, max_length: int = 40) -> str:
    """Truncate a value for table display."""
    if value is None:
        return ''
    if isinstance(value, dict):
        # For dicts, show key summary or compact JSON
        text = json.dumps(value, separators=(',', ':'))
    elif isinstance(value, list):
        text = json.dumps(value, separators=(',', ':'))
    else:
        text = str(value)
    # Clean up newlines
    text = text.replace('\n', ' ').replace('\r', '')
    if len(text) > max_length:
        return text[:max_length - 3] + '...'
    return text


@app.command("list")
def list_timeline(
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter by session ID"),
    conversation_id: Optional[int] = typer.Option(None, "--conversation-id", "-C", help="Filter by conversation ID (requires --session-id)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show full input/output (no truncation)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum entries"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    errors_only: bool = typer.Option(False, "--errors-only", "-e", help="Show only errors"),
):
    """
    Show unified timeline of all activities.

    Combines skills, tool calls, subagent launches, and errors into one chronological view.

    Example:
        claude-code-sessions timeline list --project Agent-ATABlogger --since 1h
        claude-code-sessions timeline list --project Agent-ATABlogger --session-id abc123
        claude-code-sessions timeline list --project Agent-ATABlogger --errors-only
        claude-code-sessions timeline list --project Agent-ATABlogger --filter "event_type:eq:skill"
    """
    try:
        # Validate conversation_id requires session_id
        if conversation_id and not session_id:
            raise ClientError("--conversation-id requires --session-id")

        client = get_client()

        # Fetch more if we're filtering (apply limit after filters)
        fetch_limit = limit
        if session_id or conversation_id or errors_only:
            fetch_limit = 10000

        timeline = client.list_timeline(project=project, limit=fetch_limit, since=since)

        # Convert to dicts for filtering/output
        items = [e.model_dump() for e in timeline]

        # Apply session_id filter
        if session_id:
            items = [item for item in items if item.get('session_id') == session_id]

        # Apply conversation_id filter
        if conversation_id:
            items = [item for item in items if item.get('conversation_id') == conversation_id]

        # Apply errors-only filter
        if errors_only:
            items = [item for item in items if item.get('status') == 'error']

        # Apply client-side filters
        if filter:
            items = apply_filters(items, filter)

        # Apply limit after all filters
        items = items[:limit]

        if table:
            # Format for table display
            for item in items:
                item['type'] = format_event_type(item.get('event_type', ''))
                item['status'] = format_status(item.get('status', ''))
                # Format timestamp in local timezone (time only)
                item['time'] = format_local_time_only(item.get('timestamp', ''))
                # Format agent name for subagent tool calls
                item['agent'] = item.get('agent_name') or ''
                # Format input/output for display (full or truncated)
                if wide:
                    item['input_preview'] = truncate_value(item.get('input'), 10000)
                    item['output_preview'] = truncate_value(item.get('output'), 10000)
                else:
                    item['input_preview'] = truncate_value(item.get('input'), 50)
                    item['output_preview'] = truncate_value(item.get('output'), 50)
                # Format cost metrics for Claude Max tracking
                turn_cost = item.get('turn_cost')
                session_total = item.get('session_total')
                item['turn_cost_fmt'] = f"{turn_cost:,}" if turn_cost else ''
                item['session_total_fmt'] = f"{session_total:,}" if session_total else ''

            columns = ["time", "session_id", "type", "agent", "name", "status", "turn_cost_fmt", "session_total_fmt", "input_preview", "output_preview"]
            headers = ["Time", "Session", "Type", "Agent", "Name", "Status", "Turn Cost", "Session Total", "Input", "Output"]
            # Use unlimited columns when --wide is specified to show input/output
            print_table(items, columns, headers, max_columns=0 if wide else 8)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("consolidated")
def consolidated_timeline(
    session_id: str = typer.Option(..., "--session-id", "-S", help="Session UUID (required)"),
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show full input/output (no truncation)"),
    limit: int = typer.Option(500, "--limit", "-l", help="Maximum entries"),
    show_agent_tools: bool = typer.Option(True, "--show-agent-tools/--hide-agent-tools", help="Include subagent tool calls"),
    show_thinking: bool = typer.Option(False, "--show-thinking", help="Include Claude's thinking/reasoning blocks"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
):
    """
    Show ALL activity for a session in a single consolidated view.

    Combines user prompts, main agent tool calls, subagent launches, and subagent tool calls
    into one chronological timeline.

    Example:
        claude-code-sessions timeline consolidated --session-id abc123 --project Agent-ATABlogger
        claude-code-sessions timeline consolidated -S abc123 -p Agent-ATABlogger --table
        claude-code-sessions timeline consolidated -S abc123 -p Agent-ATABlogger --hide-agent-tools
        claude-code-sessions timeline consolidated -S abc123 -p Agent-ATABlogger --show-thinking
        claude-code-sessions timeline consolidated -S abc123 -p Agent-ATABlogger --filter "status:eq:error" --wide
    """
    try:
        client = get_client()
        timeline = client.get_timeline(session_id=session_id, project=project, limit=limit, show_thinking=show_thinking)

        # Convert to dicts
        items = [e.model_dump() for e in timeline]

        # Optionally filter out subagent tool calls
        if not show_agent_tools:
            items = [item for item in items if item.get('event_type') != 'subagent_tool']

        # Apply client-side filters
        if filter:
            items = apply_filters(items, filter)

        if table:
            # Format for table display
            for item in items:
                item['type'] = format_event_type(item.get('event_type', ''))
                item['status'] = format_status(item.get('status', ''))
                # Format timestamp in local timezone (time only)
                item['time'] = format_local_time_only(item.get('timestamp', ''))
                # Format agent name for subagent tool calls
                item['agent'] = item.get('agent_name') or ''
                # Format input/output for display (full or truncated)
                if wide:
                    item['input_preview'] = truncate_value(item.get('input'), 10000)
                    item['output_preview'] = truncate_value(item.get('output'), 10000)
                else:
                    item['input_preview'] = truncate_value(item.get('input'), 50)
                    item['output_preview'] = truncate_value(item.get('output'), 50)
                # Format cost metrics for Claude Max tracking
                turn_cost = item.get('turn_cost')
                session_total = item.get('session_total')
                item['turn_cost_fmt'] = f"{turn_cost:,}" if turn_cost else ''
                item['session_total_fmt'] = f"{session_total:,}" if session_total else ''

            columns = ["time", "type", "agent", "name", "status", "turn_cost_fmt", "session_total_fmt", "input_preview", "output_preview"]
            headers = ["Time", "Type", "Agent", "Name", "Status", "Turn Cost", "Session Total", "Input", "Output"]
            # Use unlimited columns when --wide is specified to show input/output
            print_table(items, columns, headers, max_columns=0 if wide else 7)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_timeline(
    session_id: str = typer.Argument(..., help="Session UUID"),
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show full input/output (no truncation)"),
    limit: int = typer.Option(200, "--limit", "-l", help="Maximum entries"),
):
    """
    Get timeline for a specific session.

    Example:
        claude-code-sessions timeline get abc123 --project Agent-ATABlogger
    """
    try:
        client = get_client()
        timeline = client.get_timeline(session_id=session_id, project=project, limit=limit)

        # Convert to dicts
        items = [e.model_dump() for e in timeline]

        if table:
            # Format for table display
            for item in items:
                item['type'] = format_event_type(item.get('event_type', ''))
                item['status'] = format_status(item.get('status', ''))
                # Format timestamp in local timezone (time only)
                item['time'] = format_local_time_only(item.get('timestamp', ''))
                # Format agent name for subagent tool calls
                item['agent'] = item.get('agent_name') or ''
                # Format input/output for display (full or truncated)
                if wide:
                    item['input_preview'] = truncate_value(item.get('input'), 10000)
                    item['output_preview'] = truncate_value(item.get('output'), 10000)
                else:
                    item['input_preview'] = truncate_value(item.get('input'), 50)
                    item['output_preview'] = truncate_value(item.get('output'), 50)
                # Format cost metrics for Claude Max tracking
                turn_cost = item.get('turn_cost')
                session_total = item.get('session_total')
                item['turn_cost_fmt'] = f"{turn_cost:,}" if turn_cost else ''
                item['session_total_fmt'] = f"{session_total:,}" if session_total else ''

            columns = ["time", "type", "agent", "name", "status", "turn_cost_fmt", "session_total_fmt", "input_preview", "output_preview"]
            headers = ["Time", "Type", "Agent", "Name", "Status", "Turn Cost", "Session Total", "Input", "Output"]
            # Use unlimited columns when --wide is specified to show input/output
            print_table(items, columns, headers, max_columns=0 if wide else 7)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
