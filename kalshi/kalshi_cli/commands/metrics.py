"""Latency measurements for the REST path, signing and (demo only) order round trips."""
COMMAND_CREDENTIALS = {
    "get": ["no_auth"],
}

import statistics
import time
from typing import Optional

import typer
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import command, print_json

from ..client import KalshiClient, build_order_body, resolve_env
from ..presets import resolve_series
from ..signing import Signer
from ._common import DEMO_OPTION, ENV_OPTION, PROPERTIES_OPTION, TABLE_OPTION, emit_record, open_client

app = typer.Typer(help="Measure request latency", no_args_is_help=True)

SIGN_ITERATIONS = 1000
SAMPLE_SPACING_SECONDS = 0.25  # stays under the exchange's burst rate limit, which would otherwise answer 429


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _sign_microseconds() -> float:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    pem = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    signer = Signer("bench", pem)
    start = time.perf_counter()
    for _ in range(SIGN_ITERATIONS):
        signer.headers("GET", "/trade-api/v2/portfolio/balance")
    return round((time.perf_counter() - start) / SIGN_ITERATIONS * 1_000_000, 1)


def _order_round_trip(client: KalshiClient, ticker: str) -> dict:
    """Rest a 1-contract post-only bid at the minimum price, then cancel it, timing both calls."""
    body = build_order_body(ticker, "yes", "1", "0.01", post_only=True)
    start = time.perf_counter()
    order = client.create_order(body)
    place_ms = _ms(start)
    start = time.perf_counter()
    try:
        client.cancel_order(order["order_id"], ticker)
    except ClientError as exc:
        raise ClientError(
            f"Benchmark order {order['order_id']} was placed but the cancel failed: {exc}. "
            f"Cancel it: kalshi orders cancel {order['order_id']} --ticker {ticker} --demo --yes"
        ) from exc
    return {"order_place_ms": place_ms, "order_cancel_ms": _ms(start)}


@app.command("get")
@command
def metrics_get(
    series: str = typer.Option("btc15m", "--series", "-s", help="Preset name or series ticker used for the market request"),
    samples: int = typer.Option(20, "--samples", min=2, help="Warm requests to time on the reused connection"),
    orders: bool = typer.Option(False, "--orders", help="Also time a demo order place and cancel round trip (demo credentials required)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm placing the demo benchmark order"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the benchmark order without sending it"),
    table: bool = TABLE_OPTION,
    properties: Optional[str] = PROPERTIES_OPTION,
    env: Optional[str] = ENV_OPTION,
    demo: bool = DEMO_OPTION,
):
    """Measure cold and warm REST latency, signing cost, and optionally the demo order round trip."""
    environment = resolve_env(env, demo)
    series_ticker = resolve_series(series)[0]
    if orders:
        if not (yes or dry_run):
            raise ClientError("Refusing to place benchmark order without --yes or --dry-run")
        if environment != "demo":
            raise ClientError("Refusing to place benchmark order outside the demo exchange. Use --demo.")
        if dry_run:
            body = {**build_order_body(series_ticker, "yes", "1", "0.01", post_only=True), "ticker": f"<open market of {series_ticker}>"}
            print_json({"dry_run": True, "environment": environment, "body": body})
            return

    result = {"environment": environment, "series_ticker": series_ticker, "samples": samples}
    with open_client(environment, False) as client:
        client.max_retries = 0  # a retried 429 would silently inflate the timings, so any failure is reported
        start = time.perf_counter()
        client.list_markets(series=series_ticker, status="open", limit=5)
        result["rest_cold_ms"] = _ms(start)
        timings = []
        for _ in range(samples):
            time.sleep(SAMPLE_SPACING_SECONDS)
            start = time.perf_counter()
            client.list_markets(series=series_ticker, status="open", limit=5)
            timings.append((time.perf_counter() - start) * 1000)
        timings.sort()
        result["rest_warm_ms"] = {
            "min": round(timings[0], 2),
            "p50": round(statistics.median(timings), 2),
            "p95": round(timings[min(len(timings) - 1, int(len(timings) * 0.95))], 2),
            "max": round(timings[-1], 2),
        }
        result["sign_microseconds"] = _sign_microseconds()
        if orders:
            auth_client = open_client(environment, False, auth=True)
            with auth_client:
                result.update(_order_round_trip(auth_client, client.current_market(series_ticker)["ticker"]))
    emit_record(result, table, properties)
