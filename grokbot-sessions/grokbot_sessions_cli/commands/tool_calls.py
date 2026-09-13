"""Tool call commands for the Grok Bot Sessions CLI.

Grokbot has no tool-call stream. Its tools surface as interactive cards on the
agent's send messages, so every row here is derived from a
``local-tool-permission``, ``cursor-agent``, ``user-form``, or ``widget`` card
and is marked ``source: card`` rather than presented as native tool telemetry.
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

app = typer.Typer(help="Query tool call cards", no_args_is_help=True)

LEAN = [
    ("time", "Time"),
    ("agent_name", "Agent"),
    ("turn", "Turn"),
    ("tool", "Tool"),
    ("card_type", "Card"),
    ("status", "Status"),
    ("target", "Target"),
]
EXTRA = [
    ("entry_id", "Entry ID"),
    ("agent_id", "Agent ID"),
    ("legacy_id", "Legacy ID"),
    ("source", "Source"),
    ("action", "Action"),
    ("title", "Title"),
    ("request_id", "Request ID"),
    ("summary", "Summary"),
]


@app.command("list")
@command
def list_tool_calls(
    agent: Optional[List[str]] = typer.Option(None, "--agent", "-a", help="Agent id, legacy UUID, or name (repeatable; default: all agents)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., card_type:eq:widget)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List interactive card entries that stand in for Grokbot tool calls.

    Example:
        grokbot-sessions tool-calls list --table
        grokbot-sessions tool-calls list --agent 1036984 --table
        grokbot-sessions tool-calls list --filter "card_type:eq:local-tool-permission"
    """
    try:
        client = get_client()
        agents = client.resolve_agents(agent)
        rows = client.list_tool_calls(agents, limit=fetch_limit(limit, filter))
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            add_time(rows, "timestamp", "time")
            for row in rows:
                row["turn"] = row.get("turn") if row.get("turn") is not None else ""
            render_table(rows, LEAN, EXTRA, wide)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_tool_call(
    tool_call_id: str = typer.Argument(..., help="Card entry id: <agent legacy UUID>:<entry id>"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one derived tool call.

    Example:
        grokbot-sessions tool-calls get 76ba30d6-8ed3-40d7-b25e-87b329eddb1c:t2s7 --table
    """
    try:
        row = get_client().get_tool_call(tool_call_id)

        if table:
            field_value_table(
                [
                    ("ID", row["id"]),
                    ("Entry ID", row["entry_id"]),
                    ("Agent", f"{row['agent_name']} ({row['agent_id']})"),
                    ("Turn", row["turn"]),
                    ("Timestamp", row["timestamp"]),
                    ("Source", row["source"]),
                    ("Tool", row["tool"]),
                    ("Card Type", row["card_type"]),
                    ("Action", row["action"]),
                    ("Target", row["target"]),
                    ("Status", row["status"]),
                    ("Title", row["title"]),
                    ("Request ID", row["request_id"]),
                    ("Summary", row["summary"]),
                    ("Payload", row["payload"]),
                ]
            )
        else:
            print_json(row)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
