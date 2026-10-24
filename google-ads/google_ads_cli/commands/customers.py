"""Discover accessible Ads customer accounts."""
COMMAND_CREDENTIALS = {"list": ["oauth_authorization_code"], "get": ["oauth_authorization_code"]}

from typing import Optional, List
import typer
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.filters import apply_filters, apply_properties_filter, validate_filters
from cli_tools_shared.output import command, print_json, print_table
from ..client import get_client

app = typer.Typer(help='Discover accessible Ads customer accounts.', no_args_is_help=True)
logger = get_activity_logger("google-ads")


def emit(data, table=False, properties=None):
    if properties:
        data = apply_properties_filter(data if isinstance(data, list) else [data], properties)
    if table:
        print_table(data, max_columns=0)
    else:
        print_json(data)


@app.command("list")
@command
def list_customers(limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum accessible customer names; API has no limit parameter"),
                   filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Local field:op:value filter (resource_name); API has no filter parameter"),
                   table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
                   properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields")):
    """List directly accessible customer resource names; manager descendants require GAQL customer_client."""
    validate_filters(filter or [])
    result = get_client().call("CustomerService", "list_accessible_customers", {})
    rows = [{"resource_name": name} for name in result.get("resource_names", [])]
    if filter:
        rows = apply_filters(rows, filter)
    emit(rows[:limit], table, properties)


@app.command("get")
@command
def get_customer(customer_id: str = typer.Argument(..., help="Customer ID digits or customer resource name"),
                 table: bool = typer.Option(False, "--table", "-t", help="Display full response as table")):
    """Get customer identity, status, currency and timezone through GAQL."""
    account = customer_id.removeprefix("customers/").replace("-", "")
    print_result = get_client().call("GoogleAdsService", "search", {
        "customer_id": account,
        "query": "SELECT customer.id, customer.resource_name, customer.descriptive_name, customer.currency_code, customer.time_zone, customer.status, customer.manager, customer.test_account FROM customer LIMIT 1"})
    emit(print_result, table)


