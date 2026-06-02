"""Quotes commands for Brickowl CLI."""
COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "submit": ["browser_session"],
}

import typer
from typing import Optional, List

from cli_tools_shared.output import print_error, print_json, print_table, print_success
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit

app = typer.Typer(help="Manage Brick Owl quotes", no_args_is_help=True)


@app.command("list")
def quotes_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of quotes to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List quote requests.

    Examples:
        brickowl quotes list
        brickowl quotes list --table
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        data = browser.list_quotes(filter="outstanding")
        data = apply_filters(data, filter)
        data = apply_properties_filter(data, properties)
        data = apply_limit(data, limit)
        if table:
            print_table(data, ["quote_id", "date", "status", "total"], ["ID", "Date", "Status", "Total"])
        else:
            print_json(data)
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to list quotes: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()


@app.command("get")
def quotes_get(
    quote_id: str = typer.Argument(..., help="The quote ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific quote.

    Examples:
        brickowl quotes get QUOTE_ID
        brickowl quotes get QUOTE_ID --table
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        data = browser.get_quote(quote_id)
        if table:
            rows = [{"field": k, "value": v} for k, v in data.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(data)
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to get quote: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()


@app.command("submit")
def quotes_submit(
    quote_id: str = typer.Argument(..., help="The quote ID to submit shipping amount for"),
    amount: float = typer.Argument(..., help="Shipping amount to quote"),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Note for the buyer"),
):
    """
    Submit a shipping quote for a quote request.

    Examples:
        brickowl quotes submit QUOTE_ID 5.99
        brickowl quotes submit QUOTE_ID 3.50 --note "Ships within 2 business days"
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        result = browser.submit_quote(quote_id, amount, note=note)
        print_json(result)
        print_success(f"Quote {quote_id} submitted successfully.")
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to submit quote: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()
