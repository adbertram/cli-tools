"""Refill commands for CVS CLI."""
COMMAND_CREDENTIALS = {
    "check": [
        "browser_session"
    ]
}

import typer
from typing import List, Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter


app = typer.Typer(help="Check refill eligibility", no_args_is_help=True)


DEFAULT_TABLE_COLS = [
    "id",
    "drugName",
    "isRefillable",
    "isRenewEligible",
    "numberOfRefillsRemaining",
    "nextFillDate",
    "patientFirstName",
]
DEFAULT_TABLE_HEADERS = [
    "Rx ID",
    "Drug",
    "Refillable",
    "Renewable",
    "Refills Left",
    "Next Fill",
    "Patient",
]


@app.command("check")
def refills_check(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """Check which prescriptions are eligible for refill or renewal."""
    try:
        client = get_client()
        items = client.check_refills()
        items = [i.model_dump() for i in items]
        if filter:
            items = apply_filters(items, filter)
        items = apply_limit(items, limit)
        if properties:
            items = apply_properties_filter(items, properties)
        if table:
            if properties:
                cols = [c.strip() for c in properties.split(",")]
                headers = cols
            else:
                cols = DEFAULT_TABLE_COLS
                headers = DEFAULT_TABLE_HEADERS
            print_table(items, cols, headers)
        else:
            print_json(items)
    except Exception as e:
        raise typer.Exit(handle_error(e))
