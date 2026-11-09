"""Live streaming commands (the WebSocket handshake requires credentials)."""
COMMAND_CREDENTIALS = {
    "watch": ["custom"],
}

import asyncio
import os
import sys
import time
from typing import Optional

import orjson
import typer
from cli_tools_shared.output import command

from ..presets import resolve_series
from ..stream import state_path, stream_market
from ._common import DEMO_OPTION, ENV_OPTION, TABLE_OPTION, finite, open_client

app = typer.Typer(help="Stream live market data over WebSocket", no_args_is_help=True)


def _line(view: dict) -> str:
    """One human-readable status line (table mode)."""
    up, down = view["yes_label"] or "YES", view["no_label"] or "NO"
    return (
        f"{view['ticker']} {view['seconds_left']:7.1f}s  target {view['target_price']}  "
        f"{view['reference_index']} {view['reference_price']} (delta {view['delta']})  "
        f"{up} {view['yes_bid']}/{view['yes_ask']} x{view['yes_bid_size']}/{view['yes_ask_size']}  "
        f"{down} {view['no_bid']}/{view['no_ask']} x{view['no_bid_size']}/{view['no_ask_size']}"
    )


@app.command("watch")
@command
def stream_watch(
    target: str = typer.Argument(..., help="Preset name or series ticker (for example btc15m)"),
    duration: Optional[float] = typer.Option(None, "--duration", min=0.001, help="Stop after this many seconds (default: run until interrupted)"),
    count: Optional[int] = typer.Option(None, "--count", min=1, help="Stop after this many updates"),
    interval: float = typer.Option(0.0, "--interval", min=0.0, help="Print at most one update per this many seconds (state still updates on every message)"),
    table: bool = TABLE_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """Stream the open market of a series as one JSON line per update, rolling to each new market."""
    series, preset = resolve_series(target)
    finite(duration, "--duration")
    finite(interval, "--interval")
    client = open_client(env, demo, auth=True)
    printed = 0
    last_print = 0.0

    def on_update(view: dict) -> bool:
        nonlocal printed, last_print
        now = time.monotonic()
        if interval and view["event"] != "rollover" and now - last_print < interval:
            return False
        last_print = now
        out = (_line(view).encode() if table else orjson.dumps(view)) + b"\n"
        try:
            sys.stdout.buffer.write(out)
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            # The reader (for example `| head`) closed the pipe: stop quietly.
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            return True
        printed += 1
        return count is not None and printed >= count

    path = state_path(client.env, series)
    try:
        asyncio.run(stream_market(client, series, preset, on_update, duration, path))
    finally:
        path.unlink(missing_ok=True)
        client.close()
