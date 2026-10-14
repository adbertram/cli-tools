"""Main entry point for Clipster CLI."""

import typer
from typing import List, Optional
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_success, print_table

from . import __version__
from .client import ClipsterClient, get_client
from .config import get_config


CAMPAIGN_COLUMNS = ["id", "name", "status", "category", "web_url"]
SOCIAL_COLUMNS = ["account_id", "platform", "username", "oauth_connected", "linked_at"]
POST_COLUMNS = ["post_id", "post_url", "published_at"]
SUBMISSION_COLUMNS = ["id", "campaign_name", "status", "post_url", "view_count", "potential_earnings"]
TRANSACTION_COLUMNS = ["created_at", "type", "name", "full_amount"]

app = create_app(name="clipster", help="Clipster clipping campaigns, linked accounts, submissions and earnings",
                 version=__version__)
campaigns_app = typer.Typer(help="Clipster campaigns", no_args_is_help=True)
account_app = typer.Typer(help="Current Clipster creator account", no_args_is_help=True)
social_app = typer.Typer(help="Linked social accounts", no_args_is_help=True)
submissions_app = typer.Typer(help="Campaign submissions", no_args_is_help=True)
earnings_app = typer.Typer(help="Balance, earnings and transactions", no_args_is_help=True)

TABLE = typer.Option(False, "--table", "-t", help="Display as table")
PROPERTIES = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include")
FILTER = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)")
YES = typer.Option(False, "--yes", help="Authorize the change")
DRY_RUN = typer.Option(False, "--dry-run", help="Run every check and show the request without sending it")


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _render(rows: List[dict], table: bool, properties: Optional[str], empty: str, columns: List[str]) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)
    if not table:
        print_json(rows)
        return
    if not rows:
        print_info(empty)
        return
    columns = fields or columns
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


def _list(fetch, filters, table, properties, empty, columns) -> None:
    _validate(filters)
    rows = fetch()
    if filters:
        rows = apply_filters(rows, filters)
    _render(rows, table, properties, empty, columns)


def _record(row: dict, table: bool, properties: Optional[str]) -> None:
    """Print one record as JSON, or as a field/value table."""
    if _property_fields(properties):
        row = apply_properties_filter([row], properties)[0]
    if table:
        print_table([{"field": key, "value": str(value)} for key, value in row.items()],
                    ["field", "value"], ["Field", "Value"])
    else:
        print_json(row)


def _guard(yes: bool, dry_run: bool, action: str) -> None:
    if yes and dry_run:
        raise ClientError("Pass either --yes or --dry-run, not both")
    if not (yes or dry_run):
        raise ClientError(f"Refusing to {action} without --yes or --dry-run")


# ==================== campaigns ====================

@campaigns_app.command("list")
@command
def list_campaigns(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of campaigns (reads as many pages as needed)"),
    filter: Optional[List[str]] = FILTER,
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """List the public campaign catalog exactly as the API returns it, plus web_url."""
    _list(lambda: get_client().list_campaigns(limit), filter, table, properties, "No campaigns found.",
          CAMPAIGN_COLUMNS)


@campaigns_app.command("get")
@command
def get_campaign(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """Get full campaign detail (rules, sounds, tags, limits, your earnings) plus account_eligibility."""
    _record(get_client().get_campaign(campaign_id), table, properties)


@campaigns_app.command("join")
@command
def join_campaign(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    yes: bool = YES,
    dry_run: bool = DRY_RUN,
    table: bool = TABLE,
):
    """Apply to an application-only campaign; open campaigns need no join (status not_required)."""
    _guard(yes, dry_run, "join a campaign")
    _record(get_client().join_campaign(campaign_id, dry_run), table, None)


# ==================== account ====================

@account_app.command("get")
@command
def get_account(table: bool = TABLE, properties: Optional[str] = PROPERTIES):
    """Get the signed-in creator (id, email, username, permissions, bio_linking_enabled)."""
    _record(get_client().account(), table, properties)


# ==================== social-accounts ====================

@social_app.command("list")
@command
def list_social_accounts(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of accounts"),
    filter: Optional[List[str]] = FILTER,
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """List linked social accounts (account_id, platform, username, oauth_connected)."""
    _list(lambda: get_client().social_accounts()[:limit], filter, table, properties, "No linked accounts.",
          SOCIAL_COLUMNS)


@social_app.command("get")
@command
def get_social_account(
    account_id: str = typer.Argument(..., help="account_id from social-accounts list"),
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """Get one linked account by account_id."""
    _record(get_client().social_account(account_id), table, properties)


@social_app.command("posts")
@command
def list_account_posts(
    account_id: str = typer.Argument(..., help="account_id from social-accounts list"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of posts"),
    filter: Optional[List[str]] = FILTER,
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """List recent posts Clipster sees on a linked account (post_id, post_url, published_at)."""
    _list(lambda: get_client().account_posts(account_id)[:limit], filter, table, properties, "No posts found.",
          POST_COLUMNS)


@social_app.command("link")
@command
def link_social_account(
    platform: str = typer.Option(..., "--platform", help="Platform: tiktok"),
    username: str = typer.Option(..., "--username", help="Account handle, with or without @"),
    yes: bool = YES,
    dry_run: bool = DRY_RUN,
    table: bool = TABLE,
):
    """Start bio-code linking; put the returned verification_code in the bio, then run verify."""
    _guard(yes, dry_run, "link an account")
    _record(get_client().link_social_account(platform, username, dry_run), table, None)


@social_app.command("verify")
@command
def verify_social_account(
    link_id: str = typer.Argument(..., help="link_id returned by link"),
    yes: bool = YES,
    dry_run: bool = DRY_RUN,
    table: bool = TABLE,
):
    """Finish bio-code linking after the verification code is in the account bio."""
    _guard(yes, dry_run, "verify an account link")
    _record(get_client().verify_social_account(link_id, dry_run), table, None)


# ==================== submissions ====================

@submissions_app.command("list")
@command
def list_submissions(
    campaign_id: Optional[str] = typer.Option(None, "--campaign-id", help="Only this campaign's submissions"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of submissions"),
    filter: Optional[List[str]] = FILTER,
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """List this account's submissions (status, post_url, view_count, potential/paid_out earnings)."""
    _list(lambda: get_client().submissions(campaign_id, limit), filter, table, properties,
          "No submissions found.", SUBMISSION_COLUMNS)


@submissions_app.command("get")
@command
def get_submission(
    submission_id: str = typer.Argument(..., help="Submission ID"),
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """Get one submission by ID."""
    _record(get_client().submission(submission_id), table, properties)


@submissions_app.command("create")
@command
def create_submission(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    url: str = typer.Option(..., "--url", help="Full TikTok post URL from a linked account"),
    yes: bool = typer.Option(False, "--yes", help="Affirm the post follows the campaign rules and submit it"),
    dry_run: bool = DRY_RUN,
    table: bool = TABLE,
):
    """Submit a TikTok post once; an already-submitted URL returns status existing."""
    _guard(yes, dry_run, "submit")
    _record(get_client().create_submission(campaign_id, url, dry_run), table, None)


# ==================== earnings ====================

@earnings_app.command("get")
@command
def get_earnings(table: bool = TABLE, properties: Optional[str] = PROPERTIES):
    """Get balances (campaign, referral, pending, lifetime) and totals (earned, videos, views)."""
    _record(get_client().earnings(), table, properties)


@earnings_app.command("transactions")
@command
def list_transactions(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of transactions"),
    filter: Optional[List[str]] = FILTER,
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
):
    """List balance transactions."""
    _list(lambda: get_client().transactions(limit), filter, table, properties, "No transactions found.",
          TRANSACTION_COLUMNS)


def _login(config, force: bool) -> None:
    """Unattended email-passcode login; skipped when the saved session still works."""
    client = ClipsterClient(config=config)
    if not force:
        try:
            user = client.account(allow_login=False)
            print_info(f"Already signed in as {user['email']} (use --force to sign in again)")
            return
        except ClientError:
            pass
    client.login()
    print_success("Signed in to Clipster")


app.add_typer(campaigns_app, name="campaigns")
app.add_typer(account_app, name="account")
app.add_typer(social_app, name="social-accounts")
app.add_typer(submissions_app, name="submissions")
app.add_typer(earnings_app, name="earnings")
app.add_typer(create_auth_app(get_config, tool_name="clipster", login_handler=_login), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
