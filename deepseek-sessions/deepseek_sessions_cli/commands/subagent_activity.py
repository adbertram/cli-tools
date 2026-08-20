"""Subagent activity commands for the DeepSeek Sessions CLI.

Each dsh subagent is a full session of its own. These commands join the child
session's cost and outcome to the parent's `subagent` tool call.
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
from .session_arg import resolve_session_arg

app = typer.Typer(help="Query subagent invocations", no_args_is_help=True)


@app.command("list")
@command
def list_subagent_activity(
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Parent session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Parent session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:error)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List every subagent session spawned inside a project.

    Example:
        deepseek-sessions subagent-activity list --project LegoScout --table
        deepseek-sessions subagent-activity list -p LegoScout --filter "status:eq:error"
        deepseek-sessions subagent-activity list -p CourseCraft -S session-0d8e00ea-2658-432c-89ed-7800d5b965bd
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project=project)
        subagents = client.list_subagent_activity(
            project=project, session_id=resolved,
            limit=fetch_limit(limit, filter), since=since
        )
        items = to_items(subagents)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_tokens(items)
            add_time(items, "timestamp", "started")
            blank_none(items, "model")
            render_table(
                items,
                [("id", "ID"), ("label", "Label"), ("started", "Started"),
                 ("status", "Status"), ("tool_call_count", "Tools"),
                 ("effective", "Effective")],
                [("model", "Model"), ("message_count", "Msgs"),
                 ("turn_count", "Turns"), ("retry_count", "Retries"),
                 ("error_count", "Errors"), ("in_tok", "In Tok"),
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
def get_subagent(
    subagent_id: str = typer.Argument(..., help="Subagent (child) session ID"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (auto-derived when omitted)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get full details for a subagent, including its child session messages.

    Example:
        deepseek-sessions subagent-activity get 72a1b775-435d-4a28-bd38-3f693adac2eb
    """
    try:
        subagent = get_client().get_subagent(subagent_id, project)

        if table:
            rows = [
                {"field": "ID", "value": subagent.id},
                {"field": "Label", "value": subagent.label},
                {"field": "Parent Session", "value": subagent.parent_session_id or "N/A"},
                {"field": "Parent Tool Call", "value": subagent.parent_tool_call_id or "N/A"},
                {"field": "Model", "value": subagent.model or "N/A"},
                {"field": "Mode", "value": subagent.mode or "N/A"},
                {"field": "Status", "value": subagent.status},
                {"field": "Created", "value": format_local_time(subagent.created_at)},
                {"field": "Completed", "value": format_local_time(subagent.completed_at or "") or "N/A"},
                {"field": "Messages", "value": str(len(subagent.messages))},
                {"field": "Prompt", "value": subagent.prompt[:300] or "N/A"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(subagent.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))
