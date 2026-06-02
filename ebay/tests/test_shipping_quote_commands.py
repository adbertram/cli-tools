"""Tests for shipping-quote CLI commands."""
import json
import pytest
from unittest.mock import patch, MagicMock

from ebay_cli.main import app

from .conftest import SAMPLE_QUOTE_RESPONSE


def _mock_client(mock_config):
    """Patch get_client and get_config for shipping commands."""
    client = MagicMock()
    config_patch = patch("ebay_cli.commands.shipping.get_config", return_value=mock_config)
    client_patch = patch("ebay_cli.commands.shipping.get_client", return_value=client)
    return client, config_patch, client_patch


class TestShippingQuoteCreate:
    def test_json_output(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-quote", "create",
                "--order-id", "04-08365-42542",
                "--to-name", "Jane Smith",
                "--to-street", "456 Oak Ave",
                "--to-city", "Newark",
                "--to-state", "NJ",
                "--to-zip", "07101",
                "--weight", "2",
                "--length", "10", "--width", "8", "--height", "4",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["shippingQuoteId"] == "Q-test-001"
        assert len(data["rates"]) == 2

    def test_table_output(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-quote", "create",
                "--order-id", "04-08365-42542",
                "--to-name", "Jane Smith",
                "--to-street", "456 Oak Ave",
                "--to-city", "Newark",
                "--to-state", "NJ",
                "--to-zip", "07101",
                "--weight", "2",
                "--length", "10", "--width", "8", "--height", "4",
                "--table",
            ])

        assert result.exit_code == 0
        combined = result.output + result.stderr
        # Rich tables word-wrap, so check fragments
        assert "Ground" in combined
        assert "Priority" in combined
        assert "7.46" in combined
        assert "Q-test-001" in combined

    def test_payload_uses_correct_api_contract(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            runner.invoke(app, [
                "seller", "shipping-quote", "create",
                "--order-id", "04-08365-42542",
                "--to-name", "Jane Smith",
                "--to-street", "456 Oak Ave",
                "--to-city", "Newark",
                "--to-state", "NJ",
                "--to-zip", "07101",
                "--weight", "2",
                "--length", "10", "--width", "8", "--height", "4",
            ])

        payload = client.create_shipping_quote.call_args.args[0]

        # orders always included with channel
        assert payload["orders"] == [{"channel": "EBAY", "orderId": "04-08365-42542"}]

        # contactAddress, not address
        assert "contactAddress" in payload["shipFrom"]
        assert "contactAddress" in payload["shipTo"]

        # countryCode, not country
        assert "countryCode" in payload["shipTo"]["contactAddress"]

        # dimensions required
        assert "dimensions" in payload["packageSpecification"]
        assert payload["packageSpecification"]["dimensions"]["unit"] == "INCH"

    def test_uses_config_defaults_for_ship_from(self, runner, mock_config):
        """Verify ship-from defaults come from config (evaluated at import time)."""
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            runner.invoke(app, [
                "seller", "shipping-quote", "create",
                "--order-id", "X",
                "--to-name", "Buyer",
                "--to-street", "456 Ave",
                "--to-city", "NYC",
                "--to-state", "NY",
                "--to-zip", "10001",
                "--weight", "1",
                "--length", "6", "--width", "4", "--height", "2",
            ])

        # Config defaults are evaluated at module import, so they use the real config.
        # Just verify the ship-from address fields are present and populated.
        payload = client.create_shipping_quote.call_args.args[0]
        ship_from = payload["shipFrom"]
        assert "fullName" in ship_from
        assert ship_from["fullName"]  # non-empty
        assert "contactAddress" in ship_from
        assert ship_from["contactAddress"]["countryCode"] == "US"

    def test_phone_included_when_provided(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            runner.invoke(app, [
                "seller", "shipping-quote", "create",
                "--order-id", "X",
                "--to-name", "Buyer",
                "--to-street", "456 Ave",
                "--to-city", "NYC",
                "--to-state", "NY",
                "--to-zip", "10001",
                "--to-phone", "5559999999",
                "--weight", "1",
                "--length", "6", "--width", "4", "--height", "2",
            ])

        payload = client.create_shipping_quote.call_args.args[0]
        assert payload["shipTo"]["primaryPhone"]["phoneNumber"] == "5559999999"


