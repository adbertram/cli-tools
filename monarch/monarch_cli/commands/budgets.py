"""Budgets commands for Monarch CLI."""
import typer
from typing import Optional, List
from datetime import datetime

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_error, handle_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="Manage Monarch Money budgets")

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


@app.command("list")
def budgets_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum budgets to return"),
    start_date: Optional[str] = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end", "-e", help="End date (YYYY-MM-DD)"),
    month: Optional[str] = typer.Option(None, "--month", "-m", help="Month (YYYY-MM)"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., category:Groceries, budgeted:gte:100)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """
    List budgets.

    Filter Examples:
        monarch budgets list --filter "category:Groceries"
        monarch budgets list --filter "budgeted:gte:100"
        monarch budgets list --filter "remaining:lt:0"

    Other Examples:
        monarch budgets list
        monarch budgets list --month 2024-01
        monarch budgets list --table
    """
    try:
        # Validate filters early
        if filter:
            try:
                validate_filters(filter)
            except FilterValidationError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)

        # Handle --month shortcut or default to current month
        if month and not start_date:
            start_date = f"{month}-01"
            # Calculate end of month
            year, mon = map(int, month.split("-"))
            if mon == 12:
                end_date = f"{year + 1}-01-01"
            else:
                end_date = f"{year}-{mon + 1:02d}-01"
        elif not start_date and not end_date:
            # Default to current month if no dates specified (API requires dates)
            now = datetime.now()
            start_date = f"{now.year}-{now.month:02d}-01"
            if now.month == 12:
                end_date = f"{now.year + 1}-01-01"
            else:
                end_date = f"{now.year}-{now.month + 1:02d}-01"

        client = get_client()
        try:
            data = client.get_budgets(start_date=start_date, end_date=end_date)
        except Exception as api_err:
            # Budgets API can fail if no budgets are configured
            if "Something went wrong" in str(api_err):
                data = {"budgetData": {"budgetItems": []}}
            else:
                raise

        budgets = data.get("budgetData", {}).get("budgetItems", [])[:limit]

        # Normalize to dicts with id field
        rows = []
        for b in budgets:
            cat = b.get("category", {})
            rows.append({
                "id": b.get("id", cat.get("id", "") if cat else ""),
                "category": cat.get("name", "") if cat else "",
                "budgeted": b.get("budgetAmount", 0),
                "actual": b.get("actualAmount", 0),
                "remaining": b.get("remainingAmount", 0),
            })

        # Apply client-side filters
        if filter:
            rows = apply_filters(rows, filter)

        # Apply properties filter
        if properties:
            rows = _apply_properties_filter(rows, properties)

        if table:
            cols = list(rows[0].keys()) if rows else ["id", "category", "budgeted", "actual", "remaining"]
            print_table(rows, cols, [c.title() for c in cols])
        else:
            print_json(rows)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def budgets_get(
    budget_id: str = typer.Argument(..., help="Budget item ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    month: Optional[str] = typer.Option(None, "--month", "-m", help="Month (YYYY-MM)"),
):
    """Get details for a specific budget item."""
    try:
        # Default to current month
        now = datetime.now()
        if month:
            start_date = f"{month}-01"
            year, mon = map(int, month.split("-"))
            end_date = f"{year + 1}-01-01" if mon == 12 else f"{year}-{mon + 1:02d}-01"
        else:
            start_date = f"{now.year}-{now.month:02d}-01"
            end_date = f"{now.year + 1}-01-01" if now.month == 12 else f"{now.year}-{now.month + 1:02d}-01"

        client = get_client()
        data = client.get_budgets(start_date=start_date, end_date=end_date)
        budgets = data.get("budgetData", {}).get("budgetItems", [])

        budget = None
        for b in budgets:
            cat = b.get("category", {})
            bid = b.get("id", cat.get("id", ""))
            if str(bid) == str(budget_id):
                budget = {
                    "id": bid,
                    "category": cat.get("name", "") if cat else "",
                    "budgeted": b.get("budgetAmount", 0),
                    "actual": b.get("actualAmount", 0),
                    "remaining": b.get("remainingAmount", 0),
                }
                break

        if not budget:
            print_error(f"Budget item not found: {budget_id}")
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in budget.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(budget)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
