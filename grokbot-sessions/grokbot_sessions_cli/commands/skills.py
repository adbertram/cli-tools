"""Skill commands for the Grok Bot Sessions CLI.

Grokbot keeps agent skills in the cloud box's agent store, and the Connect
service in Grok Bot 0.47.0 exposes no method that reads it
(``ListAgentStoreEntries`` answers HTTP 404). These commands keep the shared
shape but return an explicit empty result instead of inventing records.
"""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.output import command, handle_error, print_info, print_json, print_table

from ..client import ClientError, get_client
from ._render import apply_row_filters, fetch_limit, select_properties

app = typer.Typer(help="Query agent-store skills (unsupported by this API)", no_args_is_help=True)

LEAN = [("id", "ID"), ("name", "Name"), ("kind", "Kind")]


@app.command("list")
@command
def list_skills(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:legoscout)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List agent-store skills (always empty: the API exposes no store).

    Example:
        grokbot-sessions skills list
        grokbot-sessions skills list --table
    """
    try:
        rows, note = get_client().list_skills()
        fetch_limit(limit, filter)
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)
        print_info(note)

        if table:
            print_table(rows, [column for column, _header in LEAN], [header for _column, header in LEAN], max_columns=0)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_skill(
    skill_id: str = typer.Argument(..., help="Skill id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one skill (never found: the API exposes no agent store).

    Example:
        grokbot-sessions skills get legoscout
    """
    try:
        _rows, note = get_client().list_skills()
        raise ClientError(f"Skill not found: {skill_id}. {note}")

    except ClientError as e:
        raise typer.Exit(handle_error(e))
