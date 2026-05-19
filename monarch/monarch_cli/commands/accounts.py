"""Accounts commands for Monarch CLI."""
import typer
from typing import Optional, List

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, handle_error
from ..models import Account
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Manage Monarch Money accounts")

COMMAND_CREDENTIALS = {
    "get": [
        "username_password"
    ],
    "history": [
        "username_password"
    ],
    "holdings": [
        "username_password"
    ],
    "list": [
        "username_password"
    ],
    "sync": [
        "username_password"
    ]
}


def _apply_properties_filter(items: List[dict], properties: str) -> List[dict]:
    """Filter items to include only specified properties."""
    if not properties:
        return items
    props = [p.strip() for p in properties.split(",")]
    return [{k: v for k, v in item.items() if k in props} for item in items]


def _extract_accounts(data: dict) -> list:
    """Extract accounts from API response."""
    accounts = data.get("accounts", [])
    result = []
    for acc in accounts:
        result.append(Account(
            id=str(acc.get("id", "")),
            name=acc.get("displayName", acc.get("name", "")),
            type=acc.get("type", {}).get("name") if isinstance(acc.get("type"), dict) else acc.get("type"),
            subtype=acc.get("subtype", {}).get("name") if isinstance(acc.get("subtype"), dict) else acc.get("subtype"),
            balance=float(acc.get("currentBalance", 0) or 0),
            institution=acc.get("institution", {}).get("name") if acc.get("institution") else None,
            is_hidden=acc.get("isHidden", False),
            is_asset=acc.get("isAsset", True),
            last_updated=acc.get("displayLastUpdatedAt"),
        ))
    return result


@app.command("list")
def accounts_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    show_hidden: bool = typer.Option(False, "--hidden", help="Include hidden accounts"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum accounts to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., type:Checking, balance:gte:1000)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """
    List all accounts.

    Filter Examples:
        monarch accounts list --filter "type:Checking"
        monarch accounts list --filter "balance:gte:1000"
        monarch accounts list --filter "institution:like:%Chase%"

    Other Examples:
        monarch accounts list
        monarch accounts list --table
        monarch accounts list --hidden
    """
    try:
        # Validate filters early
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        data = client.get_accounts()
        accounts = _extract_accounts(data)

        if not show_hidden:
            accounts = [a for a in accounts if not a.is_hidden]

        accounts = accounts[:limit]

        # Convert to dicts for filtering
        account_dicts = [a.model_dump() for a in accounts]

        # Apply client-side filters
        if filter:
            account_dicts = apply_filters(account_dicts, filter)

        # Apply properties filter
        if properties:
            account_dicts = _apply_properties_filter(account_dicts, properties)

        if table:
            cols = list(account_dicts[0].keys()) if account_dicts else ["name", "type", "balance", "institution"]
            print_table(account_dicts, cols, [c.replace("_", " ").title() for c in cols])
        else:
            print_json(account_dicts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def accounts_get(
    account_id: str = typer.Argument(..., help="Account ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific account."""
    try:
        client = get_client()
        data = client.get_accounts()
        accounts = _extract_accounts(data)

        account = next((a for a in accounts if a.id == account_id), None)
        if not account:
            from cli_tools_shared.output import print_error
            print_error(f"Account not found: {account_id}")
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in account.model_dump().items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(account.model_dump())

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("history")
def accounts_history(
    account_id: str = typer.Argument(..., help="Account ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(30, "--limit", "-l", help="Number of history entries"),
):
    """Get balance history for an account."""
    try:
        client = get_client()
        data = client.get_account_history(account_id)

        # Extract history entries
        history = data.get("accountHistory", [])[:limit]

        if table:
            print_table(history, ["date", "balance"], ["Date", "Balance"])
        else:
            print_json(history)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("holdings")
def accounts_holdings(
    account_id: str = typer.Argument(..., help="Account ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get securities holdings for a brokerage account."""
    try:
        client = get_client()
        data = client.get_account_holdings(account_id)

        holdings = data.get("holdings", [])

        if table:
            print_table(holdings, ["name", "ticker", "quantity", "value"],
                       ["Name", "Ticker", "Quantity", "Value"])
        else:
            print_json(holdings)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("sync")
def accounts_sync(
    account_ids: Optional[List[str]] = typer.Argument(None, help="Account IDs to sync (all if empty)"),
    wait: bool = typer.Option(False, "--wait", "-w", help="Wait for sync to complete"),
):
    """Trigger account refresh/sync."""
    try:
        client = get_client()
        result = client.refresh_accounts(account_ids, wait=wait)

        if wait:
            print_success("Account sync completed")
        else:
            print_success("Account sync triggered")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
