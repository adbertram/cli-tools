"""Project commands for the Grok Bot Sessions CLI.

Grokbot has no working-directory-scoped project: agents run in Cursor-hosted
cloud boxes. Each signed-in account scope is surfaced as one implicit project
so the shared ``projects list`` / ``projects get`` contract keeps working.
"""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.output import command, handle_error, print_json

from ..client import ClientError, get_client
from ._render import apply_row_filters, fetch_limit, field_value_table, render_table, select_properties

app = typer.Typer(help="List implicit Grokbot projects (one per account scope)", no_args_is_help=True)


@app.command("list")
@command
def list_projects(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., active:eq:true)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List Grokbot's implicit projects.

    Example:
        grokbot-sessions projects list
        grokbot-sessions projects list --table
        grokbot-sessions projects list --filter "active:eq:true"
    """
    try:
        rows = get_client().list_projects(limit=fetch_limit(limit, filter))
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            render_table(
                rows,
                [("id", "ID"), ("name", "Name"), ("active", "Active"), ("has_token", "Token")],
                [("kind", "Kind"), ("source", "Source"), ("path", "Path"), ("note", "Note")],
                wide,
            )
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_project(
    project_id: str = typer.Argument(..., help="Project ID (account-<n>) or name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one implicit project.

    Example:
        grokbot-sessions projects get account-1
    """
    try:
        row = get_client().get_project(project_id)

        if table:
            field_value_table(
                [
                    ("ID", row["id"]),
                    ("Name", row["name"]),
                    ("Kind", row["kind"]),
                    ("Active", "yes" if row["active"] else "no"),
                    ("Has Token", "yes" if row["has_token"] else "no"),
                    ("Source", row["source"]),
                    ("Path", row["path"]),
                    ("Note", row["note"]),
                ]
            )
        else:
            print_json(row)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
