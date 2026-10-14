"""Fresh provider clip metrics, with native timestamps preserved."""
from typing import List, Optional
import typer
from cli_tools_shared.output import command
from ..render import read, render
from ..client import MAX_LIMIT

app = typer.Typer(no_args_is_help=True)
COMMAND_CREDENTIALS = {'list': ['browser_session'], 'get': ['browser_session']}

@app.command('list')
@command
def list_analytics(
    limit: int = typer.Option(100, '--limit', '-l', min=1, max=MAX_LIMIT),
    status: str = typer.Option('all', '--status', help='all, pending, approved, or history; all scans in that order'),
    retainer: bool = typer.Option(False, '--retainer', help='Read retainer submissions instead of regular clips'),
    filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter fetched metrics (field:op:value)'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
    table: bool = typer.Option(False, '--table', '-t'),
):
    """Query current clip metrics from Whop, up to the requested total limit."""
    render(read('analytics', limit, status, retainer, filters=filter), table, properties, filter)

@app.command('get')
@command
def get_analytics(
    submission_id: str = typer.Argument(..., help='Owned submission ID'),
    table: bool = typer.Option(False, '--table', '-t'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
):
    """Query one owned clip's current Whop metrics."""
    render(read('analytics_submission', submission_id), table, properties)
