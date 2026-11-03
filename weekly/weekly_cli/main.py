"""Weekly CLI entry point."""
from pathlib import Path
from functools import wraps
from typing import Optional, List
import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.profiles_commands import create_profiles_app
from cli_tools_shared.config import profile_secret_field_map
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command, print_json, print_output, print_success, print_table
from cli_tools_shared.filters import apply_properties_filter
from . import __version__
from .config import get_config
from .session import import_capture, import_export, refresh, delete_profile_secret
from .transactions import list_transactions
from .firestore import list_documents, user_preferences, current_week, create_category
from .spending import create, update, split
from .ignoring import ignore
from .weeks import create as create_week, delete as delete_week
from .bills import create as create_bill, INTERVALS, CATEGORIES, EMOJI_COLORS


def login_handler(config, force):
    raise ClientError('Use weekly auth import-capture SESSION_DIRECTORY after capturing a Weekly login')


app = create_app(name='weekly', help='Weekly budgeting CLI', version=__version__)
profiles = create_profiles_app(get_config, 'weekly')


def with_secret_cleanup(callback):
    @wraps(callback)
    def wrapped(*args, **kwargs):
        name = kwargs.get('name') or args[0]
        config = get_config(profile=name)
        secret_name = profile_secret_field_map(config.env_file_path).get('SESSION_DATA')
        result = callback(*args, **kwargs)
        if secret_name:
            delete_profile_secret(secret_name)
        return result
    return wrapped


for command_info in profiles.registered_commands:
    if command_info.name in ('delete', 'remove'):
        command_info.callback = with_secret_cleanup(command_info.callback)

auth = create_auth_app(get_config, tool_name='weekly', login_handler=login_handler, profiles_app=profiles)


@auth.command('import-capture')
@command
def capture_import(directory: Path = typer.Argument(..., help='Stopped private capture session directory'), profile: Optional[str] = typer.Option(None, '--profile')):
    """Import and verify a captured Weekly login and refresh."""
    import_capture(get_config(profile), directory)
    print_success('Weekly session imported and verified')


@auth.command('import-export')
@command
def export_import(directory: Path = typer.Argument(..., help='Stopped or active private export capture directory'), flow_file: str = typer.Option('wg-export.flows', '--flow-file', help='Flow filename inside capture directory'), profile: Optional[str] = typer.Option(None, '--profile')):
    """Import transaction export settings from an authorized capture."""
    import_export(get_config(profile), directory, flow_file)
    print_success('Transaction export settings imported')


@auth.command('refresh')
@command
def auth_refresh(profile: Optional[str] = typer.Option(None, '--profile')):
    """Refresh and verify the saved Weekly session."""
    refresh(get_config(profile))
    print_success('Weekly session refreshed')


transactions = typer.Typer(help='Read transactions and manage spending', no_args_is_help=True)



def render_rows(rows, properties, table, default_columns=None, single=False):
    rows = apply_properties_filter(rows, properties)
    if table:
        columns = ([x.strip() for x in properties.split(',') if x.strip()] if properties else default_columns)
        if columns is None and single:
            columns = list(rows[0])
        print_table(rows, columns, columns)
    else:
        print_json(rows[0] if single else rows)


@transactions.command('list')
@command
def transactions_list(
    range_key: str = typer.Option('all', '--range', help='Export range: all or month_to_date'),
    unreviewed: bool = typer.Option(False, '--unreviewed', help='List the current-week review queue (requires all range)'),
    timezone_offset: Optional[int] = typer.Option(None, '--timezone-offset', help='Override the captured timezone offset'),
    limit: Optional[int] = typer.Option(None, '--limit', '-l', min=1, help='Maximum results (no limit by default)'),
    filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter: field:op:value (e.g., name:eq:value)'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields, supports dot notation'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """List transactions in the selected export range."""
    if range_key not in ('all', 'month_to_date'):
        raise ClientError('Range must be all or month_to_date')
    rows = list_transactions(get_config(profile), range_key, timezone_offset, limit, filter, unreviewed=unreviewed)
    render_rows(rows, properties, table, ['Id', 'Title', 'Date', 'Amount'])


@transactions.command('get')
@command
def transactions_get(
    transaction_id: str = typer.Argument(...),
    range_key: str = typer.Option('all', '--range', help='Export range: all or month_to_date'),
    timezone_offset: Optional[int] = typer.Option(None, '--timezone-offset'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields, supports dot notation'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """Find one transaction in the selected export range."""
    if range_key not in ('all', 'month_to_date'):
        raise ClientError('Range must be all or month_to_date')
    matches = [row for row in list_transactions(get_config(profile), range_key, timezone_offset) if row['Id'] == transaction_id]
    if len(matches) != 1:
        raise ClientError('Transaction not found or ID is ambiguous in the selected export range')
    render_rows(matches, properties, table, single=True)


@transactions.command('create')
@command
def spending_create(
    title: str = typer.Option(..., '--title'),
    amount: str = typer.Option(..., '--amount'),
    spending_date: Optional[str] = typer.Option(None, '--date', help='YYYY-MM-DD; defaults to today in account timezone'),
    category: str = typer.Option(..., '--category', help='Saved category name'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """Create a manual safe-to-spend entry."""
    print_output(create(get_config(profile), title, amount, spending_date, category), table=table)


@transactions.command('update')
@command
def spending_update(
    transaction_id: str = typer.Argument(...),
    amount: Optional[str] = typer.Option(None, '--amount', help='Positive spending amount'),
    title: Optional[str] = typer.Option(None, '--title', help='Spending description'),
    category: Optional[str] = typer.Option(None, '--category', help='Saved category name'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """Update a safe-to-spend category, or manual entry amount and title."""
    print_output(update(get_config(profile), transaction_id, amount, title, category), table=table)


@transactions.command('ignore')
@command
def transaction_ignore(
    transaction_id: str = typer.Argument(..., help='Unreviewed bank transaction ID'),
    dry_run: bool = typer.Option(False, '--dry-run', help='Preview the change without writing'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """Ignore an unreviewed bank transaction; retain its original bank details."""
    print_output(ignore(get_config(profile), transaction_id, dry_run), table=table)


@transactions.command('split')
@command
def spending_split(
    transaction_id: str = typer.Argument(...),
    parts: List[str] = typer.Option(..., '--part', help='Split part as AMOUNT:CATEGORY; repeat for each part'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile name'),
):
    """Split a bank-linked expense into safe-to-spend categories."""
    print_output(split(get_config(profile), transaction_id, parts), table=table)


balances = typer.Typer(help='Read linked account balances', no_args_is_help=True)


@balances.command('list')
@command
def balances_list(
    limit: Optional[int] = typer.Option(None, '--limit', '-l', min=1, help='Maximum results (no limit by default)'),
    filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter: field:op:value (e.g., name:eq:value)'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields, supports dot notation'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """List saved account balance records."""
    rows = list_documents(get_config(profile), 'accounts', limit=limit, filters=filter)
    render_rows(rows, properties, table, ['id', 'name', 'current_balance', 'available_balance'])


budget = typer.Typer(help='Read Weekly budget records', no_args_is_help=True)


@budget.command('current')
@command
def budget_current(table: bool = typer.Option(False, '--table', '-t'), profile: Optional[str] = typer.Option(None, '--profile')):
    """Read current week, recurring items, funds and budget preferences."""
    config = get_config(profile)
    preferences = user_preferences(config)
    week = current_week(config, preferences)
    print_output({'week': week, 'recurring_items': list_documents(config, 'items'), 'funds': list_documents(config, 'funds'), 'preferences': preferences}, table=table)


app.add_typer(budget, name='budget')
bills = typer.Typer(help='Read and create recurring bills and income', no_args_is_help=True)


@bills.command('create')
@command
def bills_create(
    title: str = typer.Option(..., '--title', help='Recurring bill description'),
    amount: str = typer.Option(..., '--amount', help='Positive amount in exact cents'),
    interval: str = typer.Option(..., '--interval', help='Intervals: ' + ', '.join(INTERVALS)),
    category: str = typer.Option(..., '--category', help='Bill categories: ' + ', '.join(CATEGORIES)),
    emoji: str = typer.Option(..., '--emoji', help='Bill icon emoji'),
    emoji_color: str = typer.Option(..., '--emoji-color', help='Icon background colors: ' + ', '.join(EMOJI_COLORS)),
    kind: str = typer.Option('expense', '--kind', help='expense or income, independent of category'),
    next_date: Optional[str] = typer.Option(None, '--next-date', help='Optional next transaction date YYYY-MM-DD'),
    hide_from_reports: bool = typer.Option(False, '--hide-from-reports', help='Exclude this item from reports'),
    archived: bool = typer.Option(False, '--archived', help='Create archived, without affecting the weekly spending limit'),
    dry_run: bool = typer.Option(False, '--dry-run', help='Validate and preview without reading or writing the account'),
    table: bool = typer.Option(False, '--table', '-t', help='Display as a table'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile'),
):
    """Create a recurring bill or income item."""
    print_output(create_bill(get_config(profile), title, amount, interval, category,
                             emoji, emoji_color, kind, next_date, dry_run,
                             hide_from_reports, archived), table=table)


@bills.command('list')
@command
def bills_list(
    limit: Optional[int] = typer.Option(None, '--limit', '-l', min=1, help='Maximum results (no limit by default)'),
    filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter: field:op:value (e.g., title:contains:Rent)'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields, supports dot notation'),
    table: bool = typer.Option(False, '--table', '-t', help='Display as a table'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile'),
):
    """List saved recurring bills and income, preserving their native fields."""
    rows = list_documents(get_config(profile), 'items', limit=limit, filters=filter)
    render_rows(rows, properties, table, ['id', 'title', 'amount', 'interval', 'category'])


@bills.command('get')
@command
def bills_get(
    item_id: str = typer.Argument(..., help='Recurring bill or income ID'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p', help='Comma-separated fields, supports dot notation'),
    table: bool = typer.Option(False, '--table', '-t', help='Display as a table'),
    profile: Optional[str] = typer.Option(None, '--profile', help='Saved authentication profile'),
):
    """Get a saved recurring bill or income item by ID."""
    collection_get('items', item_id, properties, table, profile)


app.add_typer(bills, name='bills')
weeks = typer.Typer(help='Read and delete weeks; create completed historical weeks', no_args_is_help=True)


@weeks.command('delete')
@command
def weeks_delete(
    week_id: str = typer.Argument(..., help='Saved week ID'),
    dry_run: bool = typer.Option(False, '--dry-run', help='Preview the selected week and deletion effects without deleting'),
    yes: bool = typer.Option(False, '--yes', '-y', help='Delete the selected week budget record'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """Delete one week budget record; retain transactions and funds."""
    print_output(delete_week(get_config(profile), week_id, dry_run=dry_run, yes=yes), table=table)


@weeks.command('create')
@command
def weeks_create(
    start_date: str = typer.Option(..., '--start-date', help='Inclusive start date YYYY-MM-DD'),
    end_date: str = typer.Option(..., '--end-date', help='Inclusive end date YYYY-MM-DD'),
    spending_limit: str = typer.Option(..., '--spending-limit', help='Explicit weekly spending limit in exact cents'),
    dry_run: bool = typer.Option(False, '--dry-run', help='Return the proposed week without creating it'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """Create a completed past week with no rollover; current/future weeks are unsupported."""
    print_output(create_week(get_config(profile), start_date, end_date, spending_limit, dry_run), table=table)


@weeks.command('list')
@command
def weeks_list(
    limit: Optional[int] = typer.Option(None, '--limit', '-l', min=1),
    filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter: field:op:value (e.g., startDate:eq:2026-10-16)'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """List saved weeks with their inclusive dates and recorded limits."""
    rows = list_documents(get_config(profile), 'weekInstances', limit=limit, filters=filter)
    render_rows(rows, properties, table, ['id', 'startDate', 'endDate', 'allowanceAmount'])


categories = typer.Typer(help='Manage spending categories', no_args_is_help=True)


@categories.command('create')
@command
def categories_create(
    name: str = typer.Option(..., '--name', help='Unique spending category name'),
    color: str = typer.Option(..., '--color', help='Category color, for example red'),
    emoji: str = typer.Option(..., '--emoji', help='Category emoji'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """Create a Safe-to-Spend category, not a savings fund."""
    print_output(create_category(get_config(profile), name, color, emoji), table=table)


@categories.command('list')
@command
def categories_list(
    limit: Optional[int] = typer.Option(None, '--limit', '-l', min=1),
    filter: Optional[List[str]] = typer.Option(None, '--filter', '-f', help='Filter: field:op:value (e.g., name:eq:value)'),
    properties: Optional[str] = typer.Option(None, '--properties', '-p'),
    table: bool = typer.Option(False, '--table', '-t'),
    profile: Optional[str] = typer.Option(None, '--profile'),
):
    """List saved categories available for manual spending."""
    rows = list_documents(get_config(profile), 'tags', limit=limit, filters=filter)
    render_rows(rows, properties, table, ['id', 'name', 'color'])


def collection_get(collection, item_id, properties, table, profile):
    rows = [row for row in list_documents(get_config(profile), collection) if row['id'] == item_id]
    if len(rows) != 1:
        raise ClientError('Record not found or ID is ambiguous')
    render_rows(rows, properties, table, single=True)


@weeks.command('get')
@command
def week_get(item_id: str = typer.Argument(...), properties: Optional[str] = typer.Option(None, '--properties', '-p'), table: bool = typer.Option(False, '--table', '-t'), profile: Optional[str] = typer.Option(None, '--profile')):
    """Get a saved week, including its dates and recorded spending limit."""
    collection_get('weekInstances', item_id, properties, table, profile)


@categories.command('get')
@command
def category_get(item_id: str = typer.Argument(...), properties: Optional[str] = typer.Option(None, '--properties', '-p'), table: bool = typer.Option(False, '--table', '-t'), profile: Optional[str] = typer.Option(None, '--profile')):
    """Get a saved spending category by ID."""
    collection_get('tags', item_id, properties, table, profile)


@balances.command('get')
@command
def balance_get(item_id: str = typer.Argument(...), properties: Optional[str] = typer.Option(None, '--properties', '-p'), table: bool = typer.Option(False, '--table', '-t'), profile: Optional[str] = typer.Option(None, '--profile')):
    """Get a saved account balance by ID."""
    collection_get('accounts', item_id, properties, table, profile)


app.add_typer(categories, name='categories')
app.add_typer(weeks, name='weeks')
app.add_typer(balances, name='balances')
app.add_typer(transactions, name='transactions')
app.add_typer(auth, name='auth')
app.add_typer(create_cache_app(get_config), name='cache')


def main():
    run_app(app)


if __name__ == '__main__':
    main()
