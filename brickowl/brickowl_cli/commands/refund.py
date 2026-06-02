"""Refund commands for Brickowl CLI.

Browser automation for issuing and querying refunds on Brick Owl orders.
"""
COMMAND_CREDENTIALS = {
    "info": ["browser_session"],
    "issue": ["browser_session"],
    "full": ["browser_session"],
}

import typer
from typing import Optional

from cli_tools_shared.output import print_error, print_json, print_table, print_success

app = typer.Typer(help="Manage Brick Owl refunds", no_args_is_help=True)


@app.command("info")
def refund_info(
    order_id: str = typer.Argument(..., help="The order ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get refund information for an order.

    Shows order total, prior refunds, and maximum refund amount.

    Examples:
        brickowl refund info 12345678
        brickowl refund info 12345678 --table
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        data = browser.get_order_info(order_id)
        if table:
            print_table(
                [data],
                ["order_id", "order_total", "buyer_name", "status", "payment_amount", "transaction_id"],
                ["Order ID", "Total", "Customer", "Status", "Payment", "Transaction ID"],
            )
        else:
            print_json(data)
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to get order info: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()


@app.command("issue")
def refund_issue(
    order_id: str = typer.Argument(..., help="The order ID"),
    amount: float = typer.Argument(..., help="Refund amount in dollars"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Refund reason"),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Message to buyer"),
):
    """
    Issue a partial refund for an order.

    Examples:
        brickowl refund issue 12345678 5.00
        brickowl refund issue 12345678 5.00 --reason "Missing Items"
        brickowl refund issue 12345678 5.00 --reason "Overcharged Shipping" --message "Refunding excess shipping"
    """
    from ..browser import get_browser

    kwargs = {}
    if reason is not None:
        kwargs["reason"] = reason

    browser = get_browser()
    try:
        data = browser.issue_refund(order_id, amount, **kwargs)
        print_json(data)
        if data.get("message"):
            print_success(data["message"])
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to issue refund: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()


@app.command("full")
def refund_full(
    order_id: str = typer.Argument(..., help="The order ID"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="Refund reason"),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Message to buyer"),
):
    """
    Issue a full refund for an order.

    Examples:
        brickowl refund full 12345678
        brickowl refund full 12345678 --reason "Cancel Order"
    """
    from ..browser import get_browser

    kwargs = {}
    if reason is not None:
        kwargs["reason"] = reason

    browser = get_browser()
    try:
        data = browser.issue_full_refund(order_id, **kwargs)
        print_json(data)
        if data.get("message"):
            print_success(data["message"])
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to issue full refund: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()
