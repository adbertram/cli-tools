"""Conversation commands for the DeepSeek Sessions CLI.

dsh has no `/clear`. A conversation is the run of turns between context
compactions; a session that was never compacted has exactly one.
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

app = typer.Typer(help="List conversations within sessions", no_args_is_help=True)


@app.command("list")
@command
def list_conversations(
    project: str = typer.Option(..., "--project", "-p", help="Project name, path, or directory key (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-S", help="Session ID or title"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title (exact, case-insensitive)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., started_by:eq:compaction)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List conversations within a project's sessions.

    Example:
        deepseek-sessions conversations list --project LegoScout
        deepseek-sessions conversations list -p LegoScout --session-id session-53a213f2-c5ac-4950-a2c7-8011f2281e55
        deepseek-sessions conversations list -p LegoScout --filter "started_by:eq:compaction" --table
    """
    try:
        client = get_client()
        resolved = resolve_session_arg(client, session_id, session_name, project=project)
        conversations = client.list_conversations(
            project=project, session_id=resolved,
            limit=fetch_limit(limit, filter), since=since
        )
        items = to_items(conversations)
        if filter:
            items = apply_filters(items, filter)
        items = select_properties(items[:limit], properties)

        if table:
            add_tokens(items)
            add_time(items, "created_at", "first_msg")
            add_time(items, "ended_at", "last_msg")
            blank_none(items, "model")
            render_table(
                items,
                [("session_id", "Session"), ("conversation_id", "Conv"),
                 ("started_by", "Started By"), ("message_count", "Msgs"),
                 ("first_msg", "First Msg"), ("last_msg", "Last Msg"),
                 ("effective", "Effective")],
                [("model", "Model"), ("turn_count", "Turns"),
                 ("tool_call_count", "Tools"), ("in_tok", "In Tok"),
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
def get_conversation(
    conversation_id: Optional[str] = typer.Argument(None, help="Conversation ID (session:number, e.g. session-abc:1); omit when using --session-name"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (auto-derived from the session when omitted)"),
    session_name: Optional[str] = typer.Option(None, "--session-name", "-N", help="Session title; requires --conversation-id"),
    conv_number: Optional[int] = typer.Option(None, "--conversation-id", "-C", help="Conversation number (used with --session-name)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one conversation, including its user and assistant messages.

    Identify it either positionally as session:number, or with --session-name
    plus --conversation-id. The number is split off the right, so titles that
    contain a colon still work.

    Example:
        deepseek-sessions conversations get session-53a213f2-c5ac-4950-a2c7-8011f2281e55:1
        deepseek-sessions conversations get --session-name "Fix Lego deal run issues" -C 1
    """
    try:
        if conversation_id is not None and session_name is not None:
            raise typer.BadParameter(
                "use either the positional session:conv argument or --session-name "
                "(with --conversation-id), not both"
            )

        if session_name is not None:
            if conv_number is None:
                raise typer.BadParameter("--session-name requires --conversation-id")
            session_arg, number = session_name, conv_number
        else:
            if conversation_id is None:
                raise typer.BadParameter(
                    "provide session:conv as the positional argument, or use "
                    "--session-name with --conversation-id"
                )
            if ":" not in conversation_id:
                raise typer.BadParameter(
                    "Conversation ID must be session_id:conv_number (e.g., session-abc:1)"
                )
            session_arg, raw = conversation_id.rsplit(":", 1)
            try:
                number = int(raw)
            except ValueError:
                raise typer.BadParameter(
                    f"Invalid conversation number {raw!r}. Must be an integer."
                )

        client = get_client()
        resolved = client.resolve_session_id(session_arg, project=project)
        conversation = client.get_conversation(project, resolved, number)

        if conversation is None:
            print_json({"error": f"Conversation {number} not found in session '{resolved}'"})
            raise typer.Exit(1)

        item = conversation.model_dump()

        if table:
            rows = [
                {"field": "Session ID", "value": item["session_id"]},
                {"field": "Conversation", "value": str(item["conversation_id"])},
                {"field": "Started By", "value": item["started_by"]},
                {"field": "Project", "value": item["project"]},
                {"field": "Model", "value": item.get("model") or "N/A"},
                {"field": "Messages", "value": str(item["message_count"])},
                {"field": "User Messages", "value": str(item["user_message_count"])},
                {"field": "Assistant Messages", "value": str(item["assistant_message_count"])},
                {"field": "Tool Calls", "value": str(item["tool_call_count"])},
                {"field": "Turns", "value": str(item["turn_count"])},
                {"field": "Created", "value": format_local_time(item["created_at"])},
                {"field": "Ended", "value": format_local_time(item.get("ended_at") or "")},
                {"field": "Input Tokens", "value": f"{item['total_input_tokens']:,}"},
                {"field": "Output Tokens", "value": f"{item['total_output_tokens']:,}"},
                {"field": "Cache Read Tokens", "value": f"{item['total_cache_read_tokens']:,}"},
                {"field": "Reasoning Tokens", "value": f"{item['total_reasoning_tokens']:,}"},
                {"field": "Effective Tokens", "value": f"{item['effective_tokens']:,}"},
            ]
            rows.extend(
                {
                    "field": f"Message {index} ({message.get('type', '')})",
                    "value": message.get("content", ""),
                }
                for index, message in enumerate(item.get("messages", []), start=1)
            )
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
