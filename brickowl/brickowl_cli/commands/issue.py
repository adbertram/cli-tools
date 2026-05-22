"""Issue report commands for Brickowl CLI.

Browser automation for listing and resolving issue reports
(disputes filed by customers) on Brick Owl.
"""
COMMAND_CREDENTIALS = {
    "list": ["browser_session"],
    "get": ["browser_session"],
    "resolve": ["browser_session"],
}

import typer
from typing import Optional, List

from cli_tools_shared.output import print_error, print_json, print_table, print_success
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit

app = typer.Typer(help="Manage Brick Owl issue reports", no_args_is_help=True)


@app.command("list")
def issue_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of reports to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List issue reports (browser-based).

    Shows open issue reports (disputes) filed by customers.

    Examples:
        brickowl issue list
        brickowl issue list --table
        brickowl issue list --filter "status:eq:Open"
        brickowl issue list --properties "order_id,details,status"
        brickowl issue list --limit 5
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        data = browser.list_issue_reports()
        data = apply_filters(data, filter)
        data = apply_properties_filter(data, properties)
        data = apply_limit(data, limit)
        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(data, fields, fields)
            else:
                print_table(
                    data,
                    ["order_id", "date", "issue_type", "details", "status"],
                    ["Order ID", "Date", "Issue Type", "Details", "Status"],
                )
        else:
            print_json(data)
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to list issue reports: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()


@app.command("get")
def issue_get(
    order_id: str = typer.Argument(..., help="The order ID of the issue report"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one issue report by order ID."""
    from ..browser import get_browser

    browser = get_browser()
    try:
        data = browser.list_issue_reports()
        matches = [item for item in data if str(item.get("order_id")) == order_id]
        if not matches:
            print_error(f"Issue report not found for order {order_id}")
            raise typer.Exit(1)
        item = apply_properties_filter([matches[0]], properties)[0]
        if table:
            fields = [f.strip() for f in properties.split(",")] if properties else list(item.keys())
            print_table([item], fields, fields)
        else:
            print_json(item)
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to get issue report: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()


@app.command("resolve")
def issue_resolve(
    order_id: str = typer.Argument(..., help="The order ID of the issue report to resolve"),
):
    """
    Resolve an issue report for a specific order (browser-based).

    Finds the issue report matching the given order ID and clicks
    the resolve action.

    Examples:
        brickowl issue resolve 12345678
    """
    from ..browser import get_browser

    browser = get_browser()
    try:
        result = browser.resolve_issue_report(order_id)
        print_json(result)
        if result.get("success"):
            print_success(result.get("message", f"Issue report for order {order_id} resolved"))
    except RuntimeError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Failed to resolve issue report: {e}")
        raise typer.Exit(1)
    finally:
        browser.close()
