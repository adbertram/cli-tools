"""Native Vyro reads and guarded campaign submission operations."""
from typing import List, Optional
import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_json, print_table
from . import __version__
from .config import get_config
from .client import VyroClient

app = create_app(name="vyro", help="Read Vyro accounts and clipping campaigns", version=__version__, cache_support=False)
account_app = typer.Typer(help="Current Vyro account", no_args_is_help=True)
campaigns_app = typer.Typer(help="Native campaign catalog and eligibility", no_args_is_help=True)
social_app = typer.Typer(help="Connected social accounts", no_args_is_help=True)


def read(method, profile, *args):
    client = VyroClient(get_config(profile))
    try:
        return getattr(client, method)(*args)
    finally:
        client.close()


def render(data, table, properties=None):
    rows = data if isinstance(data, list) else [data]
    if properties:
        rows = apply_properties_filter(rows, properties)
        data = rows if isinstance(data, list) else rows[0]
    if table:
        if isinstance(data, list):
            fields = [field.strip() for field in properties.split(',') if field.strip()] if properties else ['id', 'name', 'slug', 'platform', 'platformUsername']
            print_table(rows, fields, fields)
        else:
            print_table([{'field': k, 'value': str(v)} for k, v in data.items()], ['field', 'value'], ['Field', 'Value'])
    else:
        print_json(data)


@account_app.command('get')
@command
def account_get(table: bool = typer.Option(False, '--table', '-t'),
                properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
                profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name')):
    """Read the current account, including workspace and verification fields."""
    render(read('account', profile), table, properties)


@campaigns_app.command('list')
@command
def campaigns_list(limit: int = typer.Option(100, '--limit', '-l', min=1, max=1000),
                   filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter field:op:value (applied locally)'),
                   table: bool = typer.Option(False, '--table', '-t'),
                   properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
                   profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name')):
    """List newest campaigns. Filters run locally after the API limit."""
    if filter:
        validate_filters(filter)
    rows = read('campaigns', profile, limit)
    render(apply_filters(rows, filter) if filter else rows, table, properties)


@campaigns_app.command('get')
@command
def campaign_get(slug: str = typer.Argument(..., help='Exact campaign slug from campaigns list'),
                 table: bool = typer.Option(False, '--table', '-t'),
                 properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
                 profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name')):
    """Read every native campaign field, including requirements and media links."""
    render(read('campaign', profile, slug), table, properties)


@campaigns_app.command('eligibility')
@command
def campaign_eligibility(slug: str = typer.Argument(...),
                         table: bool = typer.Option(False, '--table', '-t'),
                         properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
                         profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name')):
    """Read native eligibleAccounts and inviteMode without enrolling."""
    render(read('eligibility', profile, slug), table, properties)


@social_app.command('list')
@command
def social_list(limit: int = typer.Option(100, '--limit', '-l', min=1, max=1000),
                filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter field:op:value (applied locally)'),
                table: bool = typer.Option(False, '--table', '-t'),
                properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
                profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name')):
    """List linked accounts; limit and filters are local for this endpoint."""
    if filter:
        validate_filters(filter)
    rows = read('social_accounts', profile, limit)
    render(apply_filters(rows, filter) if filter else rows, table, properties)


submissions_app = typer.Typer(help='Guarded native post submissions', no_args_is_help=True)

@campaigns_app.command('join')
@command
def campaigns_join(
    slug: str = typer.Argument(..., help='Exact campaign slug'),
    expected_account_id: str = typer.Option(..., '--expected-account-id', help='Exact Vyro account ID'),
    expected_social_account_id: str = typer.Option(..., '--expected-social-account-id', help='Exact linked Vyro social account ID'),
    expected_username: str = typer.Option(..., '--expected-username', help='Expected TikTok handle'),
    yes: bool = typer.Option(False, '--yes', help='Authorize campaign enrollment'),
    table: bool = typer.Option(False, '--table', '-t'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name'),
):
    """Join after exact actor and campaign checks."""
    render(read('join', profile, slug, expected_account_id, expected_social_account_id, expected_username, yes), table, properties)


@submissions_app.command('readiness')
@command
def submissions_readiness(
    slug: str = typer.Argument(..., help='Exact campaign slug'),
    expected_account_id: str = typer.Option(..., '--expected-account-id', help='Exact Vyro account ID'),
    expected_social_account_id: str = typer.Option(..., '--expected-social-account-id', help='Exact linked Vyro social account ID'),
    expected_username: str = typer.Option(..., '--expected-username', help='Expected TikTok handle'),
    table: bool = typer.Option(False, '--table', '-t'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name'),
):
    """Read campaign, account, rate and throttle readiness."""
    render(read('readiness', profile, slug, expected_account_id, expected_social_account_id, expected_username), table, properties)


@submissions_app.command('reconcile')
@command
def submissions_reconcile(
    slug: str = typer.Argument(..., help='Exact campaign slug'),
    expected_account_id: str = typer.Option(..., '--expected-account-id', help='Exact Vyro account ID'),
    expected_social_account_id: str = typer.Option(..., '--expected-social-account-id', help='Exact linked Vyro social account ID'),
    expected_username: str = typer.Option(..., '--expected-username', help='Expected TikTok handle'),
    url: str = typer.Option(..., '--url', help='Canonical owned TikTok post URL'),
    table: bool = typer.Option(False, '--table', '-t'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name'),
):
    """Find an exact native receipt without creating one."""
    render(read('reconcile', profile, slug, url, expected_account_id, expected_social_account_id, expected_username), table, properties)


@submissions_app.command('create')
@command
def submissions_create(
    slug: str = typer.Argument(..., help='Exact campaign slug'),
    expected_account_id: str = typer.Option(..., '--expected-account-id', help='Exact Vyro account ID'),
    expected_social_account_id: str = typer.Option(..., '--expected-social-account-id', help='Exact linked Vyro social account ID'),
    expected_username: str = typer.Option(..., '--expected-username', help='Expected TikTok handle'),
    url: str = typer.Option(..., '--url', help='Canonical owned TikTok post URL'),
    requirements_digest: str = typer.Option(..., '--requirements-digest', help='Digest returned by readiness'),
    yes: bool = typer.Option(False, '--yes', help='Affirm campaign rules and authorize submission'),
    table: bool = typer.Option(False, '--table', '-t'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name'),
):
    """Submit once after rules, identity, duplicate and pre-check verification."""
    render(read('create_submission', profile, slug, url, requirements_digest, expected_account_id, expected_social_account_id, expected_username, yes), table, properties)


@submissions_app.command('list')
@command
def submissions_list(
    campaign_slug: Optional[str] = typer.Option(None, '--campaign-slug', help='Restrict to exact campaign slug'),
    limit: int = typer.Option(100, '--limit', '-l', min=1, max=1000),
    filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter field:op:value (applied locally)'),
    table: bool = typer.Option(False, '--table', '-t'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name'),
):
    """List native receipts for the authenticated campaign member."""
    if filter: validate_filters(filter)
    rows=read('submissions',profile,campaign_slug,limit)
    render(apply_filters(rows,filter) if filter else rows,table,properties)


@submissions_app.command('get')
@command
def submissions_get(
    identity: str = typer.Argument(..., help='Exact native submission ID'),
    table: bool = typer.Option(False, '--table', '-t'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name'),
):
    """Read a native submission receipt."""
    render(read('submission',profile,identity),table,properties)


analytics_app = typer.Typer(help='Fresh provider clip metrics', no_args_is_help=True)

@analytics_app.command('list')
@command
def analytics_list(
    campaign_slug: Optional[str] = typer.Option(None, '--campaign-slug', help='Restrict to exact campaign slug'),
    limit: int = typer.Option(100, '--limit', '-l', min=1, max=1000),
    filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter fetched metrics (field:op:value)'),
    table: bool = typer.Option(False, '--table', '-t'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name'),
):
    """Query current clip metrics and earnings directly from Vyro."""
    if filter: validate_filters(filter)
    rows = read('analytics', profile, campaign_slug, limit)
    render(apply_filters(rows, filter) if filter else rows, table, properties)

@analytics_app.command('get')
@command
def analytics_get(
    identity: str = typer.Argument(..., help='Owned native submission ID'),
    table: bool = typer.Option(False, '--table', '-t'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated output fields'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name'),
):
    """Query one owned clip's current Vyro metrics and earnings."""
    render(read('analytics_submission', profile, identity), table, properties)

app.add_typer(analytics_app, name='analytics')

app.add_typer(submissions_app, name='submissions')
app.add_typer(account_app, name='account')
app.add_typer(campaigns_app, name='campaigns')
app.add_typer(social_app, name='social-accounts')
app.add_typer(create_auth_app(get_config, tool_name='vyro'), name='auth')


def main():
    run_app(app)


if __name__ == '__main__':
    main()
