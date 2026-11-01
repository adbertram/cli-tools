"""Market data commands (public, no credentials)."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "current": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.filter_map import FilterMap
from cli_tools_shared.output import command

from ..presets import resolve_series
from ..stream import market_view, read_state, state_path
from ._common import (
    DEMO_OPTION,
    ENV_OPTION,
    FILTER_OPTION,
    LIMIT_OPTION,
    PROPERTIES_OPTION,
    TABLE_OPTION,
    check_filters,
    finite,
    emit_record,
    emit_rows,
    open_client,
)

app = typer.Typer(help="Read markets and the current open market of a series", no_args_is_help=True)

COLUMNS = ["ticker", "status", "title", "yes_bid_dollars", "yes_ask_dollars", "close_time", "volume_fp"]

# The market `status` field and the API `status` filter use different words for the same states.
API_STATUS = {"initialized": "unopened", "active": "open", "finalized": "settled"}

# Filters whose field means the same thing in the output and the API become API parameters.
# Every other filter runs on the rows after --limit has been applied by the API.
FILTER_MAP = (
    FilterMap()
    .register_api_translator("ticker", lambda op, value: {"tickers": value.replace("|", ",")} if op in ("eq", "in") else {})
    .register_api_translator("event_ticker", lambda op, value: {"event_ticker": value} if op == "eq" else {})
    .register_api_translator("status", lambda op, value: {"status": API_STATUS[value]} if op == "eq" and value in API_STATUS else {})
)


@app.command("list")
@command
def markets_list(
    series: Optional[str] = typer.Option(None, "--series", "-s", help="Preset name or series ticker (for example btc15m or KXBTC15M)"),
    status: Optional[str] = typer.Option(None, "--status", help="API status filter: unopened, open, paused, closed, settled"),
    limit: int = LIMIT_OPTION,
    filter: Optional[List[str]] = FILTER_OPTION,
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """List markets, optionally for one series."""
    check_filters(filter)
    series_ticker = resolve_series(series)[0] if series is not None else None
    with open_client(env, demo) as client:
        api_params = {**FILTER_MAP.to_api_params(filter or []), **({"status": status} if status else {})}
        rows = client.list_markets(series=series_ticker, limit=limit, **api_params)
    emit_rows(rows, filter, table, properties, COLUMNS, "No markets found.")


@app.command("get")
@command
def markets_get(
    ticker: str = typer.Argument(..., help="Market ticker (for example KXBTC15M-26NOV011615-15)"),
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """Get one market by ticker."""
    with open_client(env, demo) as client:
        emit_record(client.get_market(ticker), table, properties)


@app.command("current")
@command
def markets_current(
    target: str = typer.Argument(..., help="Preset name or series ticker (for example btc15m)"),
    max_stream_age: float = typer.Option(5.0, "--max-stream-age", min=0.0, help="Use a running `stream watch` reference price if newer than this many seconds"),
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """Show the open market of a series: target, time left, YES/NO quotes, live reference price when streaming."""
    series, preset = resolve_series(target)
    finite(max_stream_age, "--max-stream-age")
    with open_client(env, demo) as client:
        market = client.current_market(series)
        streamed = read_state(state_path(client.env, series), max_stream_age)
    reference = None
    if streamed and streamed["ticker"] == market["ticker"] and streamed["reference_price"] is not None:
        reference = {"value": streamed["reference_price"], "ts_ms": streamed["reference_ts_ms"]}
    view = market_view(market, reference, preset)
    view["reference_source"] = "stream" if reference else None
    emit_record(view, table, properties)
