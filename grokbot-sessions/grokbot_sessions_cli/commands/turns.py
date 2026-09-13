"""Turn commands for the Grok Bot Sessions CLI.

Grokbot encodes the turn index in each entry id: ``t<n>u`` is the user message
that opened turn ``n``, ``t<n>s<m>`` is an agent send inside it, and
``t<n>a<m>`` is an agent-authored room message. The turn index is 0-based.
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

app = typer.Typer(help="Query agent turns and the entries inside them", no_args_is_help=True)

LEAN = [
    ("agent_name", "Agent"),
    ("turn", "Turn"),
    ("started", "Started"),
    ("entry_count", "Entries"),
    ("tool_call_count", "Cards"),
    ("has_approval", "Approval"),
]
EXTRA = [
    ("agent_id", "Agent ID"),
    ("legacy_id", "Legacy ID"),
    ("message_count", "Msgs"),
    ("send_count", "Sends"),
    ("ended_at", "Ended"),
    ("user_text", "User"),
    ("agent_text", "Agent"),
]


@app.command("list")
@command
def list_turns(
    agent: Optional[List[str]] = typer.Option(None, "--agent", "-a", help="Agent id, legacy UUID, or name (repeatable; default: all agents)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., has_approval:eq:true)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List turns grouped from each agent's transcript, newest turn first.

    Example:
        grokbot-sessions turns list --table
        grokbot-sessions turns list --agent 5658aa56-122b-4f56-acd9-5102e4f39d1b --table
        grokbot-sessions turns list --filter "tool_call_count:gt:0"
    """
    try:
        client = get_client()
        agents = client.resolve_agents(agent)
        rows = client.list_turns(agents, limit=fetch_limit(limit, filter))
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            add_time(rows, "started_at", "started")
            render_table(rows, LEAN, EXTRA, wide)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_turn(
    turn_id: str = typer.Argument(..., help="Turn id: <agent legacy UUID>:t<turn>"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one turn with its entries in chronological order.

    Example:
        grokbot-sessions turns get 5658aa56-122b-4f56-acd9-5102e4f39d1b:t6 --table
    """
    try:
        row = get_client().get_turn(turn_id)

        if table:
            field_value_table(
                [
                    ("ID", row["id"]),
                    ("Agent", f"{row['agent_name']} ({row['agent_id']})"),
                    ("Turn", row["turn"]),
                    ("Started", row["started_at"]),
                    ("Ended", row["ended_at"]),
                    ("Entries", row["entry_count"]),
                    ("Messages", row["message_count"]),
                    ("Sends", row["send_count"]),
                    ("Cards", row["tool_call_count"]),
                    ("Has Approval", "yes" if row["has_approval"] else "no"),
                    ("User", row["user_text"]),
                    ("Agent", row["agent_text"]),
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
