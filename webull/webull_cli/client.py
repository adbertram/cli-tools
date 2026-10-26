"""Official Webull SDK boundary, with safe errors and no automatic write retries."""
from __future__ import annotations

import logging
import math
import re
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal

from cli_tools_shared.exceptions import ClientError
from .config import get_config

CATEGORY_US_FUTURES = "US_FUTURES"


HOSTS = {
    "sandbox": {"api": "api.sandbox.webull.com", "quotes-api": "data-api.sandbox.webull.com", "events-api": "events-api.sandbox.webull.com"},
    "live": {"api": "api.webull.com", "quotes-api": "data-api.webull.com", "events-api": "events-api.webull.com"},
}


@dataclass(frozen=True)
class Options:
    environment: str = "sandbox"
    confirm_live: bool = False
    profile: str | None = None
    region: str = "us"
    api_host: str | None = None
    quotes_api_host: str | None = None
    events_api_host: str | None = None
    connect_timeout: float = 3.0
    read_timeout: float = 6.0


_options = Options()


def configure(options: Options):
    global _options
    _options = options


class WebullError(ClientError):
    def __init__(self, kind, message, *, http_status=None, error_code=None, client_order_id=None):
        self.kind, self.message = kind, message
        self.http_status, self.error_code = http_status, error_code
        self.client_order_id = client_order_id
        super().__init__(message)

    def as_dict(self):
        result = {"kind": self.kind, "message": self.message, "http_status": self.http_status, "error_code": self.error_code}
        if self.client_order_id is not None:
            result["client_order_id"] = self.client_order_id
        return {"error": result}


def safe_error(error, *, write=False, client_order_id=None):
    if isinstance(error, WebullError):
        return error
    from webull.core.exception.exceptions import ServerException
    status = getattr(error, "http_status", None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    code = getattr(error, "error_code", None)
    if not (type(code) is int or isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", code)):
        code = None
    rejected = isinstance(error, ServerException) and status is not None and 300 <= status < 500
    kind = "rejected" if rejected else "unknown" if write else "upstream"
    name = type(error).__name__
    name = name if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,79}", name) else "SDKError"
    message = "Webull request failed (" + ", ".join(str(v) for v in (name, status, code) if v is not None) + ")."
    if kind == "unknown":
        message += " Order outcome is unknown; inspect its client_order_id before resending."
    return WebullError(kind, message, http_status=status, error_code=code, client_order_id=client_order_id)


def quiet(api):
    logging.getLogger("webull").setLevel(logging.CRITICAL)
    api._stream_logger_set = api._file_logger_set = True


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise WebullError("validation", f"{name} must be finite and positive.")


def canonical_host(value):
    """Normalize DNS-equivalent spelling before environment authorization."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]+)?", value):
        raise WebullError("validation", "Webull hosts must be hostnames, optionally with a port.")
    hostname, _, port = value.partition(":")
    hostname = hostname.removesuffix(".").lower()
    if len(hostname) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in hostname.split(".")):
        raise WebullError("validation", "Webull hosts must contain valid DNS labels.")
    if port and not 1 <= int(port) <= 65535:
        raise WebullError("validation", "Webull host ports must be between 1 and 65535.")
    return hostname + (f":{int(port)}" if port else "")


def tick_json(value):
    """Keep every decoded market-data field, including nested basic metadata."""
    if isinstance(value, Decimal):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {key: tick_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [tick_json(item) for item in value]
    return tick_json(vars(value))


class WebullClient:
    def __init__(self, config=None, options=None):
        self.options = options or _options
        opts = self.options
        if opts.environment not in HOSTS:
            raise WebullError("validation", "Environment must be sandbox or live.")
        if opts.environment == "live" and not opts.confirm_live:
            raise WebullError("authorization", "Live Webull access requires --confirm-live.")
        positive(opts.connect_timeout, "connect-timeout")
        positive(opts.read_timeout, "read-timeout")
        self.config = config or get_config(opts.profile)
        if not self.config.has_credentials():
            raise WebullError("authentication", "Missing Webull app key or app secret. Run 'webull auth login'.")
        self.hosts = dict(HOSTS[opts.environment])
        for key, value in (("api", opts.api_host), ("quotes-api", opts.quotes_api_host), ("events-api", opts.events_api_host)):
            if value is not None:
                self.hosts[key] = value
        self.hosts = {key: canonical_host(value) for key, value in self.hosts.items()}
        production_names = {canonical_host(value).partition(":")[0] for value in HOSTS["live"].values()}
        if opts.environment != "live" and any(value.partition(":")[0] in production_names for value in self.hosts.values()):
            raise WebullError("authorization", "Production Webull hosts require --environment live --confirm-live.")
        self._api = self._trade = self._data = None
        self._send_before_epoch_ms = None
        self._client_order_id = None

    @property
    def api(self):
        if self._api is None:
            from webull.core.client import ApiClient
            owner = self
            class GuardedApiClient(ApiClient):
                def get_response(self, request):
                    owner.check_send_deadline()
                    return super().get_response(request)
            self._api = GuardedApiClient(self.config._get("APP_KEY"), self.config._get("APP_SECRET"), self.options.region,
                                  connect_timeout=self.options.connect_timeout, timeout=self.options.read_timeout, auto_retry=False)
            quiet(self._api)
            for key, host in self.hosts.items():
                self._api.add_endpoint(self.options.region, host, key)
            if self.config.access_token:
                self._api.set_token(self.config.access_token)
        return self._api

    @property
    def trade(self):
        if self._trade is None:
            from webull.trade.trade_client import TradeClient
            self._trade = TradeClient(self.api)
        return self._trade

    @property
    def data(self):
        if self._data is None:
            from webull.data.data_client import DataClient
            self._data = DataClient(self.api)
        return self._data

    def call(self, method, *args, write=False, client_order_id=None, **kwargs):
        try:
            body = method(*args, **kwargs).json()
            if not isinstance(body, (dict, list)):
                raise ValueError("Expected Webull JSON object or array")
            return body
        except Exception as exc:
            raise safe_error(exc, write=write, client_order_id=client_order_id) from None

    def account_list(self):
        self.require_account_auth()
        return self.call(self.trade.account_v2.get_account_list)

    def balance(self, account):
        self.require_account_auth()
        return self.call(self.trade.account_v2.get_account_balance, account)

    def positions(self, account):
        self.require_account_auth()
        return self.call(self.trade.account_v2.get_account_position, account)

    def orders(self, account, *, history=False, page_size=100, last_client_order_id=None, start_date=None, end_date=None):
        self.require_account_auth()
        kwargs = {"page_size": page_size}
        if last_client_order_id is not None:
            kwargs["last_client_order_id"] = last_client_order_id
        if history:
            if start_date is not None:
                kwargs["start_date"] = start_date
            if end_date is not None:
                kwargs["end_date"] = end_date
        method = self.trade.order_v3.get_order_history if history else self.trade.order_v3.get_order_open
        return self.call(method, account, **kwargs)

    def accounting(self, account, *, start_date, end_date, page_size, read_interval_seconds):
        """Read complete raw history, balance and positions with one SDK client."""
        positive(read_interval_seconds, "read-interval-seconds")
        if type(page_size) is not int or not 10 <= page_size <= 100:
            raise WebullError("validation", "page-size must be between 10 and 100.")
        history, cursors, cursor = [], set(), None
        while True:
            page = self.orders(account, history=True, page_size=page_size,
                               last_client_order_id=cursor, start_date=start_date, end_date=end_date)
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                raise WebullError("upstream", "Malformed Webull accounting history page.")
            if not page:
                break
            cursor = page[-1].get("client_order_id")
            if not isinstance(cursor, str) or not cursor.strip() or cursor in cursors:
                raise WebullError("upstream", "Malformed or repeated Webull accounting history cursor.")
            cursors.add(cursor)
            history.extend(page)
            time.sleep(read_interval_seconds)
        balance = self.balance(account)
        if not isinstance(balance, dict):
            raise WebullError("upstream", "Malformed Webull accounting balance.")
        positions = self.positions(account)
        if not isinstance(positions, list):
            raise WebullError("upstream", "Malformed Webull accounting positions.")
        return {"history": history, "balance": balance, "positions": positions}

    def order(self, account, client_order_id):
        self.require_account_auth()
        return self.call(self.trade.order_v3.get_order_detail, account, client_order_id)

    def mutate(self, action, account, orders, *, send_before_epoch_ms=None):
        self.require_account_auth()
        ids = [order.get("client_order_id") for order in orders]
        cid = ids[0] if len(ids) == 1 else ids
        self._send_before_epoch_ms, self._client_order_id = send_before_epoch_ms, cid
        method = getattr(self.trade.order_v3, action + "_order")
        self.check_send_deadline()
        return self.call(method, account, orders, write=True, client_order_id=cid)

    def check_send_deadline(self):
        if self._send_before_epoch_ms is not None and time.time() * 1000 >= self._send_before_epoch_ms:
            raise WebullError("not_sent", "Webull send deadline expired; no request was sent.", client_order_id=self._client_order_id)

    def cancel(self, account, client_order_id):
        self.require_account_auth()
        return self.call(self.trade.order_v3.cancel_order, account, client_order_id, write=True, client_order_id=client_order_id)

    def bars(self, symbol, category, timespan, count):
        return self.call(self.data.futures_market_data.get_futures_history_bars, symbol, category, timespan, count=str(count))

    def require_account_auth(self):
        if self.options.environment == "live" and not self.config.access_token:
            raise WebullError("authentication", "Production account access requires an authorized access token. Save it with 'webull auth token'.")

    def stream(self, symbol, emit, *, category=CATEGORY_US_FUTURES, reconnect_attempts=3, reconnect_delay_milliseconds=1000,
               mqtt_port=8883, socket_loop_seconds=1, close_grace_seconds=2):
        from webull.data.data_streaming_client import DataStreamingClient
        from webull.data.internal.default_retry_policy import DefaultQuotesRetryPolicy
        from webull.data.quotes.subscribe.tick_decoder import TickDecoder
        from webull.core.exception.exceptions import ServerException
        from webull.core.retry.retry_condition import RetryCondition

        class Policy(DefaultQuotesRetryPolicy):
            def should_retry(self, context):
                emit({"event": "disconnect"})
                error = context.exception
                status = getattr(error, "http_status", None)
                if isinstance(error, ServerException) and isinstance(status, int) and 400 <= status < 500:
                    return RetryCondition.NO_RETRY
                return super().should_retry(context)

        sdk = DataStreamingClient(self.config._get("APP_KEY"), self.config._get("APP_SECRET"), self.options.region, uuid.uuid4().hex,
                                  http_host=self.hosts["api"], mqtt_host=self.hosts["quotes-api"], mqtt_port=mqtt_port, tls_enable=True,
                                  retry_policy=Policy(max_retry_times=reconnect_attempts, fixed_delay=reconnect_delay_milliseconds))
        quiet(sdk.api_client)
        sdk._api_client = self.api
        sdk._connect_timeout = self.options.connect_timeout

        class Decoder(TickDecoder):
            def parse(self, payload):
                try:
                    return super().parse(payload)
                except Exception:
                    emit({"event": "error", "error": {"kind": "payload", "message": "Malformed Webull TICK payload."}})
                    sdk._thread_terminate = True
                    sdk._sock_close()
                    return None

        sdk.register_payload_decoder("tick", Decoder())
        sdk.on_connect_success = lambda client, api, session: client.subscribe([symbol], category, ["TICK"])
        sdk.on_disconnect = lambda client, userdata, rc: emit({"event": "disconnect"})

        def message(client, topic, payload):
            if topic == "tick" and payload is not None:
                emit({"event": "tick", "data": tick_json(payload)})

        sdk.on_quotes_message = message
        try:
            sdk.connect_and_loop_forever(timeout=socket_loop_seconds, logger_enable=False)
            raise WebullError("upstream", "Webull tick connection ended.")
        except KeyboardInterrupt:
            return
        except Exception as exc:
            raise safe_error(exc) from None
        finally:
            sdk._thread_terminate = True
            sdk.disconnect()
            sdk._sock_close()
