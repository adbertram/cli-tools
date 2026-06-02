"""Conversations commands for claude-code-sessions CLI."""
import typer
from typing import Optional, List

from ..client import get_client, ClientError
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table, handle_error
from ..parsers import format_local_time

app = typer.Typer(help="List conversations within sessions", no_args_is_help=True)


@app.command("list")
def list_conversations(
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-s", help="Filter to specific session"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    since: Optional[str] = typer.Option(None, "--since", help="Time filter: 5h, 1d, 7d"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to include"),
):
    """
    List conversations within sessions.

    A conversation is a chain of messages within a session, separated by /clear commands.

    Example:
        claude-code-sessions conversations list --project MyProject
        claude-code-sessions conversations list -p MyProject --session-id abc123
        claude-code-sessions conversations list -p MyProject --since 1d --table
        claude-code-sessions conversations list -p MyProject --filter "message_count:gt:10"
    """
    try:
        client = get_client()
        conversations = client.list_conversations(
            project=project,
            session_id=session_id,
            limit=limit,
            since=since,
        )

        # Convert to dicts for output
        items = [c.model_dump() for c in conversations]

        # Apply client-side filters
        if filter:
            items = apply_filters(items, filter)

        # Apply property selection
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            items = [{k: v for k, v in item.items() if k in prop_list} for item in items]

        if table:
            # Format token counts and timestamps for display
            for item in items:
                input_tok = item.get('total_input_tokens', 0)
                output_tok = item.get('total_output_tokens', 0)
                cache_read = item.get('total_cache_read_tokens', 0)
                cache_create = item.get('total_cache_creation_tokens', 0)
                effective = item.get('effective_tokens', 0)
                item['in_tok'] = f"{input_tok:,}" if input_tok else ''
                item['out_tok'] = f"{output_tok:,}" if output_tok else ''
                item['cache_read'] = f"{cache_read:,}" if cache_read else ''
                item['cache_create'] = f"{cache_create:,}" if cache_create else ''
                item['effective'] = f"{effective:,}" if effective else ''
                # Format timestamps in local timezone
                item['first_msg'] = format_local_time(item.get('created_at', ''))
                item['last_msg'] = format_local_time(item.get('ended_at', ''))
            columns = ["session_id", "conversation_id", "message_count", "first_msg", "last_msg", "in_tok", "out_tok", "cache_read", "cache_create", "effective"]
            headers = ["Session", "Conv", "Msgs", "First Msg", "Last Msg", "In Tok", "Out Tok", "Cache Read", "Cache Create", "Effective"]
            print_table(items, columns, headers, max_columns=0)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def get_conversation(
    conversation_id: str = typer.Argument(..., help="Conversation ID (session_id:conv_number, e.g. abc123:1)"),
    project: str = typer.Option(..., "--project", "-p", help="Project name (required)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get a specific conversation by ID.

    The conversation ID format is session_id:conversation_number (e.g., abc123:1).

    Example:
        claude-code-sessions conversations get abc123:1 --project MyProject
    """
    try:
        # Parse conversation_id as session_id:conv_number
        if ":" not in conversation_id:
            print_json({"error": "Conversation ID must be in format session_id:conv_number (e.g., abc123:1)"})
            raise typer.Exit(1)

        session_id, conv_num_str = conversation_id.rsplit(":", 1)
        try:
            conv_num = int(conv_num_str)
        except ValueError:
            print_json({"error": f"Invalid conversation number '{conv_num_str}'. Must be an integer."})
            raise typer.Exit(1)

        client = get_client()
        conversations = client.list_conversations(
            project=project,
            session_id=session_id,
        )

        # Find the matching conversation
        match = None
        for c in conversations:
            if c.conversation_id == conv_num:
                match = c
                break

        if not match:
            print_json({"error": f"Conversation {conv_num} not found in session '{session_id}'"})
            raise typer.Exit(1)

        item = match.model_dump()

        if table:
            rows = [
                {"field": "Session ID", "value": item.get("session_id", "")},
                {"field": "Conversation", "value": str(item.get("conversation_id", ""))},
                {"field": "Project", "value": item.get("project", "")},
                {"field": "Messages", "value": str(item.get("message_count", 0))},
                {"field": "User Messages", "value": str(item.get("user_message_count", 0))},
                {"field": "Assistant Messages", "value": str(item.get("assistant_message_count", 0))},
                {"field": "Tool Calls", "value": str(item.get("tool_call_count", 0))},
                {"field": "Created", "value": format_local_time(item.get("created_at", ""))},
                {"field": "Ended", "value": format_local_time(item.get("ended_at", ""))},
                {"field": "Input Tokens", "value": f"{item.get('total_input_tokens', 0):,}"},
                {"field": "Output Tokens", "value": f"{item.get('total_output_tokens', 0):,}"},
                {"field": "Effective Tokens", "value": f"{item.get('effective_tokens', 0):,}"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except typer.Exit:
        raise
    except ClientError as e:
        raise typer.Exit(handle_error(e))
