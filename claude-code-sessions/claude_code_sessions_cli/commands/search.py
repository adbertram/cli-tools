"""Cross-project search command for Claude Code Sessions CLI."""
import typer
from typing import Optional, List
from ..client import get_client, ClientError
from cli_tools_shared.output import command, print_json, print_table, handle_error
from ..parsers import format_local_time

app = typer.Typer(help="Search across session transcripts", no_args_is_help=True)


@app.command("run")
@command
def search(
    query: str = typer.Argument(..., help="Keyword(s) to search for (case-insensitive)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Restrict to a specific project"),
    project_path: Optional[str] = typer.Option(None, "--project-path", help="Restrict to a specific project by folder path"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum sessions to return"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Time filter: 5h, 1d, 7d, 30d"),
    max_matches: int = typer.Option(5, "--max-matches", "-m", help="Max snippet matches per session"),
    snippets: bool = typer.Option(False, "--snippets", help="Show matching text snippets (table mode)"),
):
    """
    Search keywords across all session transcripts.

    Searches all projects by default. Use --project to restrict to one.

    Example:
        claude-code-sessions search run "onedrive provisioned"
        claude-code-sessions search run "onedrive" --since 30d --table
        claude-code-sessions search run "connection error" --project ProgressAutomationProject
        claude-code-sessions search run "deploy" --snippets --table
    """
    resolved_project = project_path or project

    try:
        client = get_client()
        results = client.search_all(
            query=query,
            project=resolved_project,
            limit=limit,
            since=since,
            max_matches_per_session=max_matches,
        )

        if not results:
            typer.echo(f"No sessions found matching '{query}'")
            raise typer.Exit(0)

        items = [r.model_dump() for r in results]

        if table:
            for item in items:
                item['started'] = format_local_time(item.get('created_at', ''))
                item['last'] = format_local_time(item.get('last_activity', ''))
                if snippets and item.get('matches'):
                    # Show first match snippet truncated
                    first = item['matches'][0]
                    snip = first.get('snippet', '')
                    if len(snip) > 100:
                        snip = snip[:100] + '...'
                    item['first_match'] = f"[{first.get('role', '?')}] {snip}"
                else:
                    item['first_match'] = ''

            columns = ["session_id", "project", "started", "last", "match_count"]
            headers = ["Session ID", "Project", "Started", "Last Activity", "Matches"]
            if snippets:
                columns.append("first_match")
                headers.append("First Match")
            print_table(items, columns, headers)
        else:
            print_json(items)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
