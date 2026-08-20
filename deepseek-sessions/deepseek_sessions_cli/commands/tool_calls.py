"""Tool call commands for the DeepSeek Sessions CLI."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, handle_error, print_json, print_table

from ..client import ClientError, get_client
from ..parsers import format_local_time
from ._render import UNBOUNDED, add_time, format_status, select_properties, to_items, truncate_value
from .session_arg import resolve_session_arg

app = typer.Typer(help="Query tool call history", no_args_is_help=True)


@app.command("list")
@command
def list_tool_calls(
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show full input/output (no truncation)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., tool:eq:bash, status:eq:error)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
    include_subagents: bool = typer.Option(False, "--include-subagents", "-a", help="Include tool calls made inside subagent sessions"),
    subagent_id: Optional[str] = typer.Option(None, "--subagent-id", help="Only tool calls from one subagent (its child session ID)"),
    code_dispatch: bool = typer.Option(True, "--code-dispatch/--no-code-dispatch", help="Include run_code sub-calls (tool/code-dispatch)"),
):
    """
    List tool calls in a project.

    Example:
        deepseek-sessions tool-calls list --project LegoScout --table
        deepseek-sessions tool-calls list -p LegoScout --filter "tool:eq:bash"
        deepseek-sessions tool-calls list -p LegoScout --filter "status:eq:error" --wide --table
        deepseek-sessions tool-calls list -p LegoScout --include-subagents
        deepseek-sessions tool-calls list -p LegoScout --subagent-id 72a1b775-435d-4a28-bd38-3f693adac2eb
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project=project)

        # Filtering by subagent only makes sense with subagent rows present.
        if subagent_id:
            include_subagents = True

        rows = client.list_tool_calls(
            project=project,
            session_id=resolved,
            # Post-filters narrow the set, so fetch wide and cut at the end.
            limit=UNBOUNDED if (subagent_id or filter) else limit,
            since=since,
            include_subagents=include_subagents,
            include_code_dispatch=code_dispatch,
        )

        items = to_items(rows)
        if subagent_id:
            items = [item for item in items if item.get("session_id") == subagent_id]
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_time(items, "timestamp", "time")
            width = 10000 if wide else 50
            for item in items:
                item["status_symbol"] = format_status(item.get("status"))
                item["input_preview"] = truncate_value(item.get("input"), width)
                item["output_preview"] = truncate_value(item.get("result"), width)
            print_table(
                items,
                ["time", "session_id", "turn", "tool", "status_symbol", "is_sidechain",
                 "input_preview", "output_preview"],
                ["Time", "Session", "Turn", "Tool", "Status", "Subagent",
                 "Input", "Output"],
                max_columns=0 if wide else 8,
            )
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_tool_call(
    tool_call_id: str = typer.Argument(..., help="Tool call ID (dsh callId)"),
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific tool call.

    Example:
        deepseek-sessions tool-calls get call_00_3eobTHgeR5qdfDWKVuYA6448 --project LegoScout
    """
    try:
        tool_call = get_client().get_tool_call(tool_call_id, project)

        if table:
            rows = [
                {"field": "ID", "value": tool_call.id},
                {"field": "Tool", "value": tool_call.tool},
                {"field": "Status", "value": tool_call.status},
                {"field": "Time", "value": format_local_time(tool_call.timestamp)},
                {"field": "Session", "value": tool_call.session_id},
                {"field": "Turn / Step", "value": f"{tool_call.turn} / {tool_call.step}"},
                {"field": "From Subagent", "value": str(tool_call.is_sidechain)},
                {"field": "Input", "value": truncate_value(tool_call.input, 2000)},
                {"field": "Result", "value": (tool_call.result or "")[:2000]},
            ]
            if tool_call.error:
                rows.append({"field": "Error", "value": truncate_value(tool_call.error, 500)})
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(tool_call.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))
