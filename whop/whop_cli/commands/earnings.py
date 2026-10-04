from typing import List, Optional
import typer
from cli_tools_shared.output import command
from ..render import read, render
from ..client import MAX_LIMIT

app=typer.Typer(no_args_is_help=True)
COMMAND_CREDENTIALS={'get': ['browser_session'], 'payouts': ['browser_session']}

@app.command("get")
@command
def get(start: str=typer.Option(...,"--start",help="Timezone-aware ISO date"),end: str=typer.Option(...,"--end",help="Timezone-aware ISO date"),table: bool=typer.Option(False,"--table","-t")):
    """Read actual creator analytics for an explicit date range; missing values stay unknown."""
    render(read("earnings",start,end),table)

@app.command("payouts")
@command
def payouts(limit: int=typer.Option(100,"--limit","-l",min=1,max=MAX_LIMIT), filter: Optional[List[str]]=typer.Option(None,"--filter","-f",metavar="TEXT",help="Filter fetched records (field:op:value)"),properties: Optional[str]=typer.Option(None,"--properties","-p",metavar="TEXT",help="Comma-separated output fields"),table: bool=typer.Option(False,"--table","-t")):
    """Read creator payout records with server pagination."""
    render(read("payouts",limit,filters=filter),table,properties,filter)
