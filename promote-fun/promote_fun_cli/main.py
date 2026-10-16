"""Promote.fun public campaign discovery; stdout contains native JSON records."""
from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_json, print_table

from . import __version__
from .client import PromoteFunClient
from .config import get_config

app = create_app(name='promote-fun', help='Discover Promote.fun public campaigns. Rules and minimum views may be gated.', version=__version__)
campaigns_app = typer.Typer(no_args_is_help=True, help='Read public campaigns without signing in')


@campaigns_app.command('list')
@command
def campaigns_list(
    limit: int = typer.Option(100, '--limit', '-l', min=1, max=1000),
    status: str = typer.Option('active', '--status', help='Campaign status, as used by the public app'),
    platform: Optional[str] = typer.Option(None, '--platform', help='Server-side platform filter, e.g. tiktok'),
    search: Optional[str] = typer.Option(None, '--search', help='Server-side campaign search'),
    sort: str = typer.Option('newest', '--sort'),
    filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Local field:op:value filter over fetched rows'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated native fields'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Accepted for workflow compatibility; public reads do not use authentication'),
):
    """List public campaigns with server pagination; missing view floors stay missing."""
    if filter:
        validate_filters(filter)
    client = PromoteFunClient()
    try:
        rows = client.campaigns(limit, status, platform, search, sort)
    finally:
        client.close()
    if filter:
        rows = apply_filters(rows, filter)
    if properties:
        rows = apply_properties_filter(rows, properties)
    if table:
        columns = properties.split(',') if properties else ['_id', 'title', 'acceptedPlatforms', 'costPer1kViews', 'totalBudget']
        print_table(rows, columns, columns)
    else:
        print_json(rows)


@campaigns_app.command('get')
@command
def campaigns_get(campaign_id: str = typer.Argument(..., help='Native ID or campaign slug'),
                  table: bool = typer.Option(False, '--table', '-t'),
                  profile: Optional[str] = typer.Option(None, '--profile', help='Public read; authentication is not sent')):
    """Read native public detail, including explicit rulesAccess gates."""
    client = PromoteFunClient()
    try:
        row = client.campaign(campaign_id)
    finally:
        client.close()
    if table:
        print_table([{'field': key, 'value': value} for key, value in row.items()], ['field', 'value'], ['Field', 'Value'])
    else:
        print_json(row)


app.add_typer(campaigns_app, name='campaigns')
app.add_typer(create_auth_app(get_config, tool_name='promote-fun'), name='auth')
app.add_typer(create_cache_app(get_config), name='cache')


def main():
    run_app(app)


if __name__ == '__main__':
    main()
