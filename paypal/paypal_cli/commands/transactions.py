"""Transaction search commands for PayPal CLI."""

from typing import List, Optional

import typer

from cli_tools_shared.filters import FilterValidationError, apply_properties_filter
from cli_tools_shared.output import command, print_json, print_table

from ..client import MAX_TRANSACTION_PAGE_SIZE, get_api_client

COMMAND_CREDENTIALS = {
    "get": ["oauth"],
    "list": ["oauth"],
}

app = typer.Typer(help="Manage PayPal transaction reporting")

_DEFAULT_TABLE_PROPERTIES = [
    "transaction_info.transaction_id",
    "transaction_info.transaction_initiation_date",
    "transaction_info.transaction_status",
    "transaction_info.transaction_amount.value",
    "transaction_info.transaction_amount.currency_code",
]


def _property_list(properties: Optional[str]) -> List[str]:
    if properties:
        return [prop.strip() for prop in properties.split(",") if prop.strip()]
    return _DEFAULT_TABLE_PROPERTIES


def _headers_for(properties: List[str]) -> List[str]:
    return [prop.replace("_", " ").replace(".", " ").title() for prop in properties]


def _print_transaction_table(transactions: List[dict], properties: Optional[str]) -> None:
    table_properties = _property_list(properties)
    rows = transactions if properties else apply_properties_filter(transactions, ",".join(table_properties))
    print_table(rows, table_properties, _headers_for(table_properties), max_columns=0)


@app.command("list")
@command
def transactions_list(
    start_date: str = typer.Option(
        ...,
        "--start-date",
        help=(
            "Start of the transaction range. YYYY-MM-DD becomes 00:00:00Z. "
            "Naive datetimes are interpreted as UTC."
        ),
    ),
    end_date: str = typer.Option(
        ...,
        "--end-date",
        help=(
            "End of the transaction range. YYYY-MM-DD becomes 23:59:59Z. "
            "Naive datetimes are interpreted as UTC."
        ),
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum number of transactions to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help=(
            "Client-side filter: field:op:value. Supports nested fields such as "
            "transaction_info.transaction_status:eq:S"
        ),
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
    page_size: int = typer.Option(
        100,
        "--page-size",
        min=1,
        max=MAX_TRANSACTION_PAGE_SIZE,
        help=f"Number of records to request per PayPal page (max {MAX_TRANSACTION_PAGE_SIZE})",
    ),
    all_records: bool = typer.Option(
        False,
        "--all-records",
        help="Include non-balance-affecting records by sending balance_affecting_records_only=N",
    ),
):
    """List transactions from the PayPal Transaction Search API."""
    try:
        client = get_api_client()
        transactions = client.list_transactions(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            filters=filter,
            page_size=page_size,
            fields="all",
            balance_affecting_records_only="N" if all_records else "Y",
        )
    except FilterValidationError as exc:
        raise RuntimeError(str(exc)) from exc

    if properties:
        transactions = apply_properties_filter(transactions, properties)

    if table:
        _print_transaction_table(transactions, properties)
        return

    print_json(transactions)


@app.command("get")
@command
def transactions_get(
    transaction_id: str = typer.Argument(..., help="PayPal transaction ID"),
    start_date: str = typer.Option(
        ...,
        "--start-date",
        help=(
            "Start of the search range. YYYY-MM-DD becomes 00:00:00Z. "
            "Naive datetimes are interpreted as UTC."
        ),
    ),
    end_date: str = typer.Option(
        ...,
        "--end-date",
        help=(
            "End of the search range. YYYY-MM-DD becomes 23:59:59Z. "
            "Naive datetimes are interpreted as UTC."
        ),
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of transaction detail fields to include in output",
    ),
    page_size: int = typer.Option(
        100,
        "--page-size",
        min=1,
        max=MAX_TRANSACTION_PAGE_SIZE,
        help=f"Number of records to request per PayPal page (max {MAX_TRANSACTION_PAGE_SIZE})",
    ),
    all_records: bool = typer.Option(
        False,
        "--all-records",
        help="Include non-balance-affecting records by sending balance_affecting_records_only=N",
    ),
):
    """Get transaction-search matches for a PayPal transaction ID."""
    client = get_api_client()
    result = client.get_transaction(
        transaction_id=transaction_id,
        start_date=start_date,
        end_date=end_date,
        page_size=page_size,
        fields="all",
        balance_affecting_records_only="N" if all_records else "Y",
    )

    details = result.get("transaction_details", [])
    if properties:
        details = apply_properties_filter(details, properties)
        result = {**result, "transaction_details": details}

    if table:
        _print_transaction_table(details, properties)
        return

    print_json(result)
