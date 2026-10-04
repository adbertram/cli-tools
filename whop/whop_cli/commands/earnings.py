from typing import List, Optional
import typer
from cli_tools_shared.output import command
from ..render import read, render
from ..client import MAX_LIMIT

app=typer.Typer(no_args_is_help=True)
COMMAND_CREDENTIALS={'get':['browser_session'],'payouts':['browser_session'],'sync':['browser_session'],'submission':['browser_session']}

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

@app.command('sync')
@command
def sync(restart_pass: bool=typer.Option(False,'--restart-pass',help='Discard only an incomplete scan and begin a new provider pass'),table: bool=typer.Option(False,'--table','-t')):
    """Advance one shared payout scan, reading at most eleven pages."""
    render(read('sync_submission_revenue',restart_pass=restart_pass),table)

@app.command('submission')
@command
def submission(submission_id: str=typer.Argument(...),campaign_id: str=typer.Argument(...),refresh_payouts: bool=typer.Option(True,'--refresh-payouts/--no-refresh-payouts',help='Advance the shared scan; disable after one explicit sync for a batch'),table: bool=typer.Option(False,'--table','-t')):
    """Read individual allocations for one owned submission; unknown amounts remain null."""
    render(read('submission_revenue',submission_id,campaign_id,refresh_payouts=refresh_payouts),table)
