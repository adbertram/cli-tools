"""Timeline commands."""
import typer
from typing import List, Optional

from ..client import get_client
from .common import emit_list, emit_one

app = typer.Typer(help="View Codex session activity timelines", no_args_is_help=True)
COMMAND_CREDENTIALS = {"list": ["custom"], "consolidated": ["custom"], "get": ["custom"]}

TIMELINE_COLUMNS = ["time", "session_id", "event_type", "name", "status", "text"]
TIMELINE_HEADERS = ["Time", "Session", "Type", "Name", "Status", "Text"]


@app.command("list")
def list_timeline(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    project_path: Optional[str] = typer.Option(None, "--project-path", help="Project folder path"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter to session"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum entries"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields"),
    errors_only: bool = typer.Option(False, "--errors-only", "-e", help="Show only error events"),
):
    """List timeline events across sessions."""
    items = get_client().list_timeline(project, project_path, session_id, since, limit=limit)
    if errors_only:
        items = [item for item in items if item.status in {"error", "failed", "timed_out"}]
    emit_list(items[:limit], table, TIMELINE_COLUMNS, TIMELINE_HEADERS, filter=filter, properties=properties)


@app.command("consolidated")
def consolidated_timeline(
    session_id: str = typer.Option(..., "--session-id", "-S", help="Session UUID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(500, "--limit", "-l", help="Maximum entries"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
    show_agent_tools: bool = typer.Option(True, "--show-agent-tools/--hide-agent-tools", help="Accepted for CLI parity"),
):
    """Show all activity for a single session in chronological order."""
    items = get_client().get_timeline(session_id, limit=limit)
    emit_list(items, table, TIMELINE_COLUMNS, TIMELINE_HEADERS, filter=filter, properties=properties)


@app.command("get")
def get_timeline(
    event_id: str = typer.Argument(..., help="Timeline event ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """Get a single timeline event by ID."""
    emit_one(get_client().get_timeline_event(event_id), table, TIMELINE_COLUMNS, properties=properties)
