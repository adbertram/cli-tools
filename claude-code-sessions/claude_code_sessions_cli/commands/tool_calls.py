"""Tool call commands for Claude Code Sessions CLI."""
import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, print_json, print_table, handle_error
from ..parsers import format_local_time

app = typer.Typer(help="Query tool call history", no_args_is_help=True)


@app.command("list")
@command
def list_tool_calls(
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter to specific session"),
    conversation_id: Optional[int] = typer.Option(None, "--conversation-id", "-C", help="Filter to specific conversation (requires --session-id)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
    include_subagents: bool = typer.Option(False, "--include-subagents", "-a", help="Include tool calls from subagents"),
    subagent_id: Optional[str] = typer.Option(None, "--subagent-id", help="Filter to tool calls from a specific subagent (Task tool call ID)"),
):
    """
    List all tool calls for a project.

    Example:
        claude-code-sessions tool-calls list --project ExampleProject
        claude-code-sessions tool-calls list --project ExampleProject --since 1d
        claude-code-sessions tool-calls list --project ExampleProject --filter "status:eq:error"
        claude-code-sessions tool-calls list --project ExampleProject --filter "tool:eq:Bash"
        claude-code-sessions tool-calls list --project ExampleProject --include-subagents
        claude-code-sessions tool-calls list --project ExampleProject --subagent-id toolu_01ABC...
    """
    try:
        # Validate conversation_id requires session_id
        if conversation_id and not session_id:
            raise ClientError("--conversation-id requires --session-id")

        client = get_client()

        # If subagent_id is provided, automatically include subagents
        # and fetch more results since we'll filter after
        fetch_limit = limit
        if subagent_id or session_id or conversation_id:
            fetch_limit = 10000  # Fetch all, filter after
        if subagent_id:
            include_subagents = True

        tool_calls = client.list_tool_calls(project=project, limit=fetch_limit, since=since, include_subagents=include_subagents)

        # Convert to dicts for filtering/output
        items = [tc.model_dump() for tc in tool_calls]

        # Filter by session
        if session_id:
            items = [item for item in items if item.get('session_id') == session_id]

        # Filter by conversation (tool calls don't have conversation_id directly,
        # but we can add it later if needed - for now just filter session)
        # Note: Full conversation filtering would require extending the data model

        # Filter by specific subagent if requested
        if subagent_id:
            items = [item for item in items if item.get('parent_tool_call_id') == subagent_id]

        # Apply limit after all filters
        items = items[:limit]

        # Apply client-side filters
        if filter:
            items = apply_filters(items, filter)

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            items = [{k: v for k, v in item.items() if k in prop_list} for item in items]

        if table:
            # Format timestamps in local timezone
            for item in items:
                item['time'] = format_local_time(item.get('timestamp', ''))
            columns = ["id", "tool", "status", "is_sidechain", "time"]
            headers = ["ID", "Tool", "Status", "Subagent", "Time"]
            print_table(items, columns, headers)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_tool_call(
    tool_call_id: str = typer.Argument(..., help="Tool call ID"),
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific tool call.

    Example:
        claude-code-sessions tool-calls get toolu_123 --project ExampleProject
    """
    try:
        client = get_client()
        tool_call = client.get_tool_call(tool_call_id, project)

        if table:
            rows = [
                {"field": "ID", "value": tool_call.id},
                {"field": "Tool", "value": tool_call.tool},
                {"field": "Status", "value": tool_call.status},
                {"field": "Time", "value": format_local_time(tool_call.timestamp)},
                {"field": "Session", "value": tool_call.session_id},
                {"field": "Is Subagent", "value": str(tool_call.is_sidechain)},
            ]
            if tool_call.error:
                rows.append({"field": "Error", "value": str(tool_call.error)[:100]})
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(tool_call.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))
