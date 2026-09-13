"""Session commands for the Grok Bot Sessions CLI.

A Grokbot "session" is an agent: all of an agent's history is one transcript,
stored in Cursor's cloud box and read here over the live Connect RPC API. The
numeric agent ``id`` is the public session id; ``legacy_id`` is the UUID that
transcript calls require.
"""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "search": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.output import command, handle_error, print_json

from ..client import ClientError, get_client
from ._render import apply_row_filters, fetch_limit, field_value_table, render_table, select_properties

app = typer.Typer(help="List, get, and search Grok Bot agents", no_args_is_help=True)

LEAN = [
    ("id", "ID"),
    ("name", "Name"),
    ("kind", "Kind"),
    ("harness", "Harness"),
    ("member_count", "Members"),
    ("updated_at", "Updated"),
]
EXTRA = [
    ("legacy_id", "Legacy ID"),
    ("role", "Role"),
    ("visibility", "Visibility"),
    ("avatar_shape", "Avatar"),
    ("created_at", "Created"),
    ("member_agent_ids", "Member IDs"),
    ("title", "Title"),
]


def _search_agents(rows: List[dict], query: str) -> List[dict]:
    """Match a query against an agent's names, description, and ids."""
    needle = query.lower()
    matches = []
    for row in rows:
        haystacks = [
            row.get("id") or "",
            row.get("legacy_id") or "",
            row.get("name") or "",
            row.get("title") or "",
            row.get("description") or "",
        ]
        if any(needle in value.lower() for value in haystacks):
            matches.append(row)
    return matches


@app.command("list")
@command
def list_sessions(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., kind:eq:ROOM)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List Grok Bot agents, one per session.

    Example:
        grokbot-sessions sessions list --table
        grokbot-sessions sessions list --filter "kind:eq:ROOM"
        grokbot-sessions sessions list --properties id,legacy_id,name --table
    """
    try:
        rows = get_client().list_sessions(limit=fetch_limit(limit, filter))
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            render_table(rows, LEAN, EXTRA, wide)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def get_session(
    session_id: str = typer.Argument(..., help="Numeric agent id, legacy UUID, or agent name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get one Grok Bot agent.

    Example:
        grokbot-sessions sessions get 1036984
        grokbot-sessions sessions get 5658aa56-122b-4f56-acd9-5102e4f39d1b --table
        grokbot-sessions sessions get "Lego Scout"
    """
    try:
        row = get_client().get_session(session_id)

        if table:
            field_value_table(
                [
                    ("ID", row["id"]),
                    ("Legacy ID", row["legacy_id"]),
                    ("Name", row["name"]),
                    ("Kind", row["kind"]),
                    ("Is Group", "yes" if row["is_group"] else "no"),
                    ("Harness", row["harness"]),
                    ("Role", row["role"]),
                    ("Visibility", row["visibility"]),
                    ("Title", row["title"]),
                    ("Avatar", f"{row['avatar_shape']} {row['avatar_color']}".strip()),
                    ("Created", row["created_at"]),
                    ("Updated", row["updated_at"]),
                    ("Member Agent IDs", ", ".join(row["member_agent_ids"])),
                    ("Description", row["description"]),
                ]
            )
        else:
            print_json(row)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
@command
def search_sessions(
    query: str = typer.Argument(..., help="Text to match against agent names, titles, descriptions, and ids"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., kind:eq:AGENT)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Search Grok Bot agents by name, title, description, or id.

    Use `search run` to search transcript text instead.

    Example:
        grokbot-sessions sessions search lego
        grokbot-sessions sessions search kalshi --table
    """
    try:
        rows = get_client().list_sessions()
        rows = _search_agents(rows, query)
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            render_table(rows, LEAN, EXTRA, wide)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
