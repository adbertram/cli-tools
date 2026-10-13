"""Native Vyro account and campaign reads; no publication mutations."""
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


app.add_typer(account_app, name='account')
app.add_typer(campaigns_app, name='campaigns')
app.add_typer(social_app, name='social-accounts')
app.add_typer(create_auth_app(get_config, tool_name='vyro'), name='auth')


def main():
    run_app(app)


if __name__ == '__main__':
    main()
