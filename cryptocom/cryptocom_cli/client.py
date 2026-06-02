"""Crypto.com Exchange REST API client."""
from typing import Any, Dict, List, Optional, TypeVar
import hashlib
import hmac
import random
import time
import warnings

warnings.filterwarnings("ignore", module="urllib3")

import requests
from pydantic import BaseModel

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters, apply_limit, validate_filters

from .config import get_config
from .models import (
    AccountBalance,
    BookSnapshot,
    Candlestick,
    Instrument,
    OpenOrder,
    Ticker,
    Trade,
)


DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

activity = get_activity_logger("cryptocom")
ModelT = TypeVar("ModelT", bound=BaseModel)


class CryptocomClient:
    """Client for Crypto.com Exchange REST API."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        self.base_url = self.config.base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = self.base_delay * (2 ** attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _is_retryable(self, response: Optional[requests.Response], exception: Optional[Exception]) -> bool:
        """Return true when a failed request should be retried."""
        if exception is not None:
            return isinstance(
                exception,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                ),
            )
        return response is not None and response.status_code in RETRYABLE_STATUS_CODES

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        """Read Retry-After seconds from a response."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        try:
            return float(retry_after)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        """Extract error detail from a failed HTTP response."""
        try:
            body = response.json()
        except ValueError:
            if response.text:
                return response.text[:500]
            return "Unknown error"

        message = body.get("message")
        if message:
            return str(message)
        return str(body)[:500]

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        retry: bool = True,
    ) -> Dict[str, Any]:
        """Make an HTTP request with retry and return parsed JSON."""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        max_attempts = self.max_retries + 1 if retry else 1
        last_response: Optional[requests.Response] = None
        last_exception: Optional[Exception] = None

        for attempt in range(max_attempts):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=30,
                )
                last_response = response
                activity.info("%s %s -> %s", method, url, response.status_code)

                if retry and self._is_retryable(response, None) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt, self._get_retry_after(response))
                    activity.warning("Retrying %s after HTTP %s in %.2fs", url, response.status_code, delay)
                    time.sleep(delay)
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                activity.warning("Request exception for %s: %s", url, exc)
                if retry and self._is_retryable(None, exc) and attempt < self.max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    activity.warning("Retrying %s after exception in %.2fs", url, delay)
                    time.sleep(delay)
                    continue
                break

        if last_response is None:
            raise ClientError(f"Request failed: {last_exception}")

        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")

        try:
            return last_response.json()
        except ValueError as exc:
            raise ClientError("Response was not valid JSON") from exc

    def _extract_result(self, body: Dict[str, Any], method_name: str) -> Dict[str, Any]:
        """Validate Exchange response envelope and return result."""
        code = body.get("code")
        if code != 0:
            message = body.get("message") or body.get("original") or body
            raise ClientError(f"{method_name} failed with code {code}: {message}")
        if "result" not in body:
            raise ClientError(f"{method_name} response did not include result")
        return body["result"]

    def _make_public_request(
        self,
        method_name: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call a public Exchange API method."""
        url = f"{self.base_url}/{method_name}"
        activity.info("Calling public method %s", method_name)
        body = self._request_json("GET", url, params=params)
        return self._extract_result(body, method_name)

    def _require_credentials(self):
        """Fail unless API key and secret are configured."""
        if not self.config.has_credentials():
            missing = ", ".join(self.config.get_missing_credentials())
            raise ClientError(f"Missing credentials: {missing}. Run 'cryptocom auth login'.")

    def _signature_value(self, value: Any) -> str:
        """Convert a parameter value into Crypto.com signature text."""
        if isinstance(value, dict):
            return "".join(f"{key}{self._signature_value(value[key])}" for key in sorted(value))
        if isinstance(value, list):
            return "".join(self._signature_value(item) for item in value)
        if value is None:
            return "null"
        return str(value)

    def _parameter_string(self, params: Dict[str, Any]) -> str:
        """Build Crypto.com signature parameter string."""
        return "".join(f"{key}{self._signature_value(params[key])}" for key in sorted(params))

    def _signature(self, method_name: str, request_id: int, params: Dict[str, Any], nonce: int) -> str:
        """Generate the HMAC-SHA256 request signature."""
        payload = f"{method_name}{request_id}{self.config.api_key}{self._parameter_string(params)}{nonce}"
        return hmac.new(
            self.config.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _make_private_request(
        self,
        method_name: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call a signed private Exchange API method."""
        self._require_credentials()
        request_params = params or {}
        nonce = int(time.time() * 1000)
        request_id = nonce
        body = {
            "id": request_id,
            "method": method_name,
            "api_key": self.config.api_key,
            "params": request_params,
            "nonce": nonce,
        }
        body["sig"] = self._signature(method_name, request_id, request_params, nonce)

        url = f"{self.base_url}/{method_name}"
        activity.info("Calling private method %s", method_name)
        response_body = self._request_json("POST", url, json_body=body)
        return self._extract_result(response_body, method_name)

    def _filter_models(
        self,
        models: List[ModelT],
        filters: Optional[List[str]],
        model_type: type[ModelT],
    ) -> List[ModelT]:
        """Apply standard filters to model instances."""
        if not filters:
            return models
        validate_filters(filters)
        rows = [model.model_dump(mode="json") for model in models]
        return [model_type(**row) for row in apply_filters(rows, filters)]

    def _limit_models(self, models: List[ModelT], limit: Optional[int]) -> List[ModelT]:
        """Apply output limit for endpoints without server-side limit support."""
        return apply_limit(models, limit)

    def list_instruments(
        self,
        limit: Optional[int] = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Instrument]:
        """List Exchange instruments."""
        result = self._make_public_request("public/get-instruments")
        instruments = [Instrument(**item) for item in result["data"]]
        instruments = self._filter_models(instruments, filters, Instrument)
        return self._limit_models(instruments, limit)

    def get_instrument(self, symbol: str) -> Instrument:
        """Get one instrument by symbol."""
        symbols = self.list_instruments(limit=None)
        for instrument in symbols:
            if instrument.symbol == symbol:
                return instrument
        raise ClientError(f"Instrument not found: {symbol}")

    def get_ticker(self, instrument_name: str) -> Ticker:
        """Get ticker data for an instrument."""
        result = self._make_public_request(
            "public/get-tickers",
            params={"instrument_name": instrument_name},
        )
        data = result["data"]
        if not data:
            raise ClientError(f"Ticker not found: {instrument_name}")
        return Ticker(**data[0])

    def list_tickers(
        self,
        limit: Optional[int] = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Ticker]:
        """List tickers."""
        result = self._make_public_request("public/get-tickers")
        tickers = [Ticker(**item) for item in result["data"]]
        tickers = self._filter_models(tickers, filters, Ticker)
        return self._limit_models(tickers, limit)

    def get_book(self, instrument_name: str, depth: int = 10) -> BookSnapshot:
        """Get order book snapshot for an instrument."""
        result = self._make_public_request(
            "public/get-book",
            params={"instrument_name": instrument_name, "depth": depth},
        )
        data = result["data"]
        if not data:
            raise ClientError(f"Order book not found: {instrument_name}")
        snapshot = data[0] | {
            "instrument_name": result["instrument_name"],
            "depth": result["depth"],
        }
        return BookSnapshot(**snapshot)

    def list_trades(
        self,
        instrument_name: str,
        limit: int = 25,
        start_ts: Optional[str] = None,
        end_ts: Optional[str] = None,
        filters: Optional[List[str]] = None,
    ) -> List[Trade]:
        """List recent trades for an instrument."""
        params = {"instrument_name": instrument_name, "count": limit}
        if start_ts:
            params["start_ts"] = start_ts
        if end_ts:
            params["end_ts"] = end_ts
        result = self._make_public_request("public/get-trades", params=params)
        trades = [Trade(**item) for item in result["data"]]
        return self._filter_models(trades, filters, Trade)

    def get_trade(self, instrument_name: str, trade_id: str) -> Trade:
        """Get one recent trade by trade ID."""
        trades = self.list_trades(instrument_name=instrument_name, limit=150)
        for trade in trades:
            if trade.d == trade_id:
                return trade
        raise ClientError(f"Trade not found in recent trades: {trade_id}")

    def list_candlesticks(
        self,
        instrument_name: str,
        timeframe: str,
        limit: int = 25,
        start_ts: Optional[str] = None,
        end_ts: Optional[str] = None,
        filters: Optional[List[str]] = None,
    ) -> List[Candlestick]:
        """List candlesticks for an instrument."""
        params = {
            "instrument_name": instrument_name,
            "timeframe": timeframe,
            "count": limit,
        }
        if start_ts:
            params["start_ts"] = start_ts
        if end_ts:
            params["end_ts"] = end_ts
        result = self._make_public_request("public/get-candlestick", params=params)
        candles = [Candlestick(**item) for item in result["data"]]
        return self._filter_models(candles, filters, Candlestick)

    def get_candlestick(
        self,
        instrument_name: str,
        timestamp: int,
        timeframe: str,
    ) -> Candlestick:
        """Get one recent candlestick by start timestamp."""
        candles = self.list_candlesticks(
            instrument_name=instrument_name,
            timeframe=timeframe,
            limit=150,
        )
        for candle in candles:
            if candle.t == timestamp:
                return candle
        raise ClientError(f"Candlestick not found in recent data: {timestamp}")

    def get_balances(
        self,
        limit: Optional[int] = 100,
        filters: Optional[List[str]] = None,
    ) -> List[AccountBalance]:
        """Get account balances."""
        result = self._make_private_request("private/user-balance", params={})
        balances = [AccountBalance(**item) for item in result["data"]]
        balances = self._filter_models(balances, filters, AccountBalance)
        return self._limit_models(balances, limit)

    def list_open_orders(
        self,
        instrument_name: Optional[str] = None,
        limit: Optional[int] = 100,
        filters: Optional[List[str]] = None,
    ) -> List[OpenOrder]:
        """List open orders."""
        params = {}
        if instrument_name:
            params["instrument_name"] = instrument_name
        result = self._make_private_request("private/get-open-orders", params=params)
        orders = [OpenOrder(**item) for item in result["data"]]
        orders = self._filter_models(orders, filters, OpenOrder)
        return self._limit_models(orders, limit)


_client: Optional[CryptocomClient] = None


def get_client() -> CryptocomClient:
    """Get or create the global Crypto.com Exchange client."""
    global _client
    if _client is None:
        _client = CryptocomClient()
    return _client
