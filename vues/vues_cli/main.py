"""Vues CLI: clipping campaigns, linked accounts, submissions and earnings.

Command surface and JSON conventions mirror the `clipster` CLI so the Trawler
clipping system can treat Vues as a campaign provider the same way. JSON on
stdout is the contract; `--table` is a convenience view.
"""

import typer
from typing import List, Optional

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_info, print_json, print_success, print_table

from . import __version__
from .client import VuesClient, get_client
from .config import get_config

# JSON is the full contract; these are only the default table columns.
CAMPAIGN_COLUMNS = ["id", "name", "status"]
SOCIAL_COLUMNS = ["id", "platform", "username", "status"]
SUBMISSION_COLUMNS = ["id", "campaign_id", "status", "url"]

app = create_app(name="vues",
                 help="Vues (evrgreen) clipping campaigns, linked accounts, submissions and earnings",
                 version=__version__, cache_support=False)
campaigns_app = typer.Typer(help="Vues campaigns", no_args_is_help=True)
account_app = typer.Typer(help="Current Vues creator account", no_args_is_help=True)
social_app = typer.Typer(help="Linked social accounts", no_args_is_help=True)
submissions_app = typer.Typer(help="Campaign submissions", no_args_is_help=True)
earnings_app = typer.Typer(help="Balance and earnings", no_args_is_help=True)

TABLE = typer.Option(False, "--table", "-t", help="Display as table")
PROPERTIES = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include")
FILTER = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)")
PROFILE = typer.Option(None, "--profile", help="Saved authentication profile name")
YES = typer.Option(False, "--yes", help="Authorize the change")
DRY_RUN = typer.Option(False, "--dry-run", help="Run every check and show the request without sending it")


def _client(profile: Optional[str]) -> VuesClient:
    return VuesClient(config=get_config(profile)) if profile else get_client()


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
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum number of campaigns"),
    filter: Optional[List[str]] = FILTER,
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
    profile: Optional[str] = PROFILE,
):
    """List campaigns the signed-in creator can see (requires auth; Vues gates all campaign data behind login)."""
    _list(lambda: _client(profile).list_campaigns(limit), filter, table, properties, "No campaigns found.",
          CAMPAIGN_COLUMNS)


@campaigns_app.command("get")
@command
def get_campaign(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
    profile: Optional[str] = PROFILE,
):
    """Get one campaign in full (CPM/rate, minimum views, budget, brief and rules, exactly as the API returns it)."""
    _record(_client(profile).get_campaign(campaign_id), table, properties)


@campaigns_app.command("join")
@command
def join_campaign(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    yes: bool = YES,
    dry_run: bool = DRY_RUN,
    table: bool = TABLE,
    profile: Optional[str] = PROFILE,
):
    """Apply to / join a campaign (the join endpoint is resolved from the API's own OpenAPI document)."""
    _guard(yes, dry_run, "join a campaign")
    _record(_client(profile).join_campaign(campaign_id, dry_run), table, None)


# ==================== account ====================

@account_app.command("get")
@command
def get_account(table: bool = TABLE, properties: Optional[str] = PROPERTIES, profile: Optional[str] = PROFILE):
    """Get the signed-in creator (identity and balance, exactly as /users/me returns them)."""
    _record(_client(profile).account(), table, properties)


# ==================== social-accounts ====================

@social_app.command("list")
@command
def list_social_accounts(
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum number of accounts"),
    filter: Optional[List[str]] = FILTER,
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
    profile: Optional[str] = PROFILE,
):
    """List linked social accounts (handle, platform, verification/eligibility, as the API returns them)."""
    _list(lambda: _client(profile).social_accounts(limit), filter, table, properties, "No linked accounts.",
          SOCIAL_COLUMNS)


# ==================== submissions ====================

@submissions_app.command("list")
@command
def list_submissions(
    campaign_id: Optional[str] = typer.Option(None, "--campaign-id", help="Only this campaign's submissions"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum number of submissions"),
    filter: Optional[List[str]] = FILTER,
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
    profile: Optional[str] = PROFILE,
):
    """List this account's submissions (status, tracked views, earnings, as the API returns them)."""
    _list(lambda: _client(profile).submissions(campaign_id, limit), filter, table, properties,
          "No submissions found.", SUBMISSION_COLUMNS)


@submissions_app.command("get")
@command
def get_submission(
    submission_id: str = typer.Argument(..., help="Submission ID"),
    table: bool = TABLE,
    properties: Optional[str] = PROPERTIES,
    profile: Optional[str] = PROFILE,
):
    """Get one submission by ID."""
    _record(_client(profile).submission(submission_id), table, properties)


@submissions_app.command("create")
@command
def create_submission(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    url: str = typer.Option(..., "--url", help="Full TikTok post URL from a linked account"),
    yes: bool = typer.Option(False, "--yes", help="Affirm the post follows the campaign rules and submit it"),
    dry_run: bool = DRY_RUN,
    table: bool = TABLE,
    profile: Optional[str] = PROFILE,
):
    """Submit a TikTok post once; an already-submitted URL returns status existing (never double-submits)."""
    _guard(yes, dry_run, "submit")
    _record(_client(profile).create_submission(campaign_id, url, dry_run), table, None)


# ==================== earnings ====================

@earnings_app.command("get")
@command
def get_earnings(table: bool = TABLE, properties: Optional[str] = PROPERTIES, profile: Optional[str] = PROFILE):
    """Get balance, pending, paid and withdrawal minimum (whatever the earnings/balance endpoint exposes)."""
    _record(_client(profile).earnings(), table, properties)


def _login(config, force: bool) -> None:
    """Print the one-time setup, then run the browser (Google/Apple) sign-in."""
    from cli_tools_shared.auth_commands import _handle_browser_login

    instructions = getattr(config, "AUTH_SETUP_INSTRUCTIONS", "")
    if instructions:
        print_info(instructions)
    _handle_browser_login(config, "vues", force)
    try:
        user = VuesClient(config=config).account()
        print_success(f"Signed in to Vues as {user.get('email') or user.get('id')}")
    except ClientError:
        # The browser step may still be incomplete (e.g. no account yet); auth
        # status reports the authoritative state.
        pass


app.add_typer(campaigns_app, name="campaigns")
app.add_typer(account_app, name="account")
app.add_typer(social_app, name="social-accounts")
app.add_typer(submissions_app, name="submissions")
app.add_typer(earnings_app, name="earnings")
app.add_typer(create_auth_app(get_config, tool_name="vues", login_handler=_login), name="auth")


def main():
    run_app(app)


if __name__ == "__main__":
    main()
