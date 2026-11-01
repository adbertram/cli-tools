import asyncio
import json
import time

import httpx
import pytest
from cli_tools_shared.exceptions import ClientError
from websockets.asyncio.server import serve

from kalshi_cli.client import KalshiClient
from kalshi_cli.signing import Signer
from kalshi_cli.stream import MarketState, market_view, read_state, stream_market, write_state
from test_client import iso

PRESET = {"reference_index": "BRTI", "yes_label": "up", "no_label": "down"}


def now_ms() -> int:
    return int(time.time() * 1000)


def market(ticker="M-1", **overrides):
    base = {
        "ticker": ticker,
        "close_time": iso(600),
        "open_time": iso(-300),
        "floor_strike": 77789.11,
        "yes_bid_dollars": "0.2200",
        "yes_bid_size_fp": "100.00",
        "yes_ask_dollars": "0.2300",
        "yes_ask_size_fp": "40.00",
        "last_price_dollars": "0.2200",
        "volume_fp": "5.00",
        "open_interest_fp": "9.00",
    }
    return {**base, **overrides}


def ticker_message(ticker="M-1", **body):
    msg = {
        "market_ticker": ticker,
        "yes_bid_dollars": "0.3000",
        "yes_ask_dollars": "0.3100",
        "yes_bid_size_fp": "10.00",
        "yes_ask_size_fp": "20.00",
        "price_dollars": "0.3000",
        "volume_fp": "6.00",
        "open_interest_fp": "10.00",
    }
    return {"type": "ticker", "sid": 1, "msg": {**msg, **body}}


def reference_message(value="78000.50", ts=1700000000000):
    return {"type": "cfbenchmarks_value_5hz", "sid": 2, "msg": {"index_id": "BRTI", "value_usd": value, "source_ts_ms": ts}}


class TestMarketView:
    def test_no_side_is_derived_from_yes(self):
        view = market_view(market(), None, PRESET)
        assert view["no_bid"] == "0.7700" and view["no_ask"] == "0.7800"
        assert view["no_bid_size"] == "40.00" and view["no_ask_size"] == "100.00"
        assert view["yes_label"] == "up" and view["no_label"] == "down"

    def test_quote_is_null_when_no_size_rests(self):
        view = market_view(market(yes_ask_size_fp="0.00"), None, PRESET)
        assert view["yes_ask"] is None and view["yes_ask_size"] is None
        assert view["no_bid"] is None

    def test_delta_and_seconds_left(self):
        view = market_view(market(), {"value": "77800.11", "ts_ms": 5}, PRESET)
        assert view["delta"] == "11.00" and view["reference_price"] == "77800.11"
        assert 590 < view["seconds_left"] <= 600

    def test_no_reference_means_no_delta(self):
        assert market_view(market(), None, PRESET)["delta"] is None


class TestMarketState:
    def test_not_ready_until_reference_arrives(self):
        state = MarketState(market(), PRESET)
        assert not state.ready
        assert state.apply(reference_message()) == "reference"
        assert state.ready

    def test_without_reference_index_it_is_ready_immediately(self):
        assert MarketState(market(), {}).ready

    def test_ticker_message_updates_quotes(self):
        state = MarketState(market(), PRESET)
        assert state.apply(ticker_message()) == "ticker"
        assert state.view()["yes_bid"] == "0.3000" and state.view()["last_price"] == "0.3000"

    def test_other_market_and_other_index_are_ignored(self):
        state = MarketState(market(), PRESET)
        assert state.apply(ticker_message("OTHER")) is None
        assert state.apply({"type": "cfbenchmarks_value_5hz", "msg": {"index_id": "ETH", "value_usd": "1", "source_ts_ms": 1}}) is None
        assert state.reference is None

    def test_subscribed_records_sid(self):
        state = MarketState(market(), PRESET)
        state.apply({"type": "subscribed", "msg": {"channel": "ticker", "sid": 7}})
        assert state.sids == {"ticker": 7}

    @pytest.mark.parametrize(
        "message,expected",
        [
            ([], "Unexpected Kalshi WebSocket frame"),
            ({"type": "ticker", "msg": []}, "Unexpected Kalshi WebSocket frame"),
            ({"type": "ticker", "msg": {}}, "missing field"),
            ({"type": "subscribed", "msg": {"channel": "ticker"}}, "missing field 'sid'"),
            ({"type": "ticker", "msg": {"market_ticker": "M-1"}}, "missing field 'yes_bid_dollars'"),
        ],
    )
    def test_malformed_frames_fail_explicitly(self, message, expected):
        with pytest.raises(ClientError, match=expected):
            MarketState(market(), PRESET).apply(message)

    def test_error_message_fails_explicitly(self):
        with pytest.raises(ClientError, match="WebSocket error 6: bad"):
            MarketState(market(), PRESET).apply({"type": "error", "msg": {"code": 6, "msg": "bad"}})


class TestStateFile:
    def test_fresh_state_is_returned(self, tmp_path):
        path = tmp_path / "s" / "state.json"
        write_state(path, {"ticker": "M-1", "reference_price": "1"}, now_ms())
        assert read_state(path, 5)["ticker"] == "M-1"

    def test_stale_state_is_ignored(self, tmp_path):
        path = tmp_path / "state.json"
        write_state(path, {"ticker": "M-1"}, now_ms())
        time.sleep(0.05)
        assert read_state(path, 0.01) is None

    def test_missing_state_is_none(self, tmp_path):
        assert read_state(tmp_path / "none.json", 5) is None

    def test_stale_reference_makes_the_state_unusable_even_when_the_file_is_fresh(self, tmp_path):
        path = tmp_path / "state.json"
        write_state(path, {"ticker": "M-1"}, now_ms() - 60_000)
        assert read_state(path, 5) is None

    def test_state_without_a_reference_is_unusable(self, tmp_path):
        path = tmp_path / "state.json"
        write_state(path, {"ticker": "M-1"}, None)
        assert read_state(path, 5) is None

    def test_future_dated_state_is_unusable(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_bytes(json.dumps({"ticker": "M-1", "written_ms": now_ms() + 3_600_000, "reference_received_ms": now_ms()}).encode())
        assert read_state(path, 5) is None

    @pytest.mark.parametrize(
        "content",
        [b"{not json", b"", b"[]", b"null", b'{"written_ms":"abc","reference_received_ms":1}', b'{"ticker":"X"}', b"\xff\xfe\x00"],
    )
    def test_corrupt_state_means_no_live_stream(self, tmp_path, content):
        path = tmp_path / "state.json"
        path.write_bytes(content)
        assert read_state(path, 5) is None

    def test_nan_max_age_never_makes_a_stale_state_fresh(self, tmp_path):
        path = tmp_path / "state.json"
        write_state(path, {"ticker": "M-1"}, now_ms() - 3_600_000)
        assert read_state(path, float("nan")) is None

    def test_unreadable_state_is_an_explicit_error_naming_the_file(self, tmp_path):
        path = tmp_path / "state.json"
        write_state(path, {"ticker": "M-1"}, now_ms())
        path.chmod(0)
        try:
            with pytest.raises(ClientError, match="Cannot read stream state"):
                read_state(path, 5)
        finally:
            path.chmod(0o600)

    def test_concurrent_writers_do_not_collide(self, tmp_path):
        import threading

        path = tmp_path / "state.json"
        errors = []

        def writer():
            try:
                for _ in range(300):
                    write_state(path, {"ticker": "M-1"}, now_ms())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert list(tmp_path.glob("*.tmp")) == []


class FakeExchange:
    """Local WebSocket server standing in for Kalshi: records what the client sends."""

    def __init__(self, script):
        self.script = script
        self.headers = None
        self.commands = []

    async def handler(self, ws):
        self.headers = ws.request.headers
        await self.script(self, ws)


async def run_stream(exchange, markets_handler, **kwargs):
    async with serve(exchange.handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        client = KalshiClient(env="demo", signer=kwargs.pop("signer"), transport=httpx.MockTransport(markets_handler), base_delay=0)
        client.ws_url = f"ws://127.0.0.1:{port}/trade-api/ws/v2"
        updates = []
        await asyncio.wait_for(
            stream_market(client, "KXBTC15M", PRESET, lambda view: updates.append(view) or (len(updates) >= kwargs.get("stop_after", 2)), duration=10),
            timeout=15,
        )
        return updates


def test_stream_signs_handshake_subscribes_and_emits_updates(ed_pem):
    async def script(exchange, ws):
        for _ in range(2):
            exchange.commands.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"id": 1, "type": "subscribed", "msg": {"channel": "ticker", "sid": 1}}))
        await ws.send(json.dumps(ticker_message()))
        await ws.send(json.dumps(reference_message()))
        await ws.send(json.dumps(ticker_message(yes_bid_dollars="0.3500")))
        await asyncio.sleep(1)

    exchange = FakeExchange(script)
    markets = [market()]
    updates = asyncio.run(run_stream(exchange, lambda request: httpx.Response(200, json={"markets": markets, "cursor": ""}), signer=Signer("key-9", ed_pem)))

    assert exchange.headers["KALSHI-ACCESS-KEY"] == "key-9"
    assert exchange.headers["KALSHI-ACCESS-SIGNATURE"] and exchange.headers["KALSHI-ACCESS-TIMESTAMP"]
    channels = {tuple(command["params"]["channels"]): command["params"] for command in exchange.commands}
    assert channels[("ticker",)]["market_tickers"] == ["M-1"]
    assert channels[("cfbenchmarks_value_5hz",)]["index_ids"] == ["BRTI"]
    # Nothing is emitted before the reference price is known.
    assert [update["event"] for update in updates] == ["reference", "ticker"]
    assert updates[0]["reference_price"] == "78000.50" and updates[0]["yes_bid"] == "0.3000"
    assert updates[1]["yes_bid"] == "0.3500"


def test_stream_rolls_the_subscription_to_the_next_market(ed_pem):
    first = market("M-1", close_time=iso(0.4))
    second = market("M-2", open_time=iso(0), close_time=iso(900))
    calls = []

    def markets_handler(request):
        calls.append(1)
        return httpx.Response(200, json={"markets": [first] if len(calls) == 1 else [second], "cursor": ""})

    async def script(exchange, ws):
        for _ in range(2):
            exchange.commands.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"id": 1, "type": "subscribed", "msg": {"channel": "ticker", "sid": 4}}))
        await ws.send(json.dumps(reference_message()))
        for _ in range(2):
            exchange.commands.append(json.loads(await ws.recv()))
        await ws.send(json.dumps(ticker_message("M-2", yes_bid_dollars="0.6000")))
        await asyncio.sleep(1)

    exchange = FakeExchange(script)
    updates = asyncio.run(run_stream(exchange, markets_handler, signer=Signer("k", ed_pem), stop_after=3))

    updates_cmds = [c for c in exchange.commands if c["cmd"] == "update_subscription"]
    assert [(c["params"]["action"], c["params"]["market_tickers"], c["params"]["sid"]) for c in updates_cmds] == [
        ("add_markets", ["M-2"], 4),
        ("delete_markets", ["M-1"], 4),
    ]
    assert [update["event"] for update in updates] == ["reference", "rollover", "ticker"]
    assert updates[-1]["ticker"] == "M-2" and updates[-1]["yes_bid"] == "0.6000"


def test_stream_handshake_rejection_fails_explicitly(ed_pem):
    async def reject(connection, request):
        return connection.respond(401, "token_authentication_failure")

    async def main():
        async with serve(lambda ws: None, "127.0.0.1", 0, process_request=reject) as server:
            port = server.sockets[0].getsockname()[1]
            client = KalshiClient(
                env="demo",
                signer=Signer("k", ed_pem),
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"markets": [market()], "cursor": ""})),
            )
            client.ws_url = f"ws://127.0.0.1:{port}/trade-api/ws/v2"
            await stream_market(client, "KXBTC15M", PRESET, lambda view: False, duration=5)

    with pytest.raises(ClientError, match="handshake rejected: HTTP 401"):
        asyncio.run(main())


def test_watch_command_prints_json_lines_stops_at_count_and_removes_state(ed_pem, monkeypatch, tmp_path):
    import threading

    from typer.testing import CliRunner

    from kalshi_cli.main import app

    ready = threading.Event()
    info = {}

    async def script(exchange, ws):
        for _ in range(2):
            await ws.recv()
        await ws.send(json.dumps(reference_message()))
        await ws.send(json.dumps(ticker_message()))
        await asyncio.sleep(2)

    async def serve_forever():
        exchange = FakeExchange(script)
        async with serve(exchange.handler, "127.0.0.1", 0) as server:
            info["port"] = server.sockets[0].getsockname()[1]
            info["loop"] = asyncio.get_running_loop()
            info["stop"] = asyncio.Event()
            ready.set()
            await info["stop"].wait()

    thread = threading.Thread(target=lambda: asyncio.run(serve_forever()), daemon=True)
    thread.start()
    assert ready.wait(5)

    def fake_open_client(env, demo, auth=False):
        client = KalshiClient(
            env="demo",
            signer=Signer("k", ed_pem),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"markets": [market()], "cursor": ""})),
        )
        client.ws_url = f"ws://127.0.0.1:{info['port']}/trade-api/ws/v2"
        return client

    state_file = tmp_path / "state.json"
    monkeypatch.setattr("kalshi_cli.commands.stream.open_client", fake_open_client)
    monkeypatch.setattr("kalshi_cli.commands.stream.state_path", lambda env, series: state_file)
    try:
        result = CliRunner().invoke(app, ["stream", "watch", "btc15m", "--count", "2", "--demo"])
    finally:
        info["loop"].call_soon_threadsafe(info["stop"].set)
        thread.join(5)

    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in result.output.strip().splitlines()]
    assert [line["event"] for line in lines] == ["reference", "ticker"]
    assert lines[1]["reference_price"] == "78000.50" and lines[1]["yes_bid"] == "0.3000"
    assert not state_file.exists()


def _client(port, ed_pem, markets_handler=None):
    handler = markets_handler or (lambda request: httpx.Response(200, json={"markets": [market()], "cursor": ""}))
    client = KalshiClient(env="demo", signer=Signer("k", ed_pem), transport=httpx.MockTransport(handler), base_delay=0)
    client.ws_url = f"ws://127.0.0.1:{port}/trade-api/ws/v2"
    return client


def test_clean_server_close_backs_off_instead_of_reconnecting_in_a_tight_loop(ed_pem, monkeypatch):
    monkeypatch.setattr("kalshi_cli.stream.RECONNECT_BASE_DELAY", 0.05)
    connections = []

    async def handler(ws):
        connections.append(time.monotonic())
        await ws.close(1000)

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            client = _client(server.sockets[0].getsockname()[1], ed_pem)
            with pytest.raises(ClientError, match="connection lost"):
                await stream_market(client, "KXBTC15M", PRESET, lambda view: False, duration=20)

    asyncio.run(main())
    gaps = [b - a for a, b in zip(connections, connections[1:])]
    assert len(connections) == 6  # MAX_CONSECUTIVE_FAILURES + 1 attempts, then explicit failure
    assert gaps[0] >= 0.04 and gaps[-1] > gaps[0] * 4  # exponential growth


def test_a_healthy_session_resets_the_failure_counter(ed_pem, monkeypatch):
    monkeypatch.setattr("kalshi_cli.stream.RECONNECT_BASE_DELAY", 0.01)
    monkeypatch.setattr("kalshi_cli.stream.HEALTHY_SESSION_SECONDS", 0.2)
    sessions = []

    async def handler(ws):
        sessions.append(1)
        if len(sessions) % 2 == 0:
            await asyncio.sleep(0.3)  # healthy: stays up past the threshold
        await ws.close(1011)

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            client = _client(server.sockets[0].getsockname()[1], ed_pem)
            await stream_market(client, "KXBTC15M", PRESET, lambda view: False, duration=4)

    asyncio.run(main())
    # Alternating healthy and short sessions never accumulates 6 failures, so the watcher
    # keeps reconnecting until the duration ends instead of failing.
    assert len(sessions) > 8


def test_retryable_handshake_status_is_retried_and_other_statuses_are_not(ed_pem, monkeypatch):
    monkeypatch.setattr("kalshi_cli.stream.RECONNECT_BASE_DELAY", 0.01)
    attempts = []

    async def reject(connection, request):
        attempts.append(1)
        return connection.respond(503 if len(attempts) < 3 else 403, "no")

    async def main():
        async with serve(lambda ws: None, "127.0.0.1", 0, process_request=reject) as server:
            client = _client(server.sockets[0].getsockname()[1], ed_pem)
            await stream_market(client, "KXBTC15M", PRESET, lambda view: False, duration=10)

    with pytest.raises(ClientError, match="HTTP 403"):
        asyncio.run(main())
    assert len(attempts) == 3


def test_output_failures_are_not_reported_as_connection_loss(ed_pem):
    async def script(exchange, ws):
        for _ in range(2):
            await ws.recv()
        await ws.send(json.dumps(reference_message()))
        await asyncio.sleep(2)

    def broken_pipe(view):
        raise BrokenPipeError(32, "Broken pipe")

    with pytest.raises(ClientError, match="Cannot write stream output: .*Broken pipe"):
        asyncio.run(_run_with(script, ed_pem, broken_pipe))


def test_unwritable_state_file_is_an_explicit_output_error(ed_pem, tmp_path):
    async def script(exchange, ws):
        for _ in range(2):
            await ws.recv()
        await ws.send(json.dumps(reference_message()))
        await asyncio.sleep(2)

    blocked = tmp_path / "file"
    blocked.write_text("x")
    with pytest.raises(ClientError, match="Cannot write stream output"):
        asyncio.run(_run_with(script, ed_pem, lambda view: False, path=blocked / "state.json"))


def test_no_update_is_emitted_after_the_stop_condition(ed_pem):
    async def script(exchange, ws):
        for _ in range(2):
            await ws.recv()
        for message in (reference_message(), ticker_message(), ticker_message(yes_bid_dollars="0.4000"), ticker_message(yes_bid_dollars="0.5000")):
            await ws.send(json.dumps(message))
        await asyncio.sleep(1)

    seen = []
    asyncio.run(_run_with(script, ed_pem, lambda view: seen.append(view) or True))
    assert len(seen) == 1


def test_rollover_keeps_waiting_when_no_market_is_open_yet(ed_pem, monkeypatch):
    monkeypatch.setattr("kalshi_cli.stream.ROLLOVER_POLL_SECONDS", 0.05)
    first = market("M-1", close_time=iso(0.2))
    second = market("M-2", open_time=iso(0), close_time=iso(900))
    calls = []

    def markets_handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={"markets": [first], "cursor": ""})
        if len(calls) < 6:
            return httpx.Response(200, json={"markets": [], "cursor": ""})  # gap: nothing open
        return httpx.Response(200, json={"markets": [second], "cursor": ""})

    async def script(exchange, ws):
        for _ in range(2):
            await ws.recv()
        await ws.send(json.dumps({"id": 1, "type": "subscribed", "msg": {"channel": "ticker", "sid": 4}}))
        await ws.send(json.dumps(reference_message()))
        for _ in range(2):
            exchange.commands.append(json.loads(await ws.recv()))
        await asyncio.sleep(1)

    exchange = FakeExchange(script)
    seen = []

    async def main():
        async with serve(exchange.handler, "127.0.0.1", 0) as server:
            client = _client(server.sockets[0].getsockname()[1], ed_pem, markets_handler)
            await stream_market(client, "KXBTC15M", PRESET, lambda view: seen.append(view["event"]) or view["event"] == "rollover", duration=15)

    asyncio.run(main())
    assert seen == ["reference", "rollover"]
    assert [c["params"]["action"] for c in exchange.commands] == ["add_markets", "delete_markets"]


async def _run_with(script, ed_pem, on_update, path=None):
    exchange = FakeExchange(script)
    async with serve(exchange.handler, "127.0.0.1", 0) as server:
        client = _client(server.sockets[0].getsockname()[1], ed_pem)
        await asyncio.wait_for(stream_market(client, "KXBTC15M", PRESET, on_update, duration=10, path=path), timeout=15)


@pytest.mark.parametrize("content", [{"reference_price": "1"}, {"ticker": "M-1", "reference_price": {"a": 1}}, {"ticker": "M-1"}])
def test_state_without_usable_ticker_or_reference_price_means_no_live_stream(tmp_path, content):
    path = tmp_path / "state.json"
    path.write_bytes(json.dumps({**content, "written_ms": now_ms(), "reference_received_ms": now_ms()}).encode())
    assert read_state(path, 5) is None
