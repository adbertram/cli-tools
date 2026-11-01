import json
import time
from datetime import datetime, timezone

import httpx
import pytest
from cli_tools_shared.exceptions import ClientError, CredentialError

from kalshi_cli.client import KalshiClient, build_order_body, resolve_env
from kalshi_cli.signing import Signer


def iso(offset: float) -> str:
    return datetime.fromtimestamp(time.time() + offset, timezone.utc).isoformat().replace("+00:00", "Z")


def make_client(handler, signer=None, **kwargs):
    return KalshiClient(env="demo", signer=signer, transport=httpx.MockTransport(handler), base_delay=0, **kwargs)


class TestEnvironment:
    def test_default_is_production(self):
        assert resolve_env(None, False) == "prod"

    def test_demo_flag(self):
        assert resolve_env(None, True) == "demo"
        assert resolve_env("demo", True) == "demo"

    def test_conflicting_flags_fail(self):
        with pytest.raises(ClientError, match="conflicts"):
            resolve_env("prod", True)

    def test_unknown_environment_fails(self):
        with pytest.raises(ClientError, match="Invalid --env"):
            resolve_env("staging", False)


class TestOrderBody:
    def test_buy_yes_is_a_bid_at_the_price(self):
        body = build_order_body("T", "yes", "3", "0.4", client_order_id="c1")
        assert body["side"] == "bid" and body["price"] == "0.4000" and body["count"] == "3"
        assert body["time_in_force"] == "good_till_canceled"
        assert body["client_order_id"] == "c1"

    def test_buy_no_is_an_ask_at_the_complement(self):
        body = build_order_body("T", "no", "1", "0.35")
        assert body["side"] == "ask" and body["price"] == "0.6500"

    def test_client_order_id_is_generated(self):
        assert build_order_body("T", "yes", "1", "0.5")["client_order_id"] != build_order_body("T", "yes", "1", "0.5")["client_order_id"]

    def test_optional_flags(self):
        body = build_order_body("T", "yes", "1", "0.5", time_in_force="ioc", reduce_only=True, post_only=True)
        assert body["time_in_force"] == "immediate_or_cancel" and body["reduce_only"] and body["post_only"]
        future = int(time.time()) + 3600
        assert build_order_body("T", "yes", "1", "0.5", expiration_ts=future)["expiration_time"] == future

    def test_trailing_zeros_do_not_count_as_extra_decimals(self):
        body = build_order_body("T", "yes", "1.50", "0.50000")
        assert body["count"] == "1.5" and body["price"] == "0.5000"

    @pytest.mark.parametrize("ticker", ["", " ", "../balance", "a/b", "a?b", "a#b", "..", "a b", "tic\nker"])
    def test_bad_tickers_are_rejected(self, ticker):
        with pytest.raises(ClientError, match="Invalid ticker"):
            build_order_body(ticker, "yes", "1", "0.5")

    @pytest.mark.parametrize(
        "kwargs,message",
        [
            ({"outcome": "maybe", "count": "1", "price": "0.5"}, "Invalid outcome"),
            ({"outcome": "yes", "count": "0", "price": "0.5"}, "Count must be positive"),
            ({"outcome": "yes", "count": "1.234", "price": "0.5"}, "Count must be positive"),
            ({"outcome": "yes", "count": "x", "price": "0.5"}, "Count must be a plain decimal"),
            ({"outcome": "yes", "count": "1", "price": "1"}, "Price must be between"),
            ({"outcome": "yes", "count": "1", "price": "0"}, "Price must be between"),
            ({"outcome": "yes", "count": "1", "price": "0.12345"}, "Price must be between"),
            ({"outcome": "yes", "count": "1", "price": "NaN"}, "plain decimal"),
            ({"outcome": "yes", "count": "1E+30", "price": "0.5"}, "plain decimal"),
            ({"outcome": "yes", "count": "1_000", "price": "0.5"}, "plain decimal"),
            ({"outcome": "yes", "count": "-1", "price": "0.5"}, "plain decimal"),
            ({"outcome": "yes", "count": "1", "price": "1e-3"}, "plain decimal"),
            ({"outcome": "yes", "count": "1", "price": "0.5", "expiration_ts": 1}, "must be in the future"),
            ({"outcome": "yes", "count": "1", "price": "0.5", "expiration_ts": 1893456000000}, "millisecond"),
            ({"outcome": "yes", "count": "1", "price": "0.5", "client_order_id": "   "}, "Invalid client order ID"),
            ({"outcome": "yes", "count": "1", "price": "0.5", "time_in_force": "day"}, "Invalid time in force"),
            ({"outcome": "yes", "count": "1", "price": "0.5", "reduce_only": True}, "requires --tif ioc"),
            ({"outcome": "yes", "count": "1", "price": "0.5", "time_in_force": "ioc", "expiration_ts": 5}, "requires --tif gtc"),
            ({"outcome": "yes", "count": "1", "price": "0.5", "self_trade_prevention": "x"}, "self-trade prevention"),
        ],
    )
    def test_invalid_orders_fail_explicitly(self, kwargs, message):
        with pytest.raises(ClientError, match=message):
            build_order_body("T", **kwargs)


class TestRequests:
    def test_signed_request_signs_full_path_without_query(self, ed_key, ed_pem):
        seen = {}

        def handler(request):
            seen["headers"] = request.headers
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"markets": [], "cursor": ""})

        client = make_client(handler, Signer("k", ed_pem))
        client.request("GET", "/portfolio/orders", {"limit": 5, "ticker": None}, auth=True)
        assert seen["url"].endswith("/trade-api/v2/portfolio/orders?limit=5")
        import base64

        message = f"{seen['headers']['kalshi-access-timestamp']}GET/trade-api/v2/portfolio/orders".encode()
        ed_key.public_key().verify(base64.b64decode(seen["headers"]["kalshi-access-signature"]), message)

    def test_public_request_sends_no_auth_headers(self):
        seen = {}

        def handler(request):
            seen["headers"] = request.headers
            return httpx.Response(200, json={})

        make_client(handler).request("GET", "/exchange/status")
        assert "kalshi-access-key" not in seen["headers"]

    def test_signed_request_without_credentials_fails(self):
        with pytest.raises(CredentialError):
            make_client(lambda request: httpx.Response(200, json={})).request("GET", "/portfolio/balance", auth=True)

    def test_get_retries_server_errors_then_succeeds(self):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

        assert make_client(handler).request("GET", "/exchange/status") == {"ok": True}
        assert len(calls) == 3

    def test_http_error_carries_status_and_detail(self):
        client = make_client(lambda request: httpx.Response(400, json={"error": {"code": "bad", "message": "nope"}}))
        with pytest.raises(ClientError, match="HTTP 400: bad: nope"):
            client.request("GET", "/markets/X")

    def test_create_order_is_never_retried(self, ed_pem):
        calls = []

        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(503)

        client = make_client(handler, Signer("k", ed_pem))
        with pytest.raises(ClientError, match="HTTP 503"):
            client.create_order({"ticker": "T"})
        assert len(calls) == 1

    def test_cancel_is_never_retried_and_sends_market_ticker(self, ed_pem):
        seen = []

        def handler(request):
            seen.append((request.method, str(request.url)))
            return httpx.Response(503)

        client = make_client(handler, Signer("k", ed_pem))
        with pytest.raises(ClientError):
            client.cancel_order("abc", "T-1")
        assert seen == [("DELETE", "https://external-api.demo.kalshi.co/trade-api/v2/portfolio/events/orders/abc?market_ticker=T-1")]

    def test_pagination_follows_cursor_and_stops_at_limit(self):
        pages = {None: ({"markets": [{"n": 1}, {"n": 2}], "cursor": "c1"}), "c1": ({"markets": [{"n": 3}, {"n": 4}], "cursor": ""})}

        def handler(request):
            return httpx.Response(200, json=pages[request.url.params.get("cursor")])

        client = make_client(handler)
        assert [m["n"] for m in client.list_markets(limit=10)] == [1, 2, 3, 4]
        assert [m["n"] for m in client.list_markets(limit=3)] == [1, 2, 3]

    def test_current_market_is_the_open_one_closing_first(self):
        markets = [
            {"ticker": "later", "open_time": iso(-10), "close_time": iso(900)},
            {"ticker": "now", "open_time": iso(-10), "close_time": iso(300)},
            {"ticker": "future", "open_time": iso(300), "close_time": iso(1200)},
            {"ticker": "past", "open_time": iso(-900), "close_time": iso(-5)},
        ]
        client = make_client(lambda request: httpx.Response(200, json={"markets": markets, "cursor": ""}))
        assert client.current_market("KXBTC15M")["ticker"] == "now"

    def test_current_market_fails_when_none_open(self):
        client = make_client(lambda request: httpx.Response(200, json={"markets": [], "cursor": ""}))
        with pytest.raises(ClientError, match="No market is open"):
            client.current_market("KXBTC15M")


class TestResponseHandling:
    @pytest.mark.parametrize("ticker", ["", "..", "../exchange/status", "a/b", "a?x=1", "a b"])
    def test_ids_that_would_rewrite_the_path_are_rejected_before_any_request(self, ticker):
        client = make_client(lambda request: pytest.fail("no request expected"))
        with pytest.raises(ClientError, match="Invalid ticker"):
            client.get_market(ticker)
        with pytest.raises(ClientError, match="Invalid order ID"):
            client.get_order(ticker)

    def test_cancel_rejects_a_path_changing_order_id(self, ed_pem):
        client = make_client(lambda request: pytest.fail("no request expected"), Signer("k", ed_pem))
        with pytest.raises(ClientError, match="Invalid order ID"):
            client.cancel_order("o1/../../balance", "T")

    @pytest.mark.parametrize("status", [301, 302, 307])
    def test_redirects_are_errors(self, status):
        client = make_client(lambda request: httpx.Response(status, headers={"location": "/x"}))
        with pytest.raises(ClientError, match=f"HTTP {status}"):
            client.request("GET", "/markets/X")

    @pytest.mark.parametrize("content", [b"[]", b"null", b"<html>", b"3"])
    def test_non_object_json_is_an_explicit_error(self, content):
        client = make_client(lambda request: httpx.Response(200, content=content))
        with pytest.raises(ClientError, match="/markets/X returned"):
            client.request("GET", "/markets/X")

    def test_missing_response_field_names_the_endpoint(self):
        client = make_client(lambda request: httpx.Response(200, json={}))
        with pytest.raises(ClientError, match="/markets/X response has no 'market' field"):
            client.get_market("X")
        with pytest.raises(ClientError, match="no 'markets' field"):
            client.list_markets()

    def test_html_error_body_is_collapsed_to_one_short_line(self):
        client = make_client(lambda request: httpx.Response(414, text="<html>\n<body>\n" + "x" * 5000))
        with pytest.raises(ClientError) as raised:
            client.request("GET", "/markets/X")
        assert "\n" not in str(raised.value) and len(str(raised.value)) < 260

    def test_cursor_that_does_not_advance_fails_instead_of_looping(self):
        client = make_client(lambda request: httpx.Response(200, json={"markets": [{"n": 1}], "cursor": "same"}))
        with pytest.raises(ClientError, match="does not advance"):
            client.list_markets(limit=100)
        empty = make_client(lambda request: httpx.Response(200, json={"markets": [], "cursor": "next"}))
        with pytest.raises(ClientError, match="does not advance"):
            empty.list_markets(limit=100)

    @pytest.mark.parametrize("header", ["-1", "nan", "inf", "abc"])
    def test_unusable_retry_after_falls_back_to_exponential_delay(self, header):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(429, headers={"Retry-After": header}) if len(calls) == 1 else httpx.Response(200, json={})

        client = make_client(handler, max_delay=0.01)
        assert client.request("GET", "/exchange/status") == {}
        assert len(calls) == 2

    def test_local_protocol_error_is_not_retried_as_a_network_error(self):
        calls = []

        def handler(request):
            calls.append(1)
            raise httpx.LocalProtocolError("Illegal header value")

        with pytest.raises(ClientError, match="malformed"):
            make_client(handler).request("GET", "/exchange/status")
        assert calls == [1]


class TestOrderNumbers:
    def test_count_is_serialized_without_trailing_zeros(self):
        assert build_order_body("T", "yes", "1.500", "0.5")["count"] == "1.5"
        assert build_order_body("T", "yes", "1000", "0.5")["count"] == "1000"

    @pytest.mark.parametrize("count,price", [("٣", "0.5"), ("1", "٠.٥")])
    def test_non_ascii_digits_are_rejected(self, count, price):
        with pytest.raises(ClientError, match="plain decimal"):
            build_order_body("T", "yes", count, price)
