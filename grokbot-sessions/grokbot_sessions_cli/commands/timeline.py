"""Timeline commands for the Grok Bot Sessions CLI.

``list`` returns a transcript's entries in the server's newest-to-oldest order
and never re-sorts by ``seq`` (a commit sequence, not an entry ordinal).
``consolidated`` interleaves every agent's entries by ``timestampMs``.
"""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "consolidated": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.output import command, handle_error, print_json

from ..client import ClientError, get_client
from ._render import add_time, apply_row_filters, fetch_limit, field_value_table, render_table, select_properties

app = typer.Typer(help="View transcript timelines", no_args_is_help=True)

LEAN = [
    ("time", "Time"),
    ("agent_name", "Agent"),
    ("turn", "Turn"),
    ("kind", "Kind"),
    ("type", "Type"),
    ("role", "Role"),
    ("summary", "Summary"),
]
EXTRA = [
    ("entry_id", "Entry ID"),
    ("agent_id", "Agent ID"),
    ("legacy_id", "Legacy ID"),
    ("seq", "Seq"),
    ("updated_seq", "Updated Seq"),
    ("request_id", "Request ID"),
    ("body_omitted", "Body Omitted"),
    ("blob_hash", "Blob Hash"),
]


def _timeline_table(rows: List[dict], wide: bool) -> None:
    """Add the derived display columns the timeline table renders."""
    add_time(rows, "timestamp", "time")
    for row in rows:
        row["turn"] = row.get("turn") if row.get("turn") is not None else ""
        row["summary"] = row.get("summary") or ""
    render_table(rows, LEAN, EXTRA, wide)


@app.command("list")
@command
def list_timeline(
    agent: Optional[List[str]] = typer.Option(None, "--agent", "-a", help="Agent id, legacy UUID, or name (repeatable; default: all agents, grouped per agent)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum entries"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., kind:eq:message)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List transcript entries, newest first within each agent.

    Example:
        grokbot-sessions timeline list --agent 5658aa56-122b-4f56-acd9-5102e4f39d1b --limit 20
        grokbot-sessions timeline list --table
        grokbot-sessions timeline list --filter "kind:eq:send-message" --table
    """
    try:
        client = get_client()
        agents = client.resolve_agents(agent)
        rows = client.list_timeline(agents, limit=fetch_limit(limit, filter), merge=False)
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            _timeline_table(rows, wide)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_timeline_entry(
    entry_id: str = typer.Argument(..., help="Entry id: <agent legacy UUID>:<entry id>"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one decoded transcript entry.

    Example:
        grokbot-sessions timeline get 5658aa56-122b-4f56-acd9-5102e4f39d1b:t6u --table
    """
    try:
        row = get_client().get_entry(entry_id)

        if table:
            field_value_table(
                [
                    ("ID", row["id"]),
                    ("Entry ID", row["entry_id"]),
                    ("Agent", f"{row['agent_name']} ({row['agent_id']})"),
                    ("Kind", row["kind"]),
                    ("Type", row["type"]),
                    ("Role", row["role"]),
                    ("Turn", row["turn"]),
                    ("Timestamp", row["timestamp"]),
                    ("Seq", row["seq"]),
                    ("Updated Seq", row["updated_seq"]),
                    ("Request ID", row["request_id"]),
                    ("Resolution", row["resolution"]),
                    ("Body Omitted", "yes" if row["body_omitted"] else "no"),
                    ("Summary", row["summary"]),
                    ("Text", row["text"]),
                    ("Payload", row["payload"]),
                ]
            )
        else:
            print_json(row)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("consolidated")
@command
def consolidated_timeline(
    agent: Optional[List[str]] = typer.Option(None, "--agent", "-a", help="Agent id, legacy UUID, or name (repeatable; default: all agents)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(500, "--limit", "-l", help="Maximum entries"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., agent_name:eq:Lego Scout)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Interleave every agent's transcript entries by timestamp, newest first.

    Example:
        grokbot-sessions timeline consolidated --limit 50 --table
        grokbot-sessions timeline consolidated --agent 5658aa56-122b-4f56-acd9-5102e4f39d1b --table
    """
    try:
        client = get_client()
        agents = client.resolve_agents(agent)
        rows = client.list_timeline(agents, limit=fetch_limit(limit, filter), merge=True)
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            _timeline_table(rows, wide)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
