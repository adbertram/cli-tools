"""Goal commands for the DeepSeek Sessions CLI.

dsh's goal-round driver keeps a standing objective for a session and re-enters
the agent loop until it is satisfied or the round budget runs out. Each create,
update, or completion is a `goal/change` revision.
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

app = typer.Typer(help="Query standing goals and their revisions", no_args_is_help=True)


@app.command("list")
@command
def list_goals(
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., phase:eq:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List standing-goal revisions in a project.

    Example:
        deepseek-sessions goals list --project BricklinkBook --table
        deepseek-sessions goals list -p BricklinkBook --filter "phase:eq:active"
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project=project)
        goals = client.list_goals(
            project=project, session_id=resolved,
            limit=fetch_limit(limit, filter), since=since
        )
        items = to_items(goals)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_time(items, "timestamp", "time")
            blank_none(items, "phase")
            render_table(
                items,
                [("time", "Time"), ("session_id", "Session"), ("operation", "Operation"),
                 ("revision", "Rev"), ("phase", "Phase"), ("objective", "Objective")],
                [("rounds_started", "Rounds"), ("max_goal_rounds", "Max Rounds")],
                wide,
            )
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_goal(
    goal_id: str = typer.Argument(..., help="Goal ID"),
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get every recorded revision of one goal.

    Example:
        deepseek-sessions goals get goal-c6c1f5cf-b816-4ab4-90aa-59c6ef7987bb -p BricklinkBook
    """
    try:
        revisions = [
            item
            for item in get_client().list_goals(project, limit=1000000)
            if item.id == goal_id
        ]
        if not revisions:
            print_json({"error": f"Goal not found: {goal_id}"})
            raise typer.Exit(1)

        revisions.sort(key=lambda item: item.revision)
        latest = revisions[-1]

        if table:
            rows = [
                {"field": "ID", "value": latest.id},
                {"field": "Session", "value": latest.session_id},
                {"field": "Objective", "value": latest.objective},
                {"field": "Phase", "value": latest.phase or "N/A"},
                {"field": "Revisions", "value": str(len(revisions))},
                {"field": "Rounds Started", "value": str(latest.rounds_started or 0)},
                {"field": "Max Goal Rounds", "value": str(latest.max_goal_rounds or "N/A")},
                {"field": "Created", "value": format_local_time(latest.created_at or "")},
                {"field": "Updated", "value": format_local_time(latest.updated_at or "")},
            ]
            rows.extend(
                {
                    "field": f"Revision {item.revision} ({item.operation})",
                    "value": f"{format_local_time(item.timestamp)} phase={item.phase}",
                }
                for item in revisions
            )
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json([item.model_dump() for item in revisions])

    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
