"""X API credit purchase commands."""

from decimal import Decimal, InvalidOperation
from typing import Optional

import typer

from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import (
    command,
    confirm_destructive_action,
    print_json,
    print_table,
)

from ..browser_client import DEVELOPER_CONSOLE_URL, XBrowserClient


app = typer.Typer(help="Purchase X API credits through the saved Developer Console browser session", no_args_is_help=True)


def _format_amount_usd(amount: Decimal) -> str:
    try:
        cents = amount.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ClientError("Credit amount must be a valid dollar amount.") from exc
    if amount <= 0:
        raise ClientError("Credit amount must be greater than 0.")
    if amount != cents:
        raise ClientError("Credit amount must use dollars and cents, for example 10.00.")
    return format(cents, "f")


def _parse_amount_usd(amount: str) -> str:
    try:
        parsed = Decimal(amount)
    except InvalidOperation as exc:
        raise ClientError("Credit amount must be a valid dollar amount.") from exc
    return _format_amount_usd(parsed)


def _credit_plan(amount_usd: str, *, dry_run: bool) -> dict:
    return {
        "action": "purchase_credits",
        "amount_usd": amount_usd,
        "currency": "USD",
        "entry_url": DEVELOPER_CONSOLE_URL,
        "requires_browser_session": True,
        "will_open_browser": not dry_run,
        "will_submit_purchase": not dry_run,
        "would_submit_purchase": dry_run,
        "completion_required": "Command must return purchase-success evidence from X or fail.",
    }


@app.command("add")
@command
def add_credits(
    amount: str = typer.Argument(..., help="Credit amount in USD"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without submitting payment"),
    yes: bool = typer.Option(False, "--yes", help="Confirm purchase and payment submission"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Browser-session auth profile name"),
):
    """Purchase X API credits using the saved Developer Console browser session."""
    amount_usd = _parse_amount_usd(amount)
    if dry_run:
        data = _credit_plan(amount_usd, dry_run=True)
        if table:
            print_table(data)
        else:
            print_json(data)
        return

    confirm_destructive_action(
        f"Purchase ${amount_usd} in X API credits?",
        assume_yes=yes,
        action_description=f"purchase ${amount_usd} in X API credits",
        skip_flag_hint="--yes",
    )

    data = _credit_plan(amount_usd, dry_run=False)
    data.update(XBrowserClient(profile=profile).purchase_credits(amount_usd))
    if table:
        print_table(data)
    else:
        print_json(data)


COMMAND_CREDENTIALS = {
    "add": [
        CredentialType.NO_AUTH.value,
    ],
}
