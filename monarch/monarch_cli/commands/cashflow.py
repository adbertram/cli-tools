"""Cashflow commands for Monarch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_error, handle_error
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError

app = typer.Typer(help="View cashflow data")

COMMAND_CREDENTIALS = {
    "get": [
        "username_password"
    ],
    "list": [
        "username_password"
    ],
    "summary": [
        "username_password"
    ]
}


def _apply_properties_filter(items: List[dict], properties: str) -> List[dict]:
    """Filter items to include only specified properties."""
    if not properties:
        return items
    props = [p.strip() for p in properties.split(",")]
    return [{k: v for k, v in item.items() if k in props} for item in items]


@app.command("summary")
def cashflow_summary(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get cashflow summary (income, expenses, savings)."""
    try:
        client = get_client()
        data = client.get_cashflow_summary()

        summary = data.get("summary", data)

        if table:
            rows = [
                {"metric": "Income", "value": f"${summary.get('sumIncome', 0):,.2f}"},
                {"metric": "Expenses", "value": f"${summary.get('sumExpense', 0):,.2f}"},
                {"metric": "Savings", "value": f"${summary.get('savings', 0):,.2f}"},
            ]
            if summary.get("savingsRate") is not None:
                rows.append({"metric": "Savings Rate", "value": f"{summary['savingsRate']:.1f}%"})
            print_table(rows, ["metric", "value"], ["Metric", "Value"])
        else:
            print_json(summary)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("list")
def cashflow_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    start_date: Optional[str] = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end", "-e", help="End date (YYYY-MM-DD)"),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., group:Income, sum:gte:1000)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated fields to include",
    ),
):
    """
    Get detailed cashflow by period.

    Filter Examples:
        monarch cashflow list --filter "group:Income"
        monarch cashflow list --filter "sum:gte:1000"
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
        data = client.get_cashflow(limit=limit, start_date=start_date, end_date=end_date)

        cashflow = data.get("byCategoryGroup", [])[:limit]

        # Normalize to dicts with id field
        rows = []
        for group in cashflow:
            cat_group = group.get("categoryGroup", {})
            rows.append({
                "id": cat_group.get("id", ""),
                "group": cat_group.get("name", ""),
                "sum": group.get("sum", 0),
            })

        # Apply client-side filters
        if filter:
            rows = apply_filters(rows, filter)

        # Apply properties filter
        if properties:
            rows = _apply_properties_filter(rows, properties)

        if table:
            cols = list(rows[0].keys()) if rows else ["id", "group", "sum"]
            print_table(rows, cols, [c.title() for c in cols])
        else:
            print_json(rows)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def cashflow_get(
    group_id: str = typer.Argument(..., help="Category group ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    start_date: Optional[str] = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, "--end", "-e", help="End date (YYYY-MM-DD)"),
):
    """Get cashflow details for a specific category group."""
    try:
        client = get_client()
        data = client.get_cashflow(limit=100, start_date=start_date, end_date=end_date)

        cashflow = data.get("byCategoryGroup", [])
        item = None
        for group in cashflow:
            cat_group = group.get("categoryGroup", {})
            if str(cat_group.get("id", "")) == str(group_id):
                item = {
                    "id": cat_group.get("id", ""),
                    "group": cat_group.get("name", ""),
                    "sum": group.get("sum", 0),
                }
                break

        if not item:
            print_error(f"Category group not found in cashflow: {group_id}")
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in item.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
