"""Transactions commands for Kick CLI."""
import typer
from datetime import datetime
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


def parse_date(date_str: str) -> datetime:
    """Parse a date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise typer.BadParameter(f"Invalid date format: {date_str}. Use YYYY-MM-DD format.")

app = typer.Typer(help="Manage Kick transactions")


def extract_field(item: dict, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    parts = field.split(".")
    value = item
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


def format_amount(amount: float) -> str:
    """Format amount as currency string."""
    if amount >= 0:
        return f"${amount:,.2f}"
    return f"-${abs(amount):,.2f}"


@app.command("list")
def transactions_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of transactions to return"),
    page: int = typer.Option(0, "--page", "-p", help="Page number (0-indexed)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    entity_id: Optional[int] = typer.Option(None, "--entity-id", "-e", help="Filter by entity ID"),
    sort_field: str = typer.Option("date", "--sort-field", help="Field to sort by"),
    sort_order: str = typer.Option("DESC", "--sort-order", help="Sort order (ASC or DESC)"),
    date_from: Optional[str] = typer.Option(None, "--from", help="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = typer.Option(None, "--to", help="Filter to date (YYYY-MM-DD)"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (pending, completed)"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Filter by account name (case-insensitive partial match)"),
    account_id: Optional[int] = typer.Option(None, "--account-id", help="Filter by financial account ID (exact match)"),
):
    """
    List transactions.

    Client-Side Filtering:
        --from/--to: Filter by date range (YYYY-MM-DD format)
        --status: Filter by transaction status
        --account: Filter by account name (case-insensitive partial match)
        --account-id: Filter by financial account ID (exact match)

    Examples:
        kick transactions list
        kick transactions list --table
        kick transactions list --limit 50
        kick transactions list --entity-id 16044
        kick transactions list --status pending --table
        kick transactions list --status completed
        kick transactions list --sort-field date --sort-order ASC
        kick transactions list --from 2025-12-01 --to 2025-12-31 --table
        kick transactions list --from 2025-01-01 --table
        kick transactions list --account "Business Checking" --table
        kick transactions list --account-id 17334 --table
    """
    try:
        client = get_client()

        # Parse date filters if provided
        from_date = parse_date(date_from) if date_from else None
        to_date = parse_date(date_to) if date_to else None

        # Build entity IDs filter
        entity_ids = [entity_id] if entity_id else None

        # Build API filters (exclude status/account - filtered client-side)
        api_filters = list(filter) if filter else []

        # Prepare account filter for case-insensitive matching
        account_search = account.lower() if account else None

        # Client-side filtering required for date range, status, or account
        if from_date or to_date or status or account_search or account_id:
            transactions = []
            current_page = 0

            while len(transactions) < limit:
                result = client.list_transactions(
                    page=current_page,
                    limit=100,
                    sort_field=sort_field,
                    sort_order=sort_order,
                    entity_ids=entity_ids,
                    filters=api_filters or None,
                )

                batch = result["data"]
                if not batch:
                    break

                for txn in batch:
                    # Status filter (client-side)
                    if status and txn.get("status") != status:
                        continue

                    # Account filter (client-side)
                    fin_account = txn.get("financialAccount") or {}
                    if account_id and fin_account.get("id") != account_id:
                        continue
                    if account_search:
                        acct_name = (fin_account.get("name") or "").lower()
                        if account_search not in acct_name:
                            continue

                    # Date filtering (client-side)
                    if from_date or to_date:
                        txn_date_str = txn.get("date", "")[:10] if txn.get("date") else None
                        if not txn_date_str:
                            continue

                        txn_date = datetime.strptime(txn_date_str, "%Y-%m-%d")

                        if from_date and txn_date < from_date:
                            if sort_order.upper() == "DESC":
                                break
                            continue
                        if to_date and txn_date > to_date:
                            if sort_order.upper() == "ASC":
                                break
                            continue

                    transactions.append(txn)
                    if len(transactions) >= limit:
                        break

                # Check if we've exhausted all pages
                if current_page >= result.get("pageCount", 1) - 1:
                    break

                current_page += 1

            total = len(transactions)
            page_count = 1
        else:
            # No client-side filtering - use standard pagination
            result = client.list_transactions(
                page=page,
                limit=limit,
                sort_field=sort_field,
                sort_order=sort_order,
                entity_ids=entity_ids,
                filters=api_filters or None,
            )

            transactions = result["data"]
            total = result.get("total", len(transactions))
            page_count = result.get("pageCount", 1)

        if table:
            table_data = []
            for txn in transactions:
                table_data.append({
                    "id": txn.get("id", ""),
                    "date": txn.get("date", "")[:10] if txn.get("date") else "",
                    "description": (txn.get("displayDescription") or txn.get("bankDescription") or "")[:40],
                    "category": txn.get("category", {}).get("label", "") if txn.get("category") else "",
                    "amount": format_amount(txn.get("amount", 0)),
                    "status": txn.get("status", ""),
                    "client": txn.get("counterparty", {}).get("name", "") if txn.get("counterparty") else "",
                    "account": txn.get("financialAccount", {}).get("name", "") if txn.get("financialAccount") else "",
                })

            print_table(
                table_data,
                ["id", "date", "description", "category", "amount", "status", "client", "account"],
                ["ID", "Date", "Description", "Category", "Amount", "Status", "Client", "Account"],
            )
            from cli_tools_shared.output import print_info
            if from_date or to_date or status or account_search or account_id:
                filters_desc = []
                if status:
                    filters_desc.append(f"status={status}")
                if account_search:
                    filters_desc.append(f"account~{account}")
                if account_id:
                    filters_desc.append(f"account_id={account_id}")
                if from_date or to_date:
                    filters_desc.append(f"date: {date_from or 'start'} to {date_to or 'now'}")
                print_info(f"Showing {len(transactions)} transactions ({', '.join(filters_desc)})")
            else:
                print_info(f"Showing {len(transactions)} of {total} transactions (page {page + 1} of {page_count})")
        else:
            print_json({
                "data": transactions,
                "total": total,
                "pageCount": page_count,
                "page": page,
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def transactions_search(
    query: str = typer.Argument(..., help="Search text to find in transaction descriptions"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of matching transactions to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    entity_id: Optional[int] = typer.Option(None, "--entity-id", "-e", help="Filter by entity ID"),
    case_sensitive: bool = typer.Option(False, "--case-sensitive", "-C", help="Case-sensitive search"),
    account: Optional[str] = typer.Option(None, "--account", "-a", help="Filter by account name (case-insensitive partial match)"),
    account_id: Optional[int] = typer.Option(None, "--account-id", help="Filter by financial account ID (exact match)"),
):
    """
    Search transactions by text in description fields.

    Searches through displayDescription, bankDescription, category label,
    and counterparty name fields.

    Examples:
        kick transactions search "Cursor"
        kick transactions search "amazon" --table
        kick transactions search "stripe" --limit 50
        kick transactions search "payment" --filter "direction:out"
        kick transactions search "AWS" --case-sensitive
        kick transactions search "cursor" --account "Business Checking"
        kick transactions search "cursor" --account-id 17334
    """
    try:
        client = get_client()
        entity_ids = [entity_id] if entity_id else None

        matches = []
        page = 0

        # Prepare search query
        search_query = query if case_sensitive else query.lower()

        # Prepare account filter for case-insensitive matching
        account_search = account.lower() if account else None

        while len(matches) < limit:
            result = client.list_transactions(
                page=page,
                limit=100,
                entity_ids=entity_ids,
                filters=filter,
            )

            transactions = result["data"]
            if not transactions:
                break

            # Filter transactions by search text and account
            for txn in transactions:
                if len(matches) >= limit:
                    break

                # Account filter (client-side)
                fin_account = txn.get("financialAccount") or {}
                if account_id and fin_account.get("id") != account_id:
                    continue
                if account_search:
                    acct_name = (fin_account.get("name") or "").lower()
                    if account_search not in acct_name:
                        continue

                # Build searchable text from multiple fields
                searchable_fields = [
                    txn.get("displayDescription") or "",
                    txn.get("bankDescription") or "",
                    txn.get("category", {}).get("label", "") if txn.get("category") else "",
                    txn.get("counterparty", {}).get("name", "") if txn.get("counterparty") else "",
                    txn.get("memo") or "",
                ]
                searchable_text = " ".join(searchable_fields)

                if not case_sensitive:
                    searchable_text = searchable_text.lower()

                if search_query in searchable_text:
                    matches.append(txn)

            # Check if we've exhausted all pages
            if page >= result.get("pageCount", 1) - 1:
                break

            page += 1

        if table:
            table_data = []
            for txn in matches:
                table_data.append({
                    "id": txn.get("id", ""),
                    "date": txn.get("date", "")[:10] if txn.get("date") else "",
                    "description": (txn.get("displayDescription") or txn.get("bankDescription") or "")[:50],
                    "category": txn.get("category", {}).get("label", "") if txn.get("category") else "",
                    "amount": format_amount(txn.get("amount", 0)),
                    "status": txn.get("status", ""),
                    "client": txn.get("counterparty", {}).get("name", "") if txn.get("counterparty") else "",
                    "account": txn.get("financialAccount", {}).get("name", "") if txn.get("financialAccount") else "",
                })

            print_table(
                table_data,
                ["id", "date", "description", "category", "amount", "status", "client", "account"],
                ["ID", "Date", "Description", "Category", "Amount", "Status", "Client", "Account"],
            )
            from cli_tools_shared.output import print_info
            print_info(f"Found {len(matches)} transactions matching '{query}' (searched {page + 1} pages)")
        else:
            print_json({
                "query": query,
                "matches": len(matches),
                "pagesSearched": page + 1,
                "data": matches,
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def transactions_get(
    transaction_id: int = typer.Argument(..., help="The transaction ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific transaction.

    Examples:
        kick transactions get 12345
        kick transactions get 12345 --table
    """
    try:
        client = get_client()
        txn = client.get_transaction(transaction_id)

        if table:
            summary = [{
                "id": txn.get("id", ""),
                "date": txn.get("date", "")[:10] if txn.get("date") else "",
                "description": txn.get("displayDescription") or txn.get("bankDescription") or "",
                "category": txn.get("category", {}).get("label", "") if txn.get("category") else "",
                "amount": format_amount(txn.get("amount", 0)),
                "status": txn.get("status", ""),
                "type": txn.get("type", ""),
                "entity": txn.get("entity", {}).get("name", "") if txn.get("entity") else "",
                "client": txn.get("counterparty", {}).get("name", "") if txn.get("counterparty") else "",
            }]

            print_table(
                summary,
                ["id", "date", "description", "category", "amount", "status", "type", "entity", "client"],
                ["ID", "Date", "Description", "Category", "Amount", "Status", "Type", "Entity", "Client"],
            )
        else:
            print_json(txn)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def transactions_update(
    transaction_id: int = typer.Argument(..., help="The transaction ID to update"),
    category_id: Optional[str] = typer.Option(None, "--category-id", "-c", help="Category UUID to assign"),
    counterparty_id: Optional[str] = typer.Option(None, "--counterparty-id", "-p", help="Counterparty UUID to assign"),
    account_id: Optional[str] = typer.Option(None, "--account-id", "-a", help="Account UUID to assign"),
    memo: Optional[str] = typer.Option(None, "--memo", "-m", help="Note/memo text to add"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Update a transaction.

    At least one update option must be provided.

    Examples:
        kick transactions update 12345 --category-id 01956661-459c-74c3-94d8-b52a43fbae24
        kick transactions update 12345 --counterparty-id 019129dd-96c6-7747-ba23-3c1b5b2066e6
        kick transactions update 12345 --account-id 019493a3-193e-790f-9f0c-c8c0fc21383b
        kick transactions update 12345 --memo "Payment for invoice #123"
        kick transactions update 12345 -c 01956661-459c-74c3-94d8-b52a43fbae24 -m "Note" --table
    """
    # Validate that at least one update field is provided
    if category_id is None and counterparty_id is None and account_id is None and memo is None:
        typer.echo("Error: At least one update option must be provided.", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        txn = client.update_transaction(
            transaction_id=transaction_id,
            category_id=category_id,
            counterparty_id=counterparty_id,
            account_id=account_id,
            memo=memo,
        )

        if table:
            summary = [{
                "id": txn.get("id", ""),
                "date": txn.get("date", "")[:10] if txn.get("date") else "",
                "description": txn.get("displayDescription") or txn.get("bankDescription") or "",
                "category": txn.get("category", {}).get("label", "") if txn.get("category") else "",
                "amount": format_amount(txn.get("amount", 0)),
                "status": txn.get("status", ""),
                "type": txn.get("type", ""),
                "entity": txn.get("entity", {}).get("name", "") if txn.get("entity") else "",
            }]

            print_table(
                summary,
                ["id", "date", "description", "category", "amount", "status", "type", "entity"],
                ["ID", "Date", "Description", "Category", "Amount", "Status", "Type", "Entity"],
            )
            from cli_tools_shared.output import print_info
            print_info(f"Transaction {transaction_id} updated successfully")
        else:
            print_json(txn)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "search": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}
