from typing import List, Optional
import typer
from cli_tools_shared.output import command
from ..render import read, render
from ..client import MAX_LIMIT

app=typer.Typer(no_args_is_help=True)
COMMAND_CREDENTIALS={'list': ['browser_session'], 'get': ['browser_session'], 'status': ['browser_session']}

@app.command("list")
@command
def list_submissions(limit: int=typer.Option(100,"--limit","-l",min=1,max=MAX_LIMIT), status: str=typer.Option("approved","--status",help="approved, pending, or history"), retainer: bool=typer.Option(False,"--retainer"), filter: Optional[List[str]]=typer.Option(None,"--filter","-f",metavar="TEXT",help="Filter fetched records (field:op:value)"), properties: Optional[str]=typer.Option(None,"--properties","-p",metavar="TEXT",help="Comma-separated output fields"), table: bool=typer.Option(False,"--table","-t")):
    """Read submissions; history uses the observed deleted-record filter."""
    render(read("submissions",limit,status,retainer,filters=filter),table,properties,filter)

@app.command("get")
@command
def get(submission_id: str=typer.Argument(...),table: bool=typer.Option(False,"--table","-t")):
    """Find a submission in at most 1000 rows per verified list; no detail route is assumed."""
    render(read("submission",submission_id),table)

@app.command("status")
@command
def status(table: bool=typer.Option(False,"--table","-t")):
    """Read server submission counts for clip and retainer records."""
    render(read("submission_status"),table)
