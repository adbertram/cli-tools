"""Subagent activity commands."""
import typer
from typing import List, Optional

from ..client import get_client
from .common import emit_list, emit_one

app = typer.Typer(help="Query Codex subagent invocations", no_args_is_help=True)
COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"]}

SUBAGENT_COLUMNS = ["time", "session_id", "agent_type", "name", "status"]
SUBAGENT_HEADERS = ["Time", "Session", "Agent Type", "Name", "Status"]


@app.command("list")
def list_subagent_activity(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    project_path: Optional[str] = typer.Option(None, "--project-path", help="Project folder path"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter to session"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields"),
):
    """List subagent launches recorded as spawn-agent tool calls."""
    items = get_client().list_subagent_activity(project, project_path, session_id, since, limit)
    emit_list(items, table, SUBAGENT_COLUMNS, SUBAGENT_HEADERS, filter=filter, properties=properties)


@app.command("get")
def get_subagent_activity(
    subagent_id: str = typer.Argument(..., help="Subagent/tool call ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """Get a specific subagent invocation."""
    emit_one(get_client().get_subagent_activity(subagent_id), table, SUBAGENT_COLUMNS, properties)
