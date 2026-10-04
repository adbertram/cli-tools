from typing import List, Optional
import typer
from cli_tools_shared.output import command
from ..render import read, render
from ..client import MAX_LIMIT

app=typer.Typer(no_args_is_help=True)
COMMAND_CREDENTIALS={'list': ['browser_session'], 'get': ['browser_session'], 'applications': ['browser_session']}

@app.command("list")
@command
def list_campaigns(limit: int=typer.Option(100,"--limit","-l",min=1,max=MAX_LIMIT), sort: str=typer.Option("featured","--sort",metavar="TEXT",help="featured, trending, or newest"), filter: Optional[List[str]]=typer.Option(None,"--filter","-f",metavar="TEXT",help="Filter fetched records (field:op:value)"), properties: Optional[str]=typer.Option(None,"--properties","-p",metavar="TEXT",help="Comma-separated output fields"), table: bool=typer.Option(False,"--table","-t")):
    """Browse Content Rewards campaigns with server pagination."""
    render(read("campaigns",limit,sort,filters=filter),table,properties,filter)

@app.command("get")
@command
def get(campaign_id: str=typer.Argument(...),table: bool=typer.Option(False,"--table","-t")):
    """Get a discovered campaign including its complete rules and payout fields."""
    render(read("campaign",campaign_id),table)

@app.command("applications")
@command
def applications(table: bool=typer.Option(False,"--table","-t")):
    """Read existing applications; fail explicitly on partial upstream results."""
    render(read("applications"),table)
