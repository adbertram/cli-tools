"""Market presets: friendly names mapped to Kalshi series tickers."""
COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
}

from typing import List, Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command

from ..presets import load_presets
from ._common import FILTER_OPTION, LIMIT_OPTION, PROPERTIES_OPTION, TABLE_OPTION, check_filters, emit_record, emit_rows

app = typer.Typer(help="Market presets (name to series ticker)", no_args_is_help=True)

COLUMNS = ["name", "series_ticker", "reference_index", "description"]


@app.command("list")
@command
def presets_list(
    limit: int = LIMIT_OPTION,
    filter: Optional[List[str]] = FILTER_OPTION,
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
):
    """List market presets from presets.json."""
    check_filters(filter)
    rows = [{"name": name, **preset} for name, preset in load_presets().items()]
    emit_rows(rows[:limit], filter, table, properties, COLUMNS, "No presets found.")


@app.command("get")
@command
def presets_get(
    name: str = typer.Argument(..., help="Preset name (for example btc15m)"),
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
):
    """Get one market preset."""
    presets = load_presets()
    if name.lower() not in presets:
        raise ClientError(f"Unknown preset '{name}'. Valid presets: {', '.join(presets)}")
    emit_record({"name": name.lower(), **presets[name.lower()]}, table, properties)
