"""Automation commands for the Grok Bot Sessions CLI.

Automations are Grokbot's own extension surface: ``recordJson`` carries the
cron/trigger definition, enabled state, provenance, and run history for each
automation attached to an agent.
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

app = typer.Typer(help="Query Grok Bot automations", no_args_is_help=True)

LEAN = [
    ("name", "Name"),
    ("agent_name", "Agent"),
    ("is_enabled", "Enabled"),
    ("trigger_type", "Trigger"),
    ("schedule", "Schedule"),
    ("next_run", "Next Run"),
]
EXTRA = [
    ("automation_id", "Automation ID"),
    ("agent_id", "Agent ID"),
    ("legacy_id", "Legacy ID"),
    ("trigger_description", "Trigger Description"),
    ("provenance", "Provenance"),
    ("run_count", "Runs"),
    ("created", "Created"),
    ("last_run", "Last Run"),
    ("file_path", "File"),
    ("prompt", "Prompt"),
]


@app.command("list")
@command
def list_automations(
    agent: Optional[List[str]] = typer.Option(None, "--agent", "-a", help="Agent id, legacy UUID, or name (repeatable; default: all agents)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., is_enabled:eq:True)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List the automations attached to Grok Bot agents.

    Example:
        grokbot-sessions automations list --table
        grokbot-sessions automations list --agent 76ba30d6-8ed3-40d7-b25e-87b329eddb1c --table
        grokbot-sessions automations list --filter "is_enabled:eq:True"
    """
    try:
        client = get_client()
        agents = client.resolve_agents(agent)
        rows = client.list_automations(agents, limit=fetch_limit(limit, filter))
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            add_time(rows, "next_run_at", "next_run")
            add_time(rows, "created_at", "created")
            add_time(rows, "last_run_at", "last_run")
            render_table(rows, LEAN, EXTRA, wide)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_automation(
    automation_id: str = typer.Argument(..., help="Automation id (automationId)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one automation with its full record.

    Example:
        grokbot-sessions automations get 5e3d822f-fa83-5f42-82ce-a0a02d7343c4 --table
    """
    try:
        row = get_client().get_automation(automation_id)

        if table:
            field_value_table(
                [
                    ("Automation ID", row["automation_id"]),
                    ("Name", row["name"]),
                    ("Agent", f"{row['agent_name']} ({row['agent_id']})"),
                    ("Enabled", "yes" if row["is_enabled"] else "no"),
                    ("Trigger Type", row["trigger_type"]),
                    ("Schedule", row["schedule"]),
                    ("Trigger Description", row["trigger_description"]),
                    ("Provenance", row["provenance"]),
                    ("Created", row["created_at"]),
                    ("Last Run", row["last_run_at"]),
                    ("Next Run", row["next_run_at"]),
                    ("Runs", row["run_count"]),
                    ("File", row["file_path"]),
                    ("Prompt", row["prompt"]),
                ]
            )
        else:
            print_json(row)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
