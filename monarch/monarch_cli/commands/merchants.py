"""Merchants commands for Monarch CLI."""
import typer
from typing import Optional, List
from datetime import datetime

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Manage merchants")

COMMAND_CREDENTIALS = {
    "get": [
        "username_password"
    ],
    "list": [
        "username_password"
    ]
}


def _apply_properties_filter(items: List[dict], properties: str) -> List[dict]:
    """Filter items to include only specified properties."""
    if not properties:
        return items
    props = [p.strip() for p in properties.split(",")]
    return [{k: v for k, v in item.items() if k in props} for item in items]


def _extract_merchants(data: dict) -> list:
    """Extract merchants from cashflow byMerchant response."""
    by_merchant = data.get("byMerchant", [])
    merchants = []
    for item in by_merchant:
        group_by = item.get("groupBy", {})
        merchant = group_by.get("merchant", {})

        if merchant and merchant.get("id"):
            merchants.append({
                "id": merchant.get("id", ""),
                "name": merchant.get("name", ""),
                "logoUrl": merchant.get("logoUrl"),
            })
    return merchants


@app.command("list")
def merchants_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(10000, "--limit", "-l", help="Maximum merchants to return"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%amazon%)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """
    List all merchants available for transaction assignment.

    Merchants are extracted from cashflow data grouped by merchant,
    querying the maximum date range to capture all merchants.

    Filter Examples:
        monarch merchants list --filter "name:ilike:%amazon%"
        monarch merchants list --filter "sumExpense:lt:-100"
    """
    try:
        # Validate filters early
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)

        # Query with maximum date range to get all merchants
        start_date = "2000-01-01"
        end_date = datetime.now().strftime("%Y-%m-%d")

        client = get_client()
        data = client.get_merchants(start_date=start_date, end_date=end_date)

        merchants = _extract_merchants(data)
        # Sort by name ascending
        merchants = sorted(merchants, key=lambda m: (m.get("name") or "").lower())
        merchants = merchants[:limit]

        # Apply client-side filters
        if filter:
            merchants = apply_filters(merchants, filter)

        # Apply properties filter
        if properties:
            merchants = _apply_properties_filter(merchants, properties)

        if table:
            cols = ["id", "name"]
            headers = ["ID", "Name"]
            print_table(merchants, cols, headers)
        else:
            print_json(merchants)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def merchants_get(
    merchant_id: str = typer.Argument(..., help="Merchant ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific merchant.

    Examples:
        monarch merchants get 12345678
    """
    try:
        # Query with maximum date range to find the merchant
        start_date = "2000-01-01"
        end_date = datetime.now().strftime("%Y-%m-%d")

        client = get_client()
        data = client.get_merchants(start_date=start_date, end_date=end_date)

        merchants = _extract_merchants(data)

        # Find the merchant by ID
        merchant = None
        for m in merchants:
            if str(m.get("id")) == str(merchant_id):
                merchant = m
                break

        if not merchant:
            typer.echo(f"Error: Merchant with ID '{merchant_id}' not found", err=True)
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in merchant.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(merchant)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
