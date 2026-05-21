"""Tool call commands."""
import typer
from typing import List, Optional

from ..client import get_client
from .common import emit_list, emit_one

app = typer.Typer(help="Query Codex tool call history", no_args_is_help=True)
COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"]}

TOOL_COLUMNS = ["time", "session_id", "name", "status", "exit_code"]
TOOL_HEADERS = ["Time", "Session", "Tool", "Status", "Exit"]


@app.command("list")
def list_tool_calls(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    project_path: Optional[str] = typer.Option(None, "--project-path", help="Project folder path"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter to session"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields"),
    include_subagents: bool = typer.Option(False, "--include-subagents", "-a", help="Accepted for CLI parity"),
):
    """List tool calls recorded in Codex transcripts."""
    items = get_client().list_tool_calls(project, project_path, session_id, since, limit, include_subagents)
    emit_list(items, table, TOOL_COLUMNS, TOOL_HEADERS, filter=filter, properties=properties)


@app.command("get")
def get_tool_call(
    tool_call_id: str = typer.Argument(..., help="Tool call ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """Get a specific tool call."""
    emit_one(get_client().get_tool_call(tool_call_id), table, TOOL_COLUMNS, properties)
