"""Subagent activity commands for the Grok Bot Sessions CLI.

Grokbot "subagents" are not spawned child sessions: a ROOM agent groups peer
bots through ``memberAgentIds``, and a ``cursor-agent`` card starts a
background-composer run. Both surfaces are reported here.
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

app = typer.Typer(help="Query room members and cursor-agent runs", no_args_is_help=True)

LEAN = [
    ("kind", "Kind"),
    ("id", "ID"),
    ("agent_name", "Agent"),
    ("member_name", "Member"),
    ("title", "Title"),
    ("time", "Time"),
]
EXTRA = [
    ("agent_id", "Agent ID"),
    ("legacy_id", "Legacy ID"),
    ("room_name", "Room"),
    ("room_legacy_id", "Room Legacy ID"),
    ("member_id", "Member ID"),
    ("member_kind", "Member Kind"),
    ("member_harness", "Member Harness"),
    ("bc_id", "BC ID"),
    ("entry_id", "Entry ID"),
    ("summary", "Summary"),
]


@app.command("list")
@command
def list_subagent_activity(
    agent: Optional[List[str]] = typer.Option(None, "--agent", "-a", help="Agent id, legacy UUID, or name (repeatable; default: all agents)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., kind:eq:room-member)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List room memberships and cursor-agent runs.

    Example:
        grokbot-sessions subagent-activity list --table
        grokbot-sessions subagent-activity list --filter "kind:eq:room-member"
        grokbot-sessions subagent-activity list --agent 2781289 --table
    """
    try:
        client = get_client()
        agents = client.resolve_agents(agent)
        rows = client.list_subagent_activity(agents, limit=fetch_limit(limit, filter))
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            add_time(rows, "timestamp", "time")
            render_table(rows, LEAN, EXTRA, wide)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_subagent(
    subagent_id: str = typer.Argument(..., help="Room member agent UUID, cursor-agent entry id, or bc id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one subagent surface, with the member's conversation summary.

    Example:
        grokbot-sessions subagent-activity get cd58935c-b2fa-448e-ac49-15fe781ddcec --table
    """
    try:
        row = get_client().get_subagent(subagent_id)

        if table:
            fields = [
                ("Kind", row["kind"]),
                ("ID", row["id"]),
                ("Agent", f"{row['agent_name']} ({row['agent_id']})"),
                ("Room", row["room_name"]),
                ("Room Legacy ID", row["room_legacy_id"]),
                ("Member", f"{row['member_name']} ({row['member_id']})"),
                ("Member Kind", row["member_kind"]),
                ("Member Harness", row["member_harness"]),
                ("BC ID", row.get("bc_id") or ""),
                ("Title", row.get("title") or ""),
                ("Timestamp", row.get("timestamp") or ""),
                ("Summary", row.get("summary") or ""),
            ]
            conversation = row.get("conversation")
            if conversation:
                fields.extend(
                    [
                        ("Conversation ID", conversation.get("id") or ""),
                        ("Entries", conversation.get("entry_count")),
                        ("Turns", conversation.get("turn_count")),
                        ("Last Activity", conversation.get("last_activity") or ""),
                    ]
                )
            field_value_table(fields)
        else:
            print_json(row)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
