"""Kalshi REST client: one persistent keep-alive connection, orjson, per-request signing."""

import math
import random
import re
import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx
import orjson
from cli_tools_shared.exceptions import ClientError, CredentialError

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_PAGE_SIZE = 1000

ENVIRONMENTS = {
    "prod": {
        "rest": "https://external-api.kalshi.com/trade-api/v2",
        "ws": "wss://external-api-ws.kalshi.com/trade-api/ws/v2",
    },
    "demo": {
        "rest": "https://external-api.demo.kalshi.co/trade-api/v2",
        "ws": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
    },
}

TIME_IN_FORCE = {
    "gtc": "good_till_canceled",
    "ioc": "immediate_or_cancel",
    "fok": "fill_or_kill",
}
SELF_TRADE_PREVENTION = ("taker_at_cross", "maker")
MAX_EXPIRATION_SECONDS = 10_000_000_000  # a larger Unix timestamp is milliseconds, not seconds

_IDENTIFIER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*", re.ASCII)
_PLAIN_DECIMAL = re.compile(r"[0-9]+(\.[0-9]+)?")


def identifier(value: str, label: str) -> str:
    """Validate a ticker or ID that is placed in a URL path or an order body."""
    if not _IDENTIFIER.fullmatch(value):
        raise ClientError(f"Invalid {label} '{value}': use letters, digits, '.', '_' and '-' only.")
    return value


def resolve_env(env: Optional[str], demo: bool) -> str:
    """Resolve --env/--demo to an environment name; production is the default."""
    if demo and env not in (None, "demo"):
        raise ClientError(f"--demo conflicts with --env {env}.")
    name = "demo" if demo else (env or "prod").lower()
    if name not in ENVIRONMENTS:
        raise ClientError(f"Invalid --env '{name}'. Valid values: {', '.join(ENVIRONMENTS)}")
    return name


def parse_time(value: str) -> float:
    """Parse a Kalshi RFC 3339 timestamp to epoch seconds."""
    return datetime.fromisoformat(value).timestamp()


def _decimal(value: str, label: str) -> Decimal:
    """Parse a plain positive decimal such as 0.55; exponents, signs, separators and NaN are rejected."""
    if not _PLAIN_DECIMAL.fullmatch(value.strip()):
        raise ClientError(f"{label} must be a plain decimal number such as 0.55, got: {value}")
    return Decimal(value.strip())


def _decimals(number: Decimal) -> int:
    """Number of decimal places the value really needs (0.5000 needs one)."""
    return max(-number.normalize().as_tuple().exponent, 0)


def build_order_body(
    ticker: str,
    outcome: str,
    count: str,
    price: str,
    *,
    time_in_force: str = "gtc",
    post_only: bool = False,
    reduce_only: bool = False,
    expiration_ts: Optional[int] = None,
    client_order_id: Optional[str] = None,
    self_trade_prevention: str = "taker_at_cross",
) -> dict:
    """Build a Create Order V2 body.

    `price` is the price of the chosen outcome in dollars. Kalshi quotes every V2 order
    from the YES side: buying YES is a `bid` at the price, buying NO is an `ask` at
    `1 - price` (selling YES at 1 - p equals buying NO at p).
    """
    outcome = outcome.lower()
    if outcome not in ("yes", "no"):
        raise ClientError(f"Invalid outcome '{outcome}'. Valid values: yes, no")
    tif = time_in_force.lower()
    if tif not in TIME_IN_FORCE:
        raise ClientError(f"Invalid time in force '{time_in_force}'. Valid values: {', '.join(TIME_IN_FORCE)}")
    if self_trade_prevention not in SELF_TRADE_PREVENTION:
        raise ClientError(
            f"Invalid self-trade prevention '{self_trade_prevention}'. Valid values: {', '.join(SELF_TRADE_PREVENTION)}"
        )
    contracts = _decimal(count, "Count")
    if contracts <= 0 or _decimals(contracts) > 2:
        raise ClientError(f"Count must be positive with at most 2 decimals, got: {count}")
    dollars = _decimal(price, "Price")
    if not Decimal(0) < dollars < Decimal(1) or _decimals(dollars) > 4:
        raise ClientError(f"Price must be between 0 and 1 dollars exclusive with at most 4 decimals, got: {price}")
    if reduce_only and tif != "ioc":
        raise ClientError("--reduce-only requires --tif ioc.")
    if expiration_ts is not None:
        if tif != "gtc":
            raise ClientError("--expiration-ts requires --tif gtc.")
        if expiration_ts > MAX_EXPIRATION_SECONDS:
            raise ClientError(f"--expiration-ts must be Unix seconds, got a millisecond-sized value: {expiration_ts}")
        if expiration_ts <= time.time():
            raise ClientError(f"--expiration-ts must be in the future, got: {expiration_ts}")
    identifier(ticker, "ticker")
    if client_order_id is not None:
        identifier(client_order_id, "client order ID")

    body = {
        "ticker": ticker,
        "side": "bid" if outcome == "yes" else "ask",
        "count": format(contracts.normalize(), "f"),
        "price": f"{dollars if outcome == 'yes' else Decimal(1) - dollars:.4f}",
        "time_in_force": TIME_IN_FORCE[tif],
        "self_trade_prevention_type": self_trade_prevention,
        "client_order_id": client_order_id or str(uuid.uuid4()),
    }
    if post_only:
        body["post_only"] = True
    if reduce_only:
        body["reduce_only"] = True
    if expiration_ts is not None:
        body["expiration_time"] = expiration_ts
    return body


def field(body: dict, key: str, endpoint: str):
    """Read a required response field, naming the endpoint when it is missing."""
    if key not in body:
        raise ClientError(f"GET {endpoint} response has no '{key}' field.")
    return body[key]


class KalshiClient:
    """Client for one Kalshi environment, reusing a single pooled connection for every call."""

    def __init__(
        self,
        env: str = "prod",
        signer=None,
        signer_factory: Optional[Callable] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.env = env
        self.base_url = ENVIRONMENTS[env]["rest"]
        self.ws_url = ENVIRONMENTS[env]["ws"]
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._signer = signer
        self._signer_factory = signer_factory
        self._path_prefix = urlparse(self.base_url).path
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"Accept": "application/json"},
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4, keepalive_expiry=120.0),
            transport=transport,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        self._http.close()

    @property
    def signer(self):
        if self._signer is None and self._signer_factory is not None:
            self._signer = self._signer_factory()
        if self._signer is None:
            raise CredentialError(f"No Kalshi {self.env} credentials available. Run: kalshi auth login")
        return self._signer

    def ws_headers(self) -> dict:
        """Signed handshake headers for the WebSocket endpoint."""
        return self.signer.headers("GET", urlparse(self.ws_url).path)

    def prewarm(self) -> None:
        """Open the TLS connection with a public request so the next call reuses it."""
        self.request("GET", "/exchange/status")

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    @staticmethod
    def _get_retry_after(response: httpx.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            seconds = float(value)
        except ValueError:
            return None
        return seconds if math.isfinite(seconds) and seconds >= 0 else None

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            return " ".join(response.text.split())[:200] or "Unknown error"
        if isinstance(body, dict):
            error = body.get("error") if isinstance(body.get("error"), dict) else body
            parts = [str(error[key]) for key in ("code", "message", "details") if error.get(key)]
            if parts:
                return ": ".join(parts)
        return str(body)[:200]

    def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        body: Optional[dict] = None,
        auth: bool = False,
        retry: bool = True,
    ) -> dict:
        """Send one request on the shared connection and return the parsed JSON object."""
        params = {key: value for key, value in (params or {}).items() if value is not None} or None
        content = orjson.dumps(body) if body is not None else None
        base_headers = {"Content-Type": "application/json"} if content is not None else {}
        sign_path = f"{self._path_prefix}{endpoint}"
        attempts = self.max_retries + 1 if retry else 1
        response: Optional[httpx.Response] = None
        error: Optional[Exception] = None

        for attempt in range(attempts):
            headers = dict(base_headers)
            if auth:
                headers.update(self.signer.headers(method, sign_path))
            try:
                response = self._http.request(method, endpoint, params=params, content=content, headers=headers)
                error = None
            except httpx.LocalProtocolError as exc:
                raise ClientError(f"Request to {endpoint} is malformed: {exc}") from exc
            except httpx.TransportError as exc:
                response, error = None, exc
                if attempt < attempts - 1:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < attempts - 1:
                time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                continue
            break

        if response is None:
            raise ClientError(f"Request failed after {attempts} attempt(s): {error}")
        if response.status_code >= 300:
            raise ClientError(f"HTTP {response.status_code}: {self._error_detail(response)}")
        if not response.content:
            return {}
        try:
            body = orjson.loads(response.content)
        except orjson.JSONDecodeError as exc:
            raise ClientError(f"{method} {endpoint} returned invalid JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise ClientError(f"{method} {endpoint} returned {type(body).__name__}, expected a JSON object.")
        return body

    def _paged(self, endpoint: str, key: str, params: dict, limit: int, auth: bool = False) -> list:
        items: list = []
        cursor = None
        while True:
            page = self.request(
                "GET", endpoint, {**params, "limit": min(limit - len(items), MAX_PAGE_SIZE), "cursor": cursor}, auth=auth
            )
            rows = field(page, key, endpoint)
            items.extend(rows)
            next_cursor = page.get("cursor")
            if not next_cursor or len(items) >= limit:
                return items[:limit]
            if not rows or next_cursor == cursor:
                raise ClientError(f"GET {endpoint} returned a cursor that does not advance.")
            cursor = next_cursor

    def list_markets(self, series: Optional[str] = None, status: Optional[str] = None, limit: int = 100, **params) -> list:
        return self._paged("/markets", "markets", {"series_ticker": series, "status": status, **params}, limit)

    def get_market(self, ticker: str) -> dict:
        path = f"/markets/{identifier(ticker, 'ticker')}"
        return field(self.request("GET", path), "market", path)

    def get_orderbook(self, ticker: str) -> dict:
        path = f"/markets/{identifier(ticker, 'ticker')}/orderbook"
        response = self.request("GET", path, {"depth": 0})
        field(response, "orderbook_fp", path)
        return response

    def current_market(self, series: str) -> dict:
        """Return the market of a series that is open right now (earliest close time)."""
        now = time.time()
        running = [
            market
            for market in self.list_markets(series=series, status="open", limit=100)
            if parse_time(market["open_time"]) <= now < parse_time(market["close_time"])
        ]
        if not running:
            raise ClientError(f"No market is open right now for series {series}.")
        return min(running, key=lambda market: market["close_time"])

    def list_orders(self, limit: int = 100, **params) -> list:
        return self._paged("/portfolio/orders", "orders", params, limit, auth=True)

    def get_order(self, order_id: str) -> dict:
        path = f"/portfolio/orders/{identifier(order_id, 'order ID')}"
        return field(self.request("GET", path, auth=True), "order", path)

    def create_order(self, body: dict) -> dict:
        """Place an order. Never retried: a retry after a lost response could double-place it."""
        return self.request("POST", "/portfolio/events/orders", body=body, auth=True, retry=False)

    def cancel_order(self, order_id: str, ticker: Optional[str] = None) -> dict:
        return self.request(
            "DELETE",
            f"/portfolio/events/orders/{identifier(order_id, 'order ID')}",
            {"market_ticker": identifier(ticker, "ticker") if ticker else None},
            auth=True,
            retry=False,
        )

    def balance(self) -> dict:
        return self.request("GET", "/portfolio/balance", auth=True)

    def list_positions(self, limit: int = 100, **params) -> list:
        return self._paged("/portfolio/positions", "market_positions", params, limit, auth=True)
