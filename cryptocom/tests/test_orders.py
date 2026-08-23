"""Offline tests for cryptocom order commands (mocked transport, no network)."""
import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner
from cli_tools_shared.exceptions import ClientError

from cryptocom_cli.client import CryptocomClient
from cryptocom_cli.commands import orders


class StubConfig:
    """Config stub so client signing runs offline without credentials."""

    base_url = "https://api.crypto.com/exchange/v1"
    api_key = "test-api-key"
    api_secret = "test-api-secret"

    def has_credentials(self):
        return True

    def get_missing_credentials(self):
        return []


def make_client():
    return CryptocomClient(config=StubConfig())


def make_response(envelope, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = {}
    response.json.return_value = envelope
    return response


def patch_transport(monkeypatch, client, envelopes):
    """Patch requests.request to replay canned envelopes and capture bodies."""
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "json": kwargs.get("json")})
        envelope = envelopes.pop(0) if len(envelopes) > 1 else envelopes[0]
        return make_response(envelope)

    monkeypatch.setattr("cryptocom_cli.client.requests.request", fake_request)
    return calls


ENVELOPE_OK = lambda result: {"code": 0, "method": "private/x", "result": result}


# --- client-level: param assembly and signature method names ---


def test_create_order_sends_signed_private_create_order(monkeypatch):
    client = make_client()
    calls = patch_transport(
        monkeypatch,
        client,
        [ENVELOPE_OK({"order_id": "ORDER-1"})],
    )

    result = client.create_order(
        instrument_name="SOL_USD",
        side="BUY",
        quantity="0.1",
        order_type="LIMIT",
        limit_price="96.50",
        time_in_force="IMMEDIATE_OR_CANCEL",
    )

    assert result == {"order_id": "ORDER-1"}
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/private/create-order")

    body = call["json"]
    assert body["method"] == "private/create-order"
    assert body["params"] == {
        "instrument_name": "SOL_USD",
        "side": "BUY",
        "type": "LIMIT",
        "quantity": "0.1",
        "price": "96.50",
        "time_in_force": "IMMEDIATE_OR_CANCEL",
    }
    expected_sig = client._signature(
        body["method"], body["id"], body["params"], body["nonce"]
    )
    assert body["sig"] == expected_sig


def test_create_order_market_omits_limit_price_and_tif(monkeypatch):
    client = make_client()
    calls = patch_transport(
        monkeypatch,
        client,
        [ENVELOPE_OK({"order_id": "ORDER-2"})],
    )

    client.create_order(
        instrument_name="BTC_USD",
        side="SELL",
        quantity="0.01",
        order_type="MARKET",
    )

    params = calls[0]["json"]["params"]
    assert params["type"] == "MARKET"
    assert "price" not in params
    assert "time_in_force" not in params


def test_create_order_limit_requires_price():
    client = make_client()
    with pytest.raises(ClientError, match="Limit orders require a limit price"):
        client.create_order(
            instrument_name="SOL_USD", side="BUY", quantity="0.1", order_type="LIMIT"
        )


def test_create_order_rejects_price_for_market():
    client = make_client()
    with pytest.raises(ClientError, match="only valid for LIMIT"):
        client.create_order(
            instrument_name="SOL_USD",
            side="BUY",
            quantity="0.1",
            order_type="MARKET",
            limit_price="96.50",
        )


def test_get_order_detail_uses_singular_method_name(monkeypatch):
    client = make_client()
    calls = patch_transport(
        monkeypatch,
        client,
        [
            ENVELOPE_OK(
                {
                    "account_id": "ACC-1",
                    "order_id": "ORDER-3",
                    "instrument_name": "SOL_USD",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "status": "FILLED",
                }
            )
        ],
    )

    order = client.get_order_detail("ORDER-3")

    assert calls[0]["json"]["method"] == "private/get-order-detail"
    assert calls[0]["json"]["params"] == {"order_id": "ORDER-3"}
    assert order.order_id == "ORDER-3"
    assert order.status.value == "FILLED"


def test_cancel_order_uses_private_cancel_order(monkeypatch):
    client = make_client()
    calls = patch_transport(
        monkeypatch,
        client,
        [ENVELOPE_OK({"order_id": "ORDER-4"})],
    )

    result = client.cancel_order("ORDER-4")

    assert calls[0]["json"]["method"] == "private/cancel-order"
    assert calls[0]["json"]["params"] == {"order_id": "ORDER-4"}
    assert result == {"order_id": "ORDER-4"}


def test_venue_error_payload_raises_clean_client_error(monkeypatch):
    client = make_client()
    patch_transport(
        monkeypatch,
        client,
        [{"code": 20004, "message": "ORDER_NOT_FOUND"}],
    )

    with pytest.raises(ClientError) as excinfo:
        client.cancel_order("BOGUS-ID")
    assert "20004" in str(excinfo.value)
    assert "ORDER_NOT_FOUND" in str(excinfo.value)


def test_missing_credentials_fail_before_signing():
    config = StubConfig()
    config.has_credentials = lambda: False
    config.get_missing_credentials = lambda: ["API_KEY"]
    client = CryptocomClient(config=config)
    with pytest.raises(ClientError, match="Missing credentials: API_KEY"):
        client.create_order(
            instrument_name="SOL_USD", side="BUY", quantity="0.1", limit_price="96.50"
        )


# --- CLI-level: command surface, streams, exit codes ---


def test_orders_create_prints_order_json_to_stdout_only(monkeypatch):
    client = MagicMock()
    client.create_order.return_value = {"order_id": "ORDER-5"}
    monkeypatch.setattr(orders, "get_client", lambda: client)

    result = CliRunner().invoke(
        orders.app,
        [
            "create",
            "--symbol",
            "sol_usd",
            "--side",
            "buy",
            "--price",
            "96.50",
            "--quantity",
            "0.1",
            "--tif",
            "IOC",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"order_id": "ORDER-5"}
    client.create_order.assert_called_once_with(
        instrument_name="SOL_USD",
        side="BUY",
        quantity="0.1",
        order_type="LIMIT",
        limit_price="96.50",
        time_in_force="IMMEDIATE_OR_CANCEL",
        client_oid=None,
    )


def test_orders_create_maps_gtc_alias_and_rejects_bad_decimal(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(orders, "get_client", lambda: client)

    result = CliRunner().invoke(
        orders.app,
        ["create", "--symbol", "SOL_USD", "--side", "sell", "--price", "2.5", "--quantity", "-1"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Quantity must be positive" in result.stderr
    client.create_order.assert_not_called()


def test_orders_create_invalid_tif_is_clean_cli_error(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(orders, "get_client", lambda: client)

    result = CliRunner().invoke(
        orders.app,
        [
            "create",
            "--symbol",
            "SOL_USD",
            "--side",
            "buy",
            "--price",
            "96.50",
            "--quantity",
            "0.1",
            "--tif",
            "WHENEVER",
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Invalid time in force" in result.stderr


def test_orders_details_venue_error_exits_one_with_message_on_stderr(monkeypatch):
    client = MagicMock()
    client.get_order_detail.side_effect = ClientError(
        "private/get-order-detail failed with code 20004: ORDER_NOT_FOUND"
    )
    monkeypatch.setattr(orders, "get_client", lambda: client)

    result = CliRunner().invoke(orders.app, ["details", "BOGUS-ID"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "20004" in result.stderr
    assert "ORDER_NOT_FOUND" in result.stderr


def test_orders_cancel_prints_result_json(monkeypatch):
    client = MagicMock()
    client.cancel_order.return_value = {"order_id": "ORDER-6"}
    monkeypatch.setattr(orders, "get_client", lambda: client)

    result = CliRunner().invoke(orders.app, ["cancel", "ORDER-6"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"order_id": "ORDER-6"}
    client.cancel_order.assert_called_once_with("ORDER-6")


def test_orders_list_reuses_open_orders_machinery(monkeypatch):
    from cryptocom_cli.models import OpenOrder

    client = MagicMock()
    client.list_open_orders.return_value = [
        OpenOrder(
            account_id="ACC-1",
            order_id="ORDER-7",
            instrument_name="SOL_USD",
            status="NEW",
        )
    ]
    monkeypatch.setattr(orders, "get_client", lambda: client)

    result = CliRunner().invoke(
        orders.app, ["list", "--instrument-name", "SOL_USD", "--properties", "order_id,status"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"order_id": "ORDER-7", "status": "NEW"}]
    client.list_open_orders.assert_called_once_with(
        instrument_name="SOL_USD", limit=100, filters=None
    )
