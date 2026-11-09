"""Live market state: one long-lived WebSocket session, local state, no polling."""

import asyncio
import os
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterator, Optional

import orjson
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.paths import resolve_state_dir

from .client import KalshiClient, parse_time

MAX_CONSECUTIVE_FAILURES = 5
RECONNECT_BASE_DELAY = 0.5
RECONNECT_MAX_DELAY = 30.0
HEALTHY_SESSION_SECONDS = 30.0
ROLLOVER_POLL_SECONDS = 1.0
ROLLOVER_MAX_POLL_SECONDS = 2.0
ROLLOVER_WARN_SECONDS = 60.0
RETRYABLE_HANDSHAKE_STATUS = {429, 500, 502, 503, 504}


class StreamOutputError(ClientError):
    """Writing the stream's own output (stdout callback or state file) failed; the socket is fine."""


def _price(price: Optional[str], size: Optional[str]) -> Optional[str]:
    """A quoted price only counts when contracts are resting at it."""
    if price in (None, "") or size in (None, "") or Decimal(size) <= 0:
        return None
    return price


def _complement(price: Optional[str]) -> Optional[str]:
    return None if price is None else f"{Decimal(1) - Decimal(price):.4f}"


def market_view(market: dict, reference: Optional[dict] = None, preset: Optional[dict] = None, now: Optional[float] = None) -> dict:
    """Derive the trading view of a market: target, reference price, time left, YES/NO quotes."""
    preset = preset or {}
    now = time.time() if now is None else now
    yes_bid_size = market.get("yes_bid_size_fp")
    yes_ask_size = market.get("yes_ask_size_fp")
    yes_bid = _price(market.get("yes_bid_dollars"), yes_bid_size)
    yes_ask = _price(market.get("yes_ask_dollars"), yes_ask_size)
    target = market.get("floor_strike")
    reference_price = reference["value"] if reference else None
    delta = None
    if reference_price is not None and target is not None:
        delta = f"{Decimal(reference_price) - Decimal(str(target)):.2f}"
    return {
        "ticker": market["ticker"],
        "close_time": market["close_time"],
        "seconds_left": round(parse_time(market["close_time"]) - now, 1),
        "target_price": target,
        "reference_index": preset.get("reference_index"),
        "reference_price": reference_price,
        "reference_ts_ms": reference["ts_ms"] if reference else None,
        "delta": delta,
        "yes_label": preset.get("yes_label"),
        "yes_bid": yes_bid,
        "yes_bid_size": yes_bid_size if yes_bid else None,
        "yes_ask": yes_ask,
        "yes_ask_size": yes_ask_size if yes_ask else None,
        "no_label": preset.get("no_label"),
        "no_bid": _complement(yes_ask),
        "no_bid_size": yes_ask_size if yes_ask else None,
        "no_ask": _complement(yes_bid),
        "no_ask_size": yes_bid_size if yes_bid else None,
        "last_price": market.get("last_price_dollars"),
        "volume": market.get("volume_fp"),
        "open_interest": market.get("open_interest_fp"),
    }


TICKER_FIELDS = {
    "yes_bid_dollars": "yes_bid_dollars",
    "yes_ask_dollars": "yes_ask_dollars",
    "yes_bid_size_fp": "yes_bid_size_fp",
    "yes_ask_size_fp": "yes_ask_size_fp",
    "price_dollars": "last_price_dollars",
    "volume_fp": "volume_fp",
    "open_interest_fp": "open_interest_fp",
}


class MarketState:
    """Local state of one market plus its reference index, updated from WebSocket messages."""

    def __init__(self, market: dict, preset: Optional[dict] = None):
        self.market = dict(market)
        self.preset = preset or {}
        self.reference: Optional[dict] = None
        self.sids: dict = {}

    @property
    def ready(self) -> bool:
        return not self.preset.get("reference_index") or self.reference is not None

    def roll(self, market: dict) -> None:
        self.market = dict(market)

    def apply(self, message) -> Optional[str]:
        """Apply one message; return the event name when the state changed."""
        if not isinstance(message, dict) or not isinstance(message.get("msg", {}), dict):
            raise ClientError(f"Unexpected Kalshi WebSocket frame: {str(message)[:200]}")
        kind = message.get("type")
        body = message.get("msg", {})
        try:
            if kind == "subscribed":
                self.sids[body["channel"]] = body["sid"]
            elif kind == "error":
                raise ClientError(f"Kalshi WebSocket error {body.get('code')}: {body.get('msg')}")
            elif kind == "ticker" and body["market_ticker"] == self.market["ticker"]:
                for source, target in TICKER_FIELDS.items():
                    self.market[target] = body[source]
                return "ticker"
            elif kind == "cfbenchmarks_value_5hz" and body["index_id"] == self.preset.get("reference_index"):
                self.reference = {
                    "value": body["value_usd"],
                    "ts_ms": body["source_ts_ms"],
                    "received_ms": int(time.time() * 1000),
                }
                return "reference"
        except KeyError as exc:
            raise ClientError(f"Kalshi WebSocket {kind} message is missing field {exc}: {str(message)[:200]}") from exc
        return None

    def view(self) -> dict:
        return market_view(self.market, self.reference, self.preset)


def state_path(env: str, series: str) -> Path:
    return resolve_state_dir("kalshi") / "stream" / f"{env}-{series}.json"


def write_state(path: Path, view: dict, reference_received_ms: Optional[int]) -> None:
    """Atomically publish the latest stream view so `markets current` can read it."""
    payload = {**view, "written_ms": int(time.time() * 1000), "reference_received_ms": reference_received_ms}
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(orjson.dumps(payload))
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def read_state(path: Path, max_age_seconds: float) -> Optional[dict]:
    """Return the published stream view when both the file and its reference price are fresher than `max_age_seconds`.

    A missing file, a file with unusable content and a stale or future-dated file all mean
    "no live stream"; an unreadable file (permissions) is an error naming the file.
    """
    try:
        data = orjson.loads(path.read_bytes())
    except FileNotFoundError:
        return None
    except (orjson.JSONDecodeError, UnicodeDecodeError):
        return None
    except OSError as exc:
        raise ClientError(f"Cannot read stream state {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("ticker"), str) or not isinstance(data.get("reference_price"), str):
        return None
    now_ms = time.time() * 1000
    for key in ("written_ms", "reference_received_ms"):
        stamp = data.get(key)
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not 0 <= now_ms - stamp <= max_age_seconds * 1000:
            return None
    return data


async def _subscribe(ws, state: MarketState, ids: Iterator[int]) -> None:
    commands = [
        {"id": next(ids), "cmd": "subscribe", "params": {"channels": ["ticker"], "market_tickers": [state.market["ticker"]]}}
    ]
    index_id = state.preset.get("reference_index")
    if index_id:
        commands.append(
            {"id": next(ids), "cmd": "subscribe", "params": {"channels": ["cfbenchmarks_value_5hz"], "index_ids": [index_id]}}
        )
    for command in commands:
        await ws.send(orjson.dumps(command).decode())


async def _roll_markets(ws, client: KalshiClient, series: str, state: MarketState, ids: Iterator[int], emit: Callable) -> None:
    """When the open market closes, move the ticker subscription to the next market on the same socket.

    Waits as long as the series has no open market, warning on stderr once a minute.
    """
    while True:
        await asyncio.sleep(max(parse_time(state.market["close_time"]) - time.time(), 0) + 0.5)
        old = state.market["ticker"]
        waiting_since = time.monotonic()
        last_warning = waiting_since
        delay = ROLLOVER_POLL_SECONDS
        while True:
            try:
                market = await asyncio.to_thread(client.current_market, series)
            except ClientError:
                market = None
            if market is not None and market["ticker"] != old:
                break
            now = time.monotonic()
            if now - last_warning >= ROLLOVER_WARN_SECONDS:
                print(f"Still waiting for a new open market in series {series} ({now - waiting_since:.0f}s).", file=sys.stderr)
                last_warning = now
            await asyncio.sleep(delay)
            delay = min(delay * 2, ROLLOVER_MAX_POLL_SECONDS)
        sid = state.sids["ticker"]
        for action, ticker in (("add_markets", market["ticker"]), ("delete_markets", old)):
            command = {"id": next(ids), "cmd": "update_subscription", "params": {"sid": sid, "action": action, "market_tickers": [ticker]}}
            await ws.send(orjson.dumps(command).decode())
        state.roll(market)
        emit("rollover", state)


async def _session(client: KalshiClient, series: str, state: MarketState, ids: Iterator[int], emit: Callable) -> None:
    from websockets.asyncio.client import connect  # deferred: only `watch` pays the import cost

    async with connect(
        client.ws_url, additional_headers=client.ws_headers(), compression=None, open_timeout=10, max_size=2**20
    ) as ws:
        await _subscribe(ws, state, ids)
        roller = asyncio.create_task(_roll_markets(ws, client, series, state, ids, emit))
        try:
            async for raw in ws:
                try:
                    message = orjson.loads(raw)
                except orjson.JSONDecodeError as exc:
                    raise ClientError(f"Kalshi WebSocket sent a non-JSON frame: {exc}") from exc
                event = state.apply(message)
                if event:
                    emit(event, state)
                if roller.done():
                    roller.result()
        finally:
            roller.cancel()


async def stream_market(
    client: KalshiClient,
    series: str,
    preset: Optional[dict],
    on_update: Callable[[dict], Optional[bool]],
    duration: Optional[float] = None,
    path: Optional[Path] = None,
) -> None:
    """Stream the open market of `series` until `duration` elapses or `on_update` returns True."""
    from websockets.exceptions import ConnectionClosed, InvalidStatus

    state = MarketState(await asyncio.to_thread(client.current_market, series), preset)
    ids = iter(range(1, 1_000_000))
    done = asyncio.Event()

    def emit(event: str, current: MarketState) -> None:
        if done.is_set() or not current.ready:
            return
        view = {"event": event, **current.view()}
        if view["seconds_left"] < 0 and event != "rollover":
            return  # the market has closed and the next one is not open yet
        try:
            if path is not None:
                write_state(path, view, current.reference["received_ms"] if current.reference else None)
            if on_update(view):
                done.set()
        except OSError as exc:
            raise StreamOutputError(f"Cannot write stream output: {exc}") from exc

    async def run() -> None:
        failures = 0
        while not done.is_set():
            started = time.monotonic()
            session = asyncio.create_task(_session(client, series, state, ids, emit))
            stopper = asyncio.create_task(done.wait())
            await asyncio.wait({session, stopper}, return_when=asyncio.FIRST_COMPLETED)
            stopper.cancel()
            if done.is_set():
                session.cancel()
                return
            try:
                session.result()
            except InvalidStatus as exc:
                status = exc.response.status_code
                if status not in RETRYABLE_HANDSHAKE_STATUS:
                    raise ClientError(f"WebSocket handshake rejected: HTTP {status}") from exc
            except (ConnectionClosed, OSError, TimeoutError):
                pass
            failures = 1 if time.monotonic() - started >= HEALTHY_SESSION_SECONDS else failures + 1
            if failures > MAX_CONSECUTIVE_FAILURES:
                raise ClientError(f"WebSocket connection lost {failures} times in a row.")
            await asyncio.sleep(min(RECONNECT_BASE_DELAY * 2 ** (failures - 1), RECONNECT_MAX_DELAY))

    try:
        async with asyncio.timeout(duration):
            await run()
    except TimeoutError:
        return
