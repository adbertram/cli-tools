"""Approval commands for the DeepSeek Sessions CLI.

dsh records a permission escalation the agent requested as `approval/asked`
(with the tool, the target call, and the stated reason) and the answer as
`approval/decided`. A row with no outcome was never answered.
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
from ._render import add_time, blank_none, fetch_limit, render_table, select_properties, to_items
from .session_arg import resolve_session_arg

app = typer.Typer(help="Query permission escalation requests", no_args_is_help=True)


@app.command("list")
@command
def list_approvals(
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., outcome:eq:allowed-once)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List permission escalation requests and their decisions.

    Example:
        deepseek-sessions approvals list --project BricklinkBook --table
        deepseek-sessions approvals list -p BricklinkBook --filter "outcome:eq:allowed-once"
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project=project)
        approvals = client.list_approvals(
            project=project, session_id=resolved,
            limit=fetch_limit(limit, filter), since=since
        )
        items = to_items(approvals)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_time(items, "timestamp", "asked")
            blank_none(items, "tool", "outcome")
            for item in items:
                latency = item.get("decision_latency_ms")
                item["latency"] = f"{latency / 1000:.1f}s" if latency else ""
            render_table(
                items,
                [("asked", "Asked"), ("session_id", "Session"), ("tool", "Tool"),
                 ("outcome", "Outcome"), ("latency", "Latency")],
                [("call_id", "Call ID"), ("reason", "Reason")],
                wide,
            )
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_approval(
    approval_id: str = typer.Argument(..., help="Approval ID"),
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for one approval request.

    Example:
        deepseek-sessions approvals get 49ff56e3-4b0a-4b1a-99d6-8aae2a288de7 -p BricklinkBook
    """
    try:
        row = next(
            (item for item in get_client().list_approvals(project, limit=1000000) if item.id == approval_id),
            None,
        )
        if row is None:
            print_json({"error": f"Approval not found: {approval_id}"})
            raise typer.Exit(1)

        if table:
            rows = [
                {"field": "ID", "value": row.id},
                {"field": "Session", "value": row.session_id},
                {"field": "Asked", "value": format_local_time(row.timestamp)},
                {"field": "Tool", "value": row.tool or "N/A"},
                {"field": "Call ID", "value": row.call_id or "N/A"},
                {"field": "Outcome", "value": row.outcome or "undecided"},
                {"field": "Decided", "value": format_local_time(row.decided_at or "") or "N/A"},
                {"field": "Latency", "value": f"{row.decision_latency_ms / 1000:.1f}s" if row.decision_latency_ms else "N/A"},
                {"field": "Reason", "value": row.reason or "N/A"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(row.model_dump())

    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
