"""Futures market data commands."""
from __future__ import annotations
import typer
from cli_tools_shared.output import command
from ..client import CATEGORY_US_FUTURES, WebullClient, WebullError, safe_error
from ..presentation import guard, render
import json
import math
import signal
import threading

app = typer.Typer(help="Read futures market data", no_args_is_help=True)
COMMAND_CREDENTIALS = {name: ["custom"] for name in ("bars", "stream")}

@app.command("bars")
@command
@guard
def futures_bars(symbol: str, category: str = typer.Option(CATEGORY_US_FUTURES, "--category", help="Webull market category"),
                 timespan: str = typer.Option("M1", "--timespan", help="Webull bar timespan"),
                 count: int = typer.Option(200, "--count", min=1, max=1200, help="Number of bars per API request"),
                 table: bool = typer.Option(False, "--table", "-t", help="Display as table")):
    """Get full futures history bar responses."""
    render(WebullClient().bars(symbol, category, timespan, count), table=table)


@app.command("stream")
@command
def futures_stream(symbol: str, category: str = typer.Option(CATEGORY_US_FUTURES, "--category", help="Webull market category"),
                   reconnect_attempts: int = typer.Option(3, "--reconnect-attempts", min=0, help="SDK reconnect attempts"),
                   reconnect_delay_milliseconds: int = typer.Option(1000, "--reconnect-delay-milliseconds", min=0, help="Reconnect delay"),
                   mqtt_port: int = typer.Option(8883, "--mqtt-port", min=1, max=65535, help="MQTT TLS port"),
                   socket_loop_seconds: float = typer.Option(1, "--socket-loop-seconds", min=0.001, help="MQTT socket loop timeout"),
                   close_grace_seconds: float = typer.Option(2, "--close-grace-seconds", min=0, help="Parent close grace budget")):
    """Emit JSONL tick, disconnect and error events until interrupted."""
    output_lock = threading.Lock()
    error_emitted = False
    def emit(event):
        nonlocal error_emitted
        with output_lock:
            if error_emitted:
                return
            print(json.dumps(event, separators=(",", ":"), allow_nan=False), flush=True)
            error_emitted = event.get("event") == "error"
    def stop(signum, frame):
        raise KeyboardInterrupt
    previous = None
    try:
        if not math.isfinite(socket_loop_seconds) or socket_loop_seconds <= 0 or not math.isfinite(close_grace_seconds) or close_grace_seconds < 0:
            raise WebullError("validation", "Stream socket-loop-seconds must be finite and positive; close-grace-seconds must be finite and nonnegative.")
        previous = signal.signal(signal.SIGTERM, stop)
        WebullClient().stream(symbol, emit, category=category, reconnect_attempts=reconnect_attempts,
                              reconnect_delay_milliseconds=reconnect_delay_milliseconds, mqtt_port=mqtt_port,
                              socket_loop_seconds=socket_loop_seconds, close_grace_seconds=close_grace_seconds)
    except KeyboardInterrupt:
        return
    except Exception as exc:
        emit({"event": "error", "error": safe_error(exc).as_dict()["error"]})
        raise typer.Exit(1) from None
    finally:
        if previous is not None:
            try:
                signal.signal(signal.SIGTERM, previous)
            except Exception as exc:
                emit({"event": "error", "error": safe_error(exc).as_dict()["error"]})
                raise typer.Exit(1) from None


