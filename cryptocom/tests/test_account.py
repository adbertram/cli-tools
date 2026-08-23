"""Offline tests for Crypto.com private account commands."""
import json
from unittest.mock import MagicMock

from typer.testing import CliRunner

from cryptocom_cli.client import CryptocomClient
from cryptocom_cli.commands import account


class StubConfig:
    """Config stub for account client tests."""

    base_url = "https://api.crypto.com/exchange/v1"
    api_key = "test-api-key"
    api_secret = "test-api-secret"

    def has_credentials(self):
        return True

    def get_missing_credentials(self):
        return []


def position_result():
    """Return a representative private/user-balance result."""
    return {
        "data": [
            {
                "instrument_name": "USD",
                "position_balances": [
                    {"instrument_name": "HBAR", "quantity": "13.93", "market_value": "1.10941306"},
                    {"instrument_name": "AAVE", "quantity": "0.1645875", "market_value": "23.15400491"},
                    {"instrument_name": "TRUMP", "quantity": "0", "market_value": "0"},
                    {"instrument_name": "CRO", "quantity": "-1", "market_value": "-0.1"},
                    {"instrument_name": "USD", "quantity": "73.830107", "market_value": "73.830107"},
                ],
            }
        ]
    }


def test_get_positions_uses_live_balance_shape_and_excludes_cash_and_nonpositive_rows():
    client = CryptocomClient(config=StubConfig())
    client._make_private_request = MagicMock(return_value=position_result())

    positions = client.get_positions()

    assert positions == [
        {"instrument_name": "HBAR", "quantity": "13.93", "market_value": "1.10941306"},
        {"instrument_name": "AAVE", "quantity": "0.1645875", "market_value": "23.15400491"},
    ]
    client._make_private_request.assert_called_once_with("private/user-balance", params={})


def test_get_positions_applies_standard_filter_before_limit():
    client = CryptocomClient(config=StubConfig())
    client._make_private_request = MagicMock(return_value=position_result())

    positions = client.get_positions(limit=1, filters=["market_value:gt:10"])

    assert positions == [
        {"instrument_name": "AAVE", "quantity": "0.1645875", "market_value": "23.15400491"}
    ]


def test_account_positions_emits_standard_json_and_forwards_list_options(monkeypatch):
    client = MagicMock()
    client.get_positions.return_value = [
        {"instrument_name": "AAVE", "quantity": "0.1645875", "market_value": "23.15400491"}
    ]
    monkeypatch.setattr(account, "get_client", lambda: client)

    result = CliRunner().invoke(
        account.app,
        [
            "positions",
            "--limit",
            "5",
            "--filter",
            "instrument_name:eq:AAVE",
            "--properties",
            "instrument_name,quantity,market_value",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {"instrument_name": "AAVE", "quantity": "0.1645875", "market_value": "23.15400491"}
    ]
    client.get_positions.assert_called_once_with(
        limit=5,
        filters=["instrument_name:eq:AAVE"],
    )


def test_account_positions_supports_table_output(monkeypatch):
    client = MagicMock()
    client.get_positions.return_value = [
        {"instrument_name": "HBAR", "quantity": "13.93", "market_value": "1.10941306"}
    ]
    monkeypatch.setattr(account, "get_client", lambda: client)

    result = CliRunner().invoke(account.app, ["positions", "--table"])

    assert result.exit_code == 0
    assert "instrument_name" in result.stdout
    assert "HBAR" in result.stdout
    assert "13.93" in result.stdout
    assert "1.10941306" in result.stdout
