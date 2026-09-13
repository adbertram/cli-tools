"""Cross-agent search command for the Grok Bot Sessions CLI.

Grokbot's API exposes no server-side transcript search, so ``search run``
downloads the selected agents' decoded transcripts and matches client-side,
returning one result per agent with its snippets.
"""
COMMAND_CREDENTIALS = {
    "run": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.output import command, handle_error, print_json

from ..client import ClientError, get_client
from ._render import add_time, apply_row_filters, blank_none, fetch_limit, render_table, select_properties

app = typer.Typer(help="Search keywords across transcript entries", no_args_is_help=True)


@app.command("run")
@command
def search(
    query: str = typer.Argument(..., help="Keyword(s) to search for (case-insensitive)"),
    agent: Optional[List[str]] = typer.Option(None, "--agent", "-a", help="Agent id, legacy UUID, or name (repeatable; default: all agents)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    wide: bool = typer.Option(False, "--wide", "-w", help="Show every column in table mode"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum agents to return"),
    max_matches: int = typer.Option(5, "--max-matches", "-m", help="Maximum snippet matches per agent"),
    snippets: bool = typer.Option(False, "--snippets", help="Show the first matching snippet in table mode"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., kind:eq:ROOM)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    Search every selected agent's transcript for a keyword.

    Example:
        grokbot-sessions search run "legoscout"
        grokbot-sessions search run "timeout" --table --snippets
        grokbot-sessions search run "context7" --agent 5658aa56-122b-4f56-acd9-5102e4f39d1b
    """
    try:
        if max_matches < 1:
            raise typer.BadParameter("--max-matches must be at least 1")
        client = get_client()
        agents = client.resolve_agents(agent)
        rows = client.search(
            query,
            agents,
            limit=fetch_limit(limit, filter),
            max_matches=max_matches,
        )
        if filter:
            rows = apply_row_filters(rows, filter)
        rows = select_properties(rows[:limit], properties)

        if table:
            add_time(rows, "last_activity", "last")
            blank_none(rows, "name", "origin")
            for row in rows:
                row["first_match"] = ""
                matches = row.get("matches") or []
                if snippets and matches:
                    row["first_match"] = f"[{matches[0].get('role') or matches[0].get('kind')}] {matches[0].get('snippet', '')}"
            lean = [
                ("session_id", "Session ID"),
                ("name", "Name"),
                ("project", "Project"),
                ("last", "Last Activity"),
                ("match_count", "Matches"),
            ]
            extra = [("kind", "Kind"), ("legacy_id", "Legacy ID"), ("origin", "Origin")]
            if snippets:
                lean.append(("first_match", "First Match"))
            render_table(rows, lean, extra, wide)
        else:
            print_json(rows)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
