from pathlib import Path
from typing import List, Optional
import typer
from cli_tools_shared.output import command
from ..render import read, render
from ..client import MAX_LIMIT

app=typer.Typer(no_args_is_help=True)
COMMAND_CREDENTIALS={'list': ['browser_session'], 'get': ['browser_session'], 'applications': ['browser_session'], 'join': ['browser_session'], 'application-form': ['browser_session'], 'apply': ['browser_session']}

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

@app.command('join')
@command
def join(campaign_id: str=typer.Argument(...), expected_account_id: str=typer.Option(...,'--expected-account-id'), confirm: bool=typer.Option(False,'--confirm',help='Explicitly authorize joining this campaign'), table: bool=typer.Option(False,'--table','-t')):
    """Join a campaign by clicking its own Join Campaign control; --confirm is required and the result reports whether the account was already a member."""
    from cli_tools_shared.exceptions import ClientError
    if not confirm: raise ClientError('campaign_join_confirmation_required')
    render(read('join_campaign',campaign_id,expected_account_id=expected_account_id,confirm=confirm),table)

@app.command('application-form')
@command
def application_form(campaign_id: str=typer.Argument(...), table: bool=typer.Option(False,'--table','-t')):
    """Read the current campaign application form and native screening fields."""
    render(read('application_form', campaign_id), table)

@app.command('apply')
@command
def apply_campaign(
    campaign_id: str=typer.Argument(...),
    answers: Path=typer.Option(...,'--answers',exists=True,dir_okay=False,readable=True,help='JSON object keyed by native screening field names'),
    social_account_id: List[str]=typer.Option(...,'--social-account-id',help='Owned linked social account ID; repeat for each account'),
    expected_account_id: str=typer.Option(...,'--expected-account-id'),
    confirm: bool=typer.Option(False,'--confirm',help='Explicitly authorize this application'),
    table: bool=typer.Option(False,'--table','-t'),
):
    """Apply once with explicit screening answers; read back before reporting success."""
    from cli_tools_shared.exceptions import ClientError
    from ..client import MAX_BODY, strict_json
    if not confirm:
        raise ClientError('campaign_application_confirmation_required')
    if answers.stat().st_size > MAX_BODY:
        raise ClientError('campaign_application_answers_too_large')
    payload = strict_json(answers.read_text())
    if not isinstance(payload, dict):
        raise ClientError('campaign_application_answers_must_be_object')
    render(read('apply_campaign', campaign_id, answers=payload, social_account_ids=social_account_id,
                expected_account_id=expected_account_id, confirm=confirm), table)
