"""Refund commands for PayPal CLI."""
COMMAND_CREDENTIALS = {
    "create": ["no_auth"],
    "from-bricklink": ["no_auth"],
}

import json
import os
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import typer

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import handle_error, print_error, print_json

from ..browser_client import get_browser_client
from ..client import get_api_client

app = typer.Typer(help="Manage refunds", no_args_is_help=True)


_CROSS_CLI_ENV_KEYS = (
    "ACCESS_TOKEN",
    "API_KEY",
    "BASE_URL",
    "CLIENT_ID",
    "CLIENT_SECRET",
    "REFRESH_TOKEN",
)


def _normalize_amount(amount: Optional[str]) -> Optional[str]:
    if amount is None:
        return None
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise ClientError("amount must be a decimal value such as 4.50") from exc
    if value <= 0:
        raise ClientError("amount must be greater than 0")
    return f"{value.quantize(Decimal('0.01'))}"


def _idempotency_key(*parts: object) -> str:
    return "-".join(str(part).replace(" ", "-") for part in parts if part is not None)


def _refund_plan(
    *,
    capture_id: str,
    amount: Optional[str],
    currency: str,
    invoice_id: Optional[str],
    custom_id: Optional[str],
    note_to_payer: Optional[str],
    idempotency_key: str,
) -> dict:
    return {
        "capture_id": capture_id,
        "refund_type": "partial" if amount is not None else "full",
        "amount": {"value": amount, "currency_code": currency} if amount is not None else None,
        "invoice_id": invoice_id,
        "custom_id": custom_id,
        "note_to_payer": note_to_payer,
        "idempotency_key": idempotency_key,
    }


def _require_confirmation(*, yes: bool, dry_run: bool) -> None:
    if dry_run or yes:
        return
    print_error("Refusing to issue refund without --yes or --dry-run")
    raise typer.Exit(1)


def _cross_cli_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _CROSS_CLI_ENV_KEYS:
        env.pop(key, None)
    return env


def get_bricklink_refund_info(order_id: str) -> dict:
    """Read BrickLink refund metadata for an order as JSON."""
    completed = subprocess.run(
        ["bricklink", "refund", "info", order_id],
        check=False,
        capture_output=True,
        env=_cross_cli_env(),
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ClientError(f"bricklink refund info failed for order {order_id}: {detail}")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ClientError("bricklink refund info did not return JSON") from exc
    if not isinstance(data, dict):
        raise ClientError("bricklink refund info returned an unexpected JSON shape")
    return data


def get_bricklink_order(order_id: str) -> dict:
    """Read BrickLink order metadata for PayPal matching."""
    completed = subprocess.run(
        ["bricklink", "order", "get", order_id],
        check=False,
        capture_output=True,
        env=_cross_cli_env(),
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ClientError(f"bricklink order get failed for order {order_id}: {detail}")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ClientError("bricklink order get did not return JSON") from exc
    if not isinstance(data, dict):
        raise ClientError("bricklink order get returned an unexpected JSON shape")
    return data


def load_bricklink_order(order_id: str, order_json: Optional[str]) -> dict:
    """Load BrickLink order JSON from a file, or fetch it from BrickLink CLI."""
    if order_json is None:
        return get_bricklink_order(order_id)

    path = Path(order_json).expanduser()
    if not path.exists():
        raise ClientError(f"BrickLink order JSON file does not exist: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ClientError(f"BrickLink order JSON file is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ClientError("BrickLink order JSON file must contain an object")

    order = data.get("order") if isinstance(data.get("order"), dict) else data
    if str(order.get("order_id") or "") != str(order_id):
        raise ClientError(
            f"BrickLink order JSON file is for order {order.get('order_id')!r}, not {order_id}"
        )
    return order


@app.command("create")
def refunds_create(
    capture_id: str = typer.Argument(..., help="PayPal capture ID to refund"),
    amount: Optional[str] = typer.Option(None, "--amount", "-a", help="Partial refund amount. Omit for full refund."),
    currency: str = typer.Option("USD", "--currency", "-c", help="ISO currency code"),
    invoice_id: Optional[str] = typer.Option(None, "--invoice-id", help="PayPal refund invoice ID"),
    custom_id: Optional[str] = typer.Option(None, "--custom-id", help="PayPal refund custom ID"),
    note_to_payer: Optional[str] = typer.Option(None, "--note-to-payer", help="Note visible to the payer"),
    idempotency_key: Optional[str] = typer.Option(None, "--idempotency-key", help="PayPal-Request-Id for idempotence"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the planned refund without issuing it"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Issue the refund without an interactive prompt"),
):
    """Issue a full or partial refund for a PayPal capture."""
    try:
        normalized_amount = _normalize_amount(amount)
        request_id = idempotency_key or _idempotency_key(
            "paypal-refund",
            capture_id,
            normalized_amount or "full",
            currency,
        )
        plan = _refund_plan(
            capture_id=capture_id,
            amount=normalized_amount,
            currency=currency,
            invoice_id=invoice_id,
            custom_id=custom_id,
            note_to_payer=note_to_payer,
            idempotency_key=request_id,
        )
        _require_confirmation(yes=yes, dry_run=dry_run)

        if dry_run:
            print_json({"dry_run": True, "request": plan})
            return

        result = get_api_client().refund_capture(
            capture_id=capture_id,
            amount=normalized_amount,
            currency=currency,
            invoice_id=invoice_id,
            custom_id=custom_id,
            note_to_payer=note_to_payer,
            idempotency_key=request_id,
        )
        print_json(result)
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))


@app.command("from-bricklink")
def refunds_from_bricklink(
    order_id: str = typer.Argument(..., help="BrickLink order ID"),
    amount: Optional[str] = typer.Option(None, "--amount", "-a", help="Partial refund amount. Omit for full refund."),
    details: Optional[str] = typer.Option(None, "--details", "-d", help="Note visible to the payer"),
    order_json: Optional[str] = typer.Option(
        None,
        "--order-json",
        help="Path to verified BrickLink order JSON. Omit to run `bricklink order get`.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the planned refund without issuing it"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Issue the refund without an interactive prompt"),
):
    """Issue a PayPal refund using PayPal transaction search and BrickLink order context."""
    browser_client = None
    try:
        bricklink_order = load_bricklink_order(order_id, order_json)
        normalized_amount = _normalize_amount(amount)
        browser_client = get_browser_client()
        match = browser_client.find_payment_for_order(
            bricklink_order,
            order_id=order_id,
            refund_amount=normalized_amount,
        )
        transaction_id = match["transaction"]["id"]
        refund_details = match["refund_details"]
        match_currency = match["order"]["currency"]
        refund_amount = normalized_amount
        if refund_amount is None:
            max_allowed = (refund_details.get("amount") or {}).get("maxAllowedRefundAmount") or {}
            refund_amount = str(max_allowed.get("formattedValue") or max_allowed.get("value") or "")
            if not refund_amount:
                raise ClientError("PayPal refund details did not include a refundable amount")
        request = {
            "transaction_id": transaction_id,
            "refund_type": "partial" if normalized_amount is not None else "full",
            "amount": {"value": refund_amount, "currency_code": match_currency},
            "invoice_number": f"BL-{order_id}",
            "note_to_buyer": details,
        }
        if dry_run:
            print_json({"dry_run": True, "bricklink_order": bricklink_order, "paypal_match": match, "request": request})
            return

        _require_confirmation(yes=yes, dry_run=dry_run)
        result = browser_client.refund_payment(
            transaction_id=transaction_id,
            amount=refund_amount,
            currency=match_currency,
            invoice_number=f"BL-{order_id}",
            note_to_buyer=details,
        )
        print_json({"bricklink_order": bricklink_order, "paypal_match": match, **result})
    except ClientError as exc:
        raise typer.Exit(handle_error(exc))
    finally:
        if browser_client is not None:
            browser_client.close()
