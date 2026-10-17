from typing import List, Optional
import typer
from cli_tools_shared.output import command
from ..render import read, render
from ..client import MAX_LIMIT

app=typer.Typer(no_args_is_help=True)
COMMAND_CREDENTIALS={'list': ['browser_session'], 'get': ['browser_session']}

@app.command("list")
@command
def list_accounts(limit: int=typer.Option(100,"--limit","-l",min=1,max=MAX_LIMIT), filter: Optional[List[str]]=typer.Option(None,"--filter","-f",metavar="TEXT",help="Filter fetched records (field:op:value)"), properties: Optional[str]=typer.Option(None,"--properties","-p",metavar="TEXT",help="Comma-separated output fields"), table: bool=typer.Option(False,"--table","-t")):
    """List Content Rewards linked accounts; active bio verification is not OAuth."""
    render(read("linked_accounts",limit,filters=filter),table,properties,filter)

@app.command("get")
@command
def get(account_id: str=typer.Argument(...),table: bool=typer.Option(False,"--table","-t")):
    """Get a linked Content Rewards account by its registry ID."""
    render(read("linked_account",account_id),table)
