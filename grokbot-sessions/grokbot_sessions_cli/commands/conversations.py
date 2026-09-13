"""Conversation commands for the Grok Bot Sessions CLI.

Grokbot calls the transcript epoch a ``generation``. One agent has one
conversation per generation; ``list`` is the index (entry, message, and turn
counts plus last activity) and ``get`` returns the decoded entries.
"""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.output import command, handle_error, print_json

from ..client import ClientError, get_client
from ._render import add_time, apply_row_filters, fetch_limit, field_value_table, render_table, select_properties

app = typer.Typer(help="List conversations within agents", no_args_is_help=True)

LEAN = [
    ("agent_name", "Agent"),
    ("generation", "Gen"),
    ("entry_count", "Entries"),
    ("turn_count", "Turns"),
    ("message_count", "Msgs"),
    ("last", "Last Activity"),
]
EXTRA = [
    ("agent_id", "Agent ID"),
    ("legacy_id", "Legacy ID"),
    ("send_count", "Sends"),
    ("event_count", "Events"),
    ("created", "Created"),
    ("first_prompt", "First Prompt"),
]


@app.command("list")
@command
def list_conversations(
    agent: Optional[List[str]] = typer.Option(None, "--agent", "-a", help="Agent id, legacy UUID, or name (repeatable; default: all agents)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., generation:eq:1)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List one conversation per agent generation, with entry and turn counts.

    Example:
        grokbot-sessions conversations list --table
        grokbot-sessions conversations list --agent 5658aa56-122b-4f56-acd9-5102e4f39d1b --table
        grokbot-sessions conversations list --filter "turn_count:gt:5"
    """
    try:
        client = get_client()
        agents = client.resolve_agents(agent)
        rows = client.list_conversations(agents, limit=fetch_limit(limit, filter))
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            add_time(rows, "last_activity", "last")
            add_time(rows, "created_at", "created")
            render_table(rows, LEAN, EXTRA, wide)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_conversation(
    conversation_id: str = typer.Argument(..., help="Conversation id: <agent legacy UUID>:<generation>"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one conversation with its decoded transcript entries.

    Example:
        grokbot-sessions conversations get 5658aa56-122b-4f56-acd9-5102e4f39d1b:1 --table
    """
    try:
        row = get_client().get_conversation(conversation_id)

        if table:
            field_value_table(
                [
                    ("ID", row["id"]),
                    ("Agent", f"{row['agent_name']} ({row['agent_id']})"),
                    ("Legacy ID", row["legacy_id"]),
                    ("Generation", row["generation"]),
                    ("Entries", row["entry_count"]),
                    ("Messages", row["message_count"]),
                    ("Sends", row["send_count"]),
                    ("Events", row["event_count"]),
                    ("Turns", row["turn_count"]),
                    ("Created", row["created_at"]),
                    ("Last Activity", row["last_activity"]),
                    ("First Prompt", row["first_prompt"]),
                    (
                        "Entries",
                        " | ".join(
                            f"{entry['entry_id']}[{entry['kind']}] {entry['summary']}"
                            for entry in row["entries"]
                        ),
                    ),
                ]
            )
        else:
            print_json(row)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
