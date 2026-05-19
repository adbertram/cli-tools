"""Transactions commands for Monarch CLI."""
import typer
from typing import Optional, List
from datetime import datetime, timedelta

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error
from ..models import Transaction
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Manage Monarch Money transactions")

COMMAND_CREDENTIALS = {
    "get": [
        "username_password"
    ],
    "list": [
        "username_password"
    ],
    "recurring": [
        "username_password"
    ],
    "update": [
        "username_password"
    ]
}


def _apply_properties_filter(items: List[dict], properties: str) -> List[dict]:
    """Filter items to include only specified properties."""
    if not properties:
        return items
    props = [p.strip() for p in properties.split(",")]
    return [{k: v for k, v in item.items() if k in props} for item in items]


def _extract_transactions(data: dict) -> list:
    """Extract transactions from API response."""
    txns = data.get("allTransactions", {}).get("results", [])
    result = []
    for t in txns:
        result.append(Transaction(
            id=str(t.get("id", "")),
            date=t.get("date", ""),
            amount=float(t.get("amount", 0) or 0),
            merchant=t.get("merchant", {}).get("name") if t.get("merchant") else t.get("plaidName"),
            raw_name=t.get("plaidName"),
            category=t.get("category", {}).get("name") if t.get("category") else None,
            account_id=str(t.get("account", {}).get("id")) if t.get("account") else None,
            account_name=t.get("account", {}).get("displayName") if t.get("account") else None,
            is_pending=t.get("isPending", False),
            notes=t.get("notes"),
            needs_review=bool(t.get("needsReview", False)),
            reviewed_at=t.get("reviewedAt"),
        ))
    return result


@app.command("list")
def transactions_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(500, "--limit", "-l", help="Maximum transactions to return"),
    start_date: Optional[str] = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end", "-e", help="End date (YYYY-MM-DD)"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Filter by account ID"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category ID"),
    search: Optional[str] = typer.Option(None, "--search", "-q", help="Search string"),
    days: Optional[int] = typer.Option(None, "--days", "-d", help="Last N days (shortcut for date range)"),
    needs_review: bool = typer.Option(
        False,
        "--needs-review",
        help="Only transactions where needsReview == true (Monarch 'Needs Review' filter).",
    ),
    reviewed: bool = typer.Option(
        False,
        "--reviewed",
        help="Only transactions where needsReview == false (already reviewed).",
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., amount:gte:100, merchant:like:%Amazon%)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """
    List transactions with filtering.

    Review-Status Filter:
        monarch transactions list --needs-review            # only "Needs Review"
        monarch transactions list --reviewed                # only already-reviewed
        (--needs-review and --reviewed are mutually exclusive.)

    Filter Examples:
        monarch transactions list --filter "amount:gte:100"
        monarch transactions list --filter "merchant:like:%Amazon%"
        monarch transactions list --filter "category:Groceries"
        monarch transactions list --filter "is_pending:true"
        monarch transactions list --filter "amount:gte:50,category:Dining"

    Supported operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull

    Other Examples:
        monarch transactions list
        monarch transactions list --days 30
        monarch transactions list --start 2024-01-01 --end 2024-01-31
        monarch transactions list --account ACC_ID --table
    """
    try:
        # --needs-review and --reviewed are mutually exclusive.
        if needs_review and reviewed:
            typer.echo(
                "Error: --needs-review and --reviewed are mutually exclusive.",
                err=True,
            )
            raise typer.Exit(1)

        review_filter: Optional[bool] = None
        if needs_review:
            review_filter = True
        elif reviewed:
            review_filter = False

        # Validate filters early
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)

        # Handle --days shortcut
        if days and not start_date:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            end_date = datetime.now().strftime("%Y-%m-%d")

        # Default to wide date range if not specified (API returns limited results without dates)
        if not start_date:
            start_date = "2000-01-01"
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")

        client = get_client()
        data = client.get_transactions(
            limit=limit,
            start_date=start_date,
            end_date=end_date,
            account_ids=[account] if account else None,
            category_ids=[category] if category else None,
            search=search or "",
            needs_review=review_filter,
        )

        transactions = _extract_transactions(data)

        # Convert Transaction models to dicts for filtering
        transaction_dicts = [t.model_dump() for t in transactions]

        # Apply client-side filters (Monarch API has limited server-side filtering)
        if filter:
            transaction_dicts = apply_filters(transaction_dicts, filter)

        # Apply properties filter
        if properties:
            transaction_dicts = _apply_properties_filter(transaction_dicts, properties)

        if table:
            cols = list(transaction_dicts[0].keys()) if transaction_dicts else ["date", "merchant", "amount", "category", "account_name"]
            print_table(transaction_dicts, cols, [c.replace("_", " ").title() for c in cols])
        else:
            print_json(transaction_dicts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def transactions_get(
    transaction_id: str = typer.Argument(..., help="Transaction ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific transaction."""
    try:
        client = get_client()
        data = client.get_transaction_details(transaction_id)

        if table:
            txn = data.get("getTransaction", data)
            rows = [{"field": k, "value": str(v)[:60]} for k, v in txn.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def transactions_update(
    transaction_id: str = typer.Argument(..., help="Transaction ID to update"),
    merchant: Optional[str] = typer.Option(None, "--merchant", "-m", help="New merchant name"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="New category ID"),
    amount: Optional[float] = typer.Option(None, "--amount", "-a", help="New amount"),
    date: Optional[str] = typer.Option(None, "--date", "-d", help="New date (YYYY-MM-DD)"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="New notes (use '' to clear)"),
    goal: Optional[str] = typer.Option(None, "--goal", "-g", help="Goal ID (use '' to clear)"),
    hide_from_reports: Optional[bool] = typer.Option(None, "--hide-from-reports", help="Hide from reports"),
    needs_review: Optional[bool] = typer.Option(None, "--needs-review", help="Mark as needs review"),
):
    """
    Update a transaction.

    Examples:
        monarch transactions update TXN_ID --merchant "Amazon"
        monarch transactions update TXN_ID --category CAT_ID
        monarch transactions update TXN_ID --amount 50.00 --date 2024-01-15
        monarch transactions update TXN_ID --notes "Reimbursement pending"
        monarch transactions update TXN_ID --notes ""  # Clear notes
        monarch transactions update TXN_ID --hide-from-reports
        monarch transactions update TXN_ID --no-needs-review
    """
    try:
        # Check if any update field was provided
        if all(v is None for v in [merchant, category, amount, date, notes, goal, hide_from_reports, needs_review]):
            typer.echo("Error: At least one update option is required", err=True)
            raise typer.Exit(1)

        client = get_client()
        result = client.update_transaction(
            transaction_id=transaction_id,
            merchant_name=merchant,
            category_id=category,
            amount=amount,
            date=date,
            notes=notes,
            goal_id=goal,
            hide_from_reports=hide_from_reports,
            needs_review=needs_review,
        )

        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("recurring")
def transactions_recurring(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    start_date: Optional[str] = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end", "-e", help="End date (YYYY-MM-DD)"),
):
    """List recurring transactions (unique streams)."""
    try:
        client = get_client()
        data = client.get_recurring_transactions(start_date=start_date, end_date=end_date)

        items = data.get("recurringTransactionItems", [])

        # Extract unique streams from items
        streams_by_id = {}
        for item in items:
            stream = item.get("stream", {})
            stream_id = stream.get("id")
            if stream_id and stream_id not in streams_by_id:
                streams_by_id[stream_id] = {
                    "id": stream_id,
                    "merchant": stream.get("merchant", {}).get("name", "") if stream.get("merchant") else "",
                    "amount": stream.get("amount", 0),
                    "frequency": stream.get("frequency", ""),
                    "is_approximate": stream.get("isApproximate", False),
                }

        recurring = list(streams_by_id.values())

        if table:
            columns = ["id", "merchant", "amount", "frequency"]
            headers = ["ID", "Merchant", "Amount", "Frequency"]
            print_table(recurring, columns, headers)
        else:
            print_json(recurring)

    except Exception as e:
        raise typer.Exit(handle_error(e))
