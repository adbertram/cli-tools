"""Payout commands for PayPal CLI."""

import json
from typing import Optional

import typer

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import handle_error, print_info, print_json, print_table

from ..client import get_api_client

COMMAND_CREDENTIALS = {
    "cancel-item": ["oauth"],
    "create": ["oauth"],
    "get": ["oauth"],
    "get-item": ["oauth"],
}

app = typer.Typer(help="Manage batch payouts")


@app.command("create")
def payouts_create(
    receiver: Optional[str] = typer.Option(None, "--receiver", "-r", help="Recipient email address"),
    amount: Optional[str] = typer.Option(None, "--amount", "-a", help="Payment amount (e.g., '10.00')"),
    currency: str = typer.Option("USD", "--currency", "-c", help="ISO currency code"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Message to recipient"),
    email_subject: Optional[str] = typer.Option(None, "--email-subject", help="Subject line for PayPal notification email"),
    email_message: Optional[str] = typer.Option(None, "--email-message", help="Body of PayPal notification email"),
    items_json: Optional[str] = typer.Option(None, "--items-json", help="JSON array for multi-recipient batch payouts"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Create a batch payout to one or more recipients.

    For a single recipient, use --receiver and --amount.
    For multiple recipients, use --items-json with a JSON array.

    Examples:
        paypal payouts create --receiver user@example.com --amount 10.00
        paypal payouts create --receiver user@example.com --amount 25.50 --note "Payment for services"
        paypal payouts create --items-json '[{"receiver":"a@example.com","amount":"10.00"},{"receiver":"b@example.com","amount":"20.00"}]'
    """
    try:
        if items_json:
            raw_items = json.loads(items_json)
            items = []
            for i, item in enumerate(raw_items):
                items.append(
                    {
                        "recipient_type": "EMAIL",
                        "amount": {
                            "value": item["amount"],
                            "currency": item.get("currency", currency),
                        },
                        "receiver": item["receiver"],
                        "note": item.get("note", note or ""),
                        "sender_item_id": f"item_{i}",
                    }
                )
        elif receiver and amount:
            items = [
                {
                    "recipient_type": "EMAIL",
                    "amount": {
                        "value": amount,
                        "currency": currency,
                    },
                    "receiver": receiver,
                    "note": note or "",
                    "sender_item_id": "item_0",
                }
            ]
        else:
            print_info("Provide either --receiver and --amount, or --items-json.")
            raise typer.Exit(1)

        client = get_api_client()
        result = client.create_payout(items, email_subject=email_subject, email_message=email_message)

        if table:
            header = result.get("batch_header", {})
            rows = [
                {
                    "batch_id": header.get("payout_batch_id", "N/A"),
                    "status": header.get("batch_status", "N/A"),
                    "sender_batch_id": header.get("sender_batch_header", {}).get("sender_batch_id", "N/A"),
                }
            ]
            print_table(rows, ["batch_id", "status", "sender_batch_id"], ["Batch ID", "Status", "Sender Batch ID"])
        else:
            print_json(result)
    except json.JSONDecodeError as exc:
        print_info(f"Invalid JSON in --items-json: {exc}")
        raise typer.Exit(1)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def payouts_get(
    batch_id: str = typer.Argument(..., help="Payout batch ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get batch payout status and details.

    Examples:
        paypal payouts get BATCH_ID_HERE
        paypal payouts get BATCH_ID_HERE -t
    """
    try:
        client = get_api_client()
        result = client.get_payout(batch_id)

        if table:
            header = result.get("batch_header", {})
            rows = [
                {
                    "batch_id": header.get("payout_batch_id", "N/A"),
                    "status": header.get("batch_status", "N/A"),
                    "amount": header.get("amount", {}).get("value", "N/A"),
                    "currency": header.get("amount", {}).get("currency", "N/A"),
                    "fees": header.get("fees", {}).get("value", "N/A"),
                }
            ]
            print_table(
                rows,
                ["batch_id", "status", "amount", "currency", "fees"],
                ["Batch ID", "Status", "Amount", "Currency", "Fees"],
            )

            items = result.get("items", [])
            if items:
                print_info("\nPayout Items:")
                item_rows = []
                for item in items:
                    payout_item = item.get("payout_item", {})
                    item_rows.append(
                        {
                            "item_id": item.get("payout_item_id", "N/A"),
                            "status": item.get("transaction_status", "N/A"),
                            "receiver": payout_item.get("receiver", "N/A"),
                            "amount": payout_item.get("amount", {}).get("value", "N/A"),
                        }
                    )
                print_table(item_rows, ["item_id", "status", "receiver", "amount"], ["Item ID", "Status", "Receiver", "Amount"])
        else:
            print_json(result)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get-item")
def payouts_get_item(
    item_id: str = typer.Argument(..., help="Payout item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get individual payout item details.

    Examples:
        paypal payouts get-item ITEM_ID_HERE
        paypal payouts get-item ITEM_ID_HERE -t
    """
    try:
        client = get_api_client()
        result = client.get_payout_item(item_id)

        if table:
            payout_item = result.get("payout_item", {})
            rows = [
                {
                    "item_id": result.get("payout_item_id", "N/A"),
                    "status": result.get("transaction_status", "N/A"),
                    "receiver": payout_item.get("receiver", "N/A"),
                    "amount": payout_item.get("amount", {}).get("value", "N/A"),
                    "currency": payout_item.get("amount", {}).get("currency", "N/A"),
                    "fee": result.get("payout_item_fee", {}).get("value", "N/A"),
                }
            ]
            print_table(
                rows,
                ["item_id", "status", "receiver", "amount", "currency", "fee"],
                ["Item ID", "Status", "Receiver", "Amount", "Currency", "Fee"],
            )
        else:
            print_json(result)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("cancel-item")
def payouts_cancel_item(
    item_id: str = typer.Argument(..., help="Payout item ID to cancel"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Cancel an unclaimed payout item.

    Only items with UNCLAIMED status can be cancelled.

    Examples:
        paypal payouts cancel-item ITEM_ID_HERE
    """
    try:
        client = get_api_client()
        result = client.cancel_payout_item(item_id)

        if table:
            rows = [
                {
                    "item_id": result.get("payout_item_id", "N/A"),
                    "status": result.get("transaction_status", "N/A"),
                }
            ]
            print_table(rows, ["item_id", "status"], ["Item ID", "Status"])
        else:
            print_json(result)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
