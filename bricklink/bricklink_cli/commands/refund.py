"""Refund commands for Bricklink CLI (browser-based)."""
COMMAND_CREDENTIALS = {
    "full": [
        "browser_session"
    ],
    "info": [
        "browser_session"
    ],
    "issue": [
        "browser_session"
    ]
}

import typer
from typing import Optional

from ..display import print_detail
from cli_tools_shared.output import print_json, print_success, handle_error
from . import run_browser

app = typer.Typer(help="Manage refunds (browser)", no_args_is_help=True)


@app.command("info")
def refund_info(
    order_id: str = typer.Argument(..., help="Order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get refund page info for an order (browser-based).

    Shows transaction ID, payment processor, prior refunds, buyer info,
    and refund activity history.

    Examples:
        bricklink refund info 12345678
        bricklink refund info 12345678 --table
    """
    try:
        data = run_browser(lambda browser: browser.get_refund_info(order_id))
        print_detail(data, table)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("issue")
def refund_issue(
    order_id: str = typer.Argument(..., help="Order ID"),
    amount: float = typer.Argument(..., help="Refund amount in dollars"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Refund reason"),
    details: Optional[str] = typer.Option(None, "--details", "-d", help="Refund details (max 200 chars)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fill form and verify Review is enabled; do NOT submit"),
):
    """
    Issue a partial refund for an order (browser-based).

    Default reason: "Item was missing or unsatisfactory"

    Examples:
        bricklink refund issue 12345678 5.00
        bricklink refund issue 12345678 3.50 --reason "Overcharged shipping"
        bricklink refund issue 12345678 2.00 --details "Missing 1x brick 3001"
    """
    try:
        result = run_browser(
            lambda browser: browser.issue_refund(
                order_id=order_id,
                amount=amount,
                reason=reason,
                details=details,
                dry_run=dry_run,
            )
        )

        if result.get("success"):
            print_success(f"Refund of ${amount:.2f} issued for order {order_id}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("full")
def refund_full(
    order_id: str = typer.Argument(..., help="Order ID"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Refund reason"),
    details: Optional[str] = typer.Option(None, "--details", "-d", help="Refund details (max 200 chars)"),
):
    """
    Issue a full refund for an order (browser-based).

    Default reason: "Buyer and Seller agreed to cancel order"

    Examples:
        bricklink refund full 12345678
        bricklink refund full 12345678 --reason "Seller cannot complete transaction"
        bricklink refund full 12345678 --details "Out of stock on multiple items"
    """
    try:
        result = run_browser(
            lambda browser: browser.issue_full_refund(
                order_id=order_id,
                reason=reason,
                details=details,
            )
        )

        if result.get("success"):
            print_success(f"Full refund issued for order {order_id}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
