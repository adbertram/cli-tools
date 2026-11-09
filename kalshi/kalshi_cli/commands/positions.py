"""Market positions."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command

from ..client import identifier

from ._common import (
    DEMO_OPTION,
    ENV_OPTION,
    FILTER_OPTION,
    LIMIT_OPTION,
    PROPERTIES_OPTION,
    TABLE_OPTION,
    check_filters,
    emit_record,
    emit_rows,
    open_client,
)

app = typer.Typer(help="List and inspect positions", no_args_is_help=True)

COLUMNS = ["ticker", "position_fp", "market_exposure_dollars", "realized_pnl_dollars", "fees_paid_dollars", "last_updated_ts"]


@app.command("list")
@command
def positions_list(
    settlement_status: str = typer.Option("unsettled", "--settlement-status", help="unsettled, settled or all"),
    limit: int = LIMIT_OPTION,
    filter: Optional[List[str]] = FILTER_OPTION,
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """List market positions (position_fp: positive = YES contracts, negative = NO contracts)."""
    check_filters(filter)
    with open_client(env, demo, auth=True) as client:
        rows = client.list_positions(limit=limit, settlement_status=settlement_status)
    emit_rows(rows, filter, table, properties, COLUMNS, "No positions found.")


@app.command("get")
@command
def positions_get(
    ticker: str = typer.Argument(..., help="Market ticker"),
    settlement_status: str = typer.Option("unsettled", "--settlement-status", help="unsettled, settled or all"),
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """Get the position in one market."""
    with open_client(env, demo, auth=True) as client:
        rows = client.list_positions(limit=1, ticker=identifier(ticker, "ticker"), settlement_status=settlement_status)
    if not rows:
        raise ClientError(f"No {settlement_status} position in market {ticker}.")
    emit_record(rows[0], table, properties)
