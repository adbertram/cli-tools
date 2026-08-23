"""Turn commands for the DeepSeek Sessions CLI.

dsh brackets its agent loop explicitly: `turn/start` opens a turn, each model
round-trip inside it is a `step/start` / `step/end` pair, and `turn/end` closes
it with a reason of completed, error, or aborted. Claude Code writes no
equivalent record, so this group is dsh-native.
"""
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
from ._render import add_time, add_tokens, blank_none, fetch_limit, render_table, select_properties, to_items
from .session_arg import require_session_arg, resolve_session_arg

app = typer.Typer(help="Query agent turns and their steps", no_args_is_help=True)


@app.command("list")
@command
def list_turns(
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., finish_reason:eq:error)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List agent turns with their finish reason, duration, and token cost.

    Example:
        deepseek-sessions turns list --project LegoScout --table
        deepseek-sessions turns list -p LegoScout --filter "finish_reason:eq:error"
        deepseek-sessions turns list -p CourseCraft -S session-0d8e00ea-2658-432c-89ed-7800d5b965bd --table
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project=project)
        turns = client.list_turns(
            project=project, session_id=resolved,
            limit=fetch_limit(limit, filter), since=since
        )
        items = to_items(turns)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_tokens(items)
            add_time(items, "started_at", "started")
            blank_none(items, "model", "finish_reason")
            for item in items:
                duration = item.get("duration_ms")
                item["duration"] = f"{duration / 1000:.1f}s" if duration else ""
            render_table(
                items,
                [("session_id", "Session"), ("turn", "Turn"), ("started", "Started"),
                 ("duration", "Duration"), ("finish_reason", "Finish"),
                 ("tool_call_count", "Tools"), ("effective", "Effective")],
                [("model", "Model"), ("step_count", "Steps"),
                 ("retry_count", "Retries"), ("in_tok", "In Tok"),
                 ("out_tok", "Out Tok"), ("cache_read", "Cache Read"),
                 ("reasoning", "Reasoning")],
                wide,
            )
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_turn(
    turn: int = typer.Argument(..., help="Turn number within the session"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (auto-derived when omitted)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one turn plus the model round-trips (steps) inside it.

    Example:
        deepseek-sessions turns get 3 -S session-0d8e00ea-2658-432c-89ed-7800d5b965bd --table
    """
    try:
        client = get_client()
        resolved = require_session_arg(client, session_id, session_name, project=project)
        summary, steps = client.get_turn(resolved, turn)

        if table:
            rows = [
                {"field": "Session", "value": summary.session_id},
                {"field": "Turn", "value": str(summary.turn)},
                {"field": "Started", "value": format_local_time(summary.started_at)},
                {"field": "Ended", "value": format_local_time(summary.ended_at or "") or "N/A"},
                {"field": "Duration", "value": f"{summary.duration_ms / 1000:.1f}s" if summary.duration_ms else "N/A"},
                {"field": "Finish Reason", "value": summary.finish_reason or "N/A"},
                {"field": "Error", "value": summary.error_message or "N/A"},
                {"field": "Model", "value": summary.model or "N/A"},
                {"field": "Steps", "value": str(summary.step_count)},
                {"field": "Tool Calls", "value": str(summary.tool_call_count)},
                {"field": "Retries", "value": str(summary.retry_count)},
                {"field": "Input Tokens", "value": f"{summary.total_input_tokens:,}"},
                {"field": "Output Tokens", "value": f"{summary.total_output_tokens:,}"},
                {"field": "Cache Read Tokens", "value": f"{summary.total_cache_read_tokens:,}"},
                {"field": "Reasoning Tokens", "value": f"{summary.total_reasoning_tokens:,}"},
                {"field": "Effective Tokens", "value": f"{summary.effective_tokens:,}"},
            ]
            rows.extend(
                {
                    "field": f"Step {step.step}",
                    "value": (
                        f"{format_local_time(step.started_at)} "
                        f"tools={step.tool_call_count} "
                        f"in={step.input_tokens or 0} out={step.output_tokens or 0} "
                        f"cache={step.cache_read_tokens or 0}"
                    ),
                }
                for step in steps
            )
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(
                {
                    **summary.model_dump(),
                    "steps": [step.model_dump() for step in steps],
                }
            )

    except ClientError as e:
        raise typer.Exit(handle_error(e))
