"""Public campaign discovery; no account or publishing actions."""
from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_json, print_table

from . import __version__
from .client import ReachCatClient
from .config import get_config

app = create_app(name='reach-cat', help='Discover ReachCat public campaign rules, view floors and rates.', version=__version__)
campaigns_app = typer.Typer(no_args_is_help=True, help='Read sanitized public campaign records')


@campaigns_app.command('list')
@command
def campaigns_list(
    limit: int = typer.Option(100, '--limit', '-l', min=1, max=1000),
    status: str = typer.Option('ACTIVE', '--status', help='Native status filter; empty string includes all statuses'),
    platform: Optional[str] = typer.Option(None, '--platform', help='Require networks.<platform> to be true'),
    filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Local field:op:value filter over fetched matching rows'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated native output fields'),
    table: bool = typer.Option(False, '--table', '-t'),
):
    """List campaign records with server cursor pagination and local status/platform filters."""
    if filter:
        validate_filters(filter)
    client = ReachCatClient()
    try:
        rows = client.campaigns(limit, status, platform)
    finally:
        client.close()
    if filter:
        rows = apply_filters(rows, filter)
    if properties:
        rows = apply_properties_filter(rows, properties)
    if table:
        columns = properties.split(',') if properties else ['id', 'name', 'status', 'minViewsForPayout', 'amountRemaining']
        print_table(rows, columns, columns)
    else:
        print_json(rows)


@campaigns_app.command('get')
@command
def campaigns_get(campaign_id: str = typer.Argument(..., help='Native campaign ID'),
                  table: bool = typer.Option(False, '--table', '-t')):
    """Read native campaign fields and public rules; management/payment identities are excluded."""
    client = ReachCatClient()
    try:
        row = client.campaign(campaign_id)
    finally:
        client.close()
    if table:
        print_table([{'field': key, 'value': value} for key, value in row.items()], ['field', 'value'], ['Field', 'Value'])
    else:
        print_json(row)


app.add_typer(campaigns_app, name='campaigns')
app.add_typer(create_cache_app(get_config), name='cache')


def main():
    run_app(app)


if __name__ == '__main__':
    main()
