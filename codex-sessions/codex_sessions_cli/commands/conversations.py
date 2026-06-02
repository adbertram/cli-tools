"""Conversation/turn commands."""
import typer
from typing import List, Optional

from ..client import get_client
from .common import emit_list, emit_one

app = typer.Typer(help="List and query Codex conversation turns", no_args_is_help=True)
COMMAND_CREDENTIALS = {"list": ["custom"], "get": ["custom"]}

CONVERSATION_COLUMNS = ["id", "project", "conversation_id", "last_activity", "message_count", "tool_call_count"]
CONVERSATION_HEADERS = ["ID", "Project", "Conversation", "Last Activity", "Messages", "Tools"]


@app.command("list")
def list_conversations(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    project_path: Optional[str] = typer.Option(None, "--project-path", help="Project folder path"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Filter to session"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields"),
):
    """List conversation turns within sessions."""
    items = get_client().list_conversations(project, project_path, session_id, since, limit)
    emit_list(items, table, CONVERSATION_COLUMNS, CONVERSATION_HEADERS, filter=filter, properties=properties)


@app.command("get")
def get_conversation(
    conversation_id: str = typer.Argument(..., help="Conversation ID: session_id:number"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """Get a specific conversation summary."""
    emit_one(get_client().get_conversation(conversation_id), table, CONVERSATION_COLUMNS, properties)
