"""Approval commands for the Grok Bot Sessions CLI.

Grokbot records a permission escalation as a ``local-tool-permission`` send
whose ``message.ask`` carries the request id, action, target, machine, and
status, and an automatic review as an ``auto-review-approval`` send whose
``message.approval`` carries the same information plus the reason and the
proposed rule.
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

app = typer.Typer(help="Query permission and review approvals", no_args_is_help=True)

LEAN = [
    ("time", "Time"),
    ("agent_name", "Agent"),
    ("kind", "Kind"),
    ("action", "Action"),
    ("status", "Status"),
    ("machine_label", "Machine"),
    ("target", "Target"),
]
EXTRA = [
    ("entry_id", "Entry ID"),
    ("agent_id", "Agent ID"),
    ("legacy_id", "Legacy ID"),
    ("request_id", "Request ID"),
    ("machine_id", "Machine ID"),
    ("resolved_value", "Resolved Value"),
    ("surface", "Surface"),
    ("proposed_rule", "Proposed Rule"),
    ("reason", "Reason"),
]


@app.command("list")
@command
def list_approvals(
    agent: Optional[List[str]] = typer.Option(None, "--agent", "-a", help="Agent id, legacy UUID, or name (repeatable; default: all agents)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., status:eq:allowed)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List permission requests and automatic review approvals.

    Example:
        grokbot-sessions approvals list --table
        grokbot-sessions approvals list --filter "kind:eq:auto-review-approval"
        grokbot-sessions approvals list --agent 76ba30d6-8ed3-40d7-b25e-87b329eddb1c --table
    """
    try:
        client = get_client()
        agents = client.resolve_agents(agent)
        rows = client.list_approvals(agents, limit=fetch_limit(limit, filter))
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
def get_approval(
    approval_id: str = typer.Argument(..., help="Approval entry id, or its request id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one approval request.

    Example:
        grokbot-sessions approvals get 76ba30d6-8ed3-40d7-b25e-87b329eddb1c:t3s10 --table
        grokbot-sessions approvals get 0f30ca1d-2fb1-41aa-a621-477f6c57740f --table
    """
    try:
        row = get_client().get_approval(approval_id)

        if table:
            field_value_table(
                [
                    ("ID", row["id"]),
                    ("Entry ID", row["entry_id"]),
                    ("Agent", f"{row['agent_name']} ({row['agent_id']})"),
                    ("Kind", row["kind"]),
                    ("Turn", row["turn"]),
                    ("Timestamp", row["timestamp"]),
                    ("Request ID", row["request_id"]),
                    ("Action", row["action"]),
                    ("Target", row["target"]),
                    ("Machine Label", row["machine_label"]),
                    ("Machine ID", row["machine_id"]),
                    ("Status", row["status"]),
                    ("Resolved Value", row["resolved_value"]),
                    ("Surface", row["surface"]),
                    ("Reason", row["reason"]),
                    ("Proposed Rule", row["proposed_rule"]),
                    ("Payload", row["payload"]),
                ]
            )
        else:
            print_json(row)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
