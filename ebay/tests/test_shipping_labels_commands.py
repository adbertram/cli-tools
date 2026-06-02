"""Tests for shipping-labels CLI commands."""
import json
import os
import pytest
from unittest.mock import patch, MagicMock

from ebay_cli.main import app

from .conftest import (
    SAMPLE_ORDER,
    SAMPLE_QUOTE_RESPONSE,
    SAMPLE_SHIPMENT_RESPONSE,
    SAMPLE_CANCELLED_SHIPMENT,
)


def _mock_client(mock_config):
    """Patch get_client and get_config so commands work without real credentials."""
    client = MagicMock()
    config_patch = patch("ebay_cli.commands.orders.get_config", return_value=mock_config)
    client_patch = patch("ebay_cli.commands.orders.get_client", return_value=client)
    return client, config_patch, client_patch


class TestShippingLabelsCreate:
    def test_dry_run_shows_rates(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = SAMPLE_ORDER
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-labels", "create", "04-08365-42542",
                "--weight", "2", "--length", "10", "--width", "8", "--height", "4",
                "--dry-run", "--no-interactive",
            ])

        assert result.exit_code == 0
        # stderr should show rates (table may word-wrap names)
        assert "Ground" in result.stderr
        assert "Advantage" in result.stderr
        assert "Priority" in result.stderr
        assert "$7.46" in result.stderr
        # stdout should have JSON with quote_id and rates
        data = json.loads(result.stdout)
        assert data["quote_id"] == "Q-test-001"
        assert len(data["rates"]) == 2

    def test_dry_run_with_service_filter(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = SAMPLE_ORDER
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-labels", "create", "04-08365-42542",
                "--weight", "2", "--length", "10", "--width", "8", "--height", "4",
                "--service", "Ground", "--dry-run", "--no-interactive",
            ])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        # Only Ground Advantage should remain
        assert len(data["rates"]) == 1
        assert data["rates"][0]["service"] == "Ground Advantage"

    def test_no_rates_exits_with_error(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = SAMPLE_ORDER
        client.create_shipping_quote.return_value = {
            "shippingQuoteId": "Q-empty",
            "rates": [],
        }

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-labels", "create", "04-08365-42542",
                "--weight", "2", "--length", "10", "--width", "8", "--height", "4",
                "--dry-run", "--no-interactive",
            ])

        assert result.exit_code == 1
        assert "No shipping rates" in result.stderr

    def test_service_filter_no_match_exits_with_error(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = SAMPLE_ORDER
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-labels", "create", "04-08365-42542",
                "--weight", "2", "--length", "10", "--width", "8", "--height", "4",
                "--service", "FedEx", "--dry-run", "--no-interactive",
            ])

        assert result.exit_code == 1
        assert "No shipping rates match" in result.stderr

    def test_non_interactive_purchase(self, runner, mock_config, tmp_path):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = SAMPLE_ORDER
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE
        client.create_from_shipping_quote.return_value = SAMPLE_SHIPMENT_RESPONSE
        client.download_label_file.return_value = b"%PDF-fake"

        out_path = str(tmp_path / "test_label.pdf")

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-labels", "create", "04-08365-42542",
                "--weight", "2", "--length", "10", "--width", "8", "--height", "4",
                "--no-interactive", "--out", out_path,
            ], input="y\n")  # Confirm purchase

        assert result.exit_code == 0
        # Verify purchase was made with cheapest rate
        client.create_from_shipping_quote.assert_called_once()
        call_kwargs = client.create_from_shipping_quote.call_args.kwargs
        assert call_kwargs["quote_id"] == "Q-test-001"
        assert call_kwargs["rate_id"] == "R-ground-001"

        # stdout contains confirmation prompt + JSON; extract just the JSON
        stdout = result.stdout
        json_start = stdout.index("{")
        data = json.loads(stdout[json_start:])
        assert data["shipment_id"] == "S-test-001"
        assert data["tracking_number"] == "9400111899223100012345"
        assert data["label_file"] == out_path

    def test_purchase_with_insurance(self, runner, mock_config, tmp_path):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = SAMPLE_ORDER
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE
        client.create_from_shipping_quote.return_value = SAMPLE_SHIPMENT_RESPONSE
        client.download_label_file.return_value = b"%PDF-fake"

        out_path = str(tmp_path / "label.pdf")

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-labels", "create", "04-08365-42542",
                "--weight", "2", "--length", "10", "--width", "8", "--height", "4",
                "--no-interactive", "--insurance", "--out", out_path,
            ], input="y\n")

        assert result.exit_code == 0
        call_kwargs = client.create_from_shipping_quote.call_args.kwargs
        options = call_kwargs["additional_options"]
        assert len(options) == 1
        assert options[0]["optionType"] == "SHIP_COVER_INSURANCE"

    def test_purchase_with_proof_of_delivery(self, runner, mock_config, tmp_path):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = SAMPLE_ORDER
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE
        client.create_from_shipping_quote.return_value = SAMPLE_SHIPMENT_RESPONSE
        client.download_label_file.return_value = b"%PDF-fake"

        out_path = str(tmp_path / "label.pdf")

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-labels", "create", "04-08365-42542",
                "--weight", "2", "--length", "10", "--width", "8", "--height", "4",
                "--no-interactive", "--proof-of-delivery", "--out", out_path,
            ], input="y\n")

        assert result.exit_code == 0
        call_kwargs = client.create_from_shipping_quote.call_args.kwargs
        options = call_kwargs["additional_options"]
        assert len(options) == 1
        assert options[0]["optionType"] == "PROOF_OF_DELIVERY"

    def test_purchase_declined(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = SAMPLE_ORDER
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-labels", "create", "04-08365-42542",
                "--weight", "2", "--length", "10", "--width", "8", "--height", "4",
                "--no-interactive",
            ], input="n\n")  # Decline purchase

        assert result.exit_code == 0
        client.create_from_shipping_quote.assert_not_called()
        assert "Cancelled" in result.stderr

    def test_quote_payload_structure(self, runner, mock_config):
        """Verify the exact payload sent to the Logistics API."""
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = SAMPLE_ORDER
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            runner.invoke(app, [
                "seller", "shipping-labels", "create", "04-08365-42542",
                "--weight", "2", "--length", "10", "--width", "8", "--height", "4",
                "--dry-run", "--no-interactive",
            ])

        payload = client.create_shipping_quote.call_args.args[0]

        # Verify orders use channel field
        assert payload["orders"] == [{"channel": "EBAY", "orderId": "04-08365-42542"}]

        # Verify contactAddress (not address)
        assert "contactAddress" in payload["shipFrom"]
        assert "contactAddress" in payload["shipTo"]
        assert "address" not in payload["shipFrom"]
        assert "address" not in payload["shipTo"]

        # Verify countryCode (not country)
        assert payload["shipFrom"]["contactAddress"]["countryCode"] == "US"
        assert payload["shipTo"]["contactAddress"]["countryCode"] == "US"

        # Verify dimensions included
        assert "dimensions" in payload["packageSpecification"]

        # Verify weight values are strings
        assert payload["packageSpecification"]["weight"]["value"] == "2.0"

    def test_ship_to_address_from_order(self, runner, mock_config):
        """Verify ship-to address is populated from the order."""
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = SAMPLE_ORDER
        client.create_shipping_quote.return_value = SAMPLE_QUOTE_RESPONSE

        with cfg_p, cli_p:
            runner.invoke(app, [
                "seller", "shipping-labels", "create", "04-08365-42542",
                "--weight", "2", "--length", "10", "--width", "8", "--height", "4",
                "--dry-run", "--no-interactive",
            ])

        payload = client.create_shipping_quote.call_args.args[0]
        ship_to = payload["shipTo"]
        assert ship_to["fullName"] == "Jane Buyer"
        assert ship_to["contactAddress"]["addressLine1"] == "456 Oak Ave"
        assert ship_to["contactAddress"]["city"] == "Newark"
        assert ship_to["contactAddress"]["stateOrProvince"] == "NJ"
        assert ship_to["contactAddress"]["postalCode"] == "07101"


class TestShippingLabelsVoid:
    def test_void_with_confirmation(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.cancel_shipment.return_value = SAMPLE_CANCELLED_SHIPMENT

        with cfg_p, cli_p:
            result = runner.invoke(app, ["seller", "shipping-labels", "void", "S-test-001"], input="y\n")

        assert result.exit_code == 0
        client.cancel_shipment.assert_called_once_with("S-test-001")
        assert "CANCELLATION_ACCEPTED" in result.stderr

    def test_void_with_force(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.cancel_shipment.return_value = SAMPLE_CANCELLED_SHIPMENT

        with cfg_p, cli_p:
            result = runner.invoke(app, ["seller", "shipping-labels", "void", "S-test-001", "--force"])

        assert result.exit_code == 0
        client.cancel_shipment.assert_called_once_with("S-test-001")

    def test_void_declined(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)

        with cfg_p, cli_p:
            result = runner.invoke(app, ["seller", "shipping-labels", "void", "S-test-001"], input="n\n")

        assert result.exit_code == 0
        client.cancel_shipment.assert_not_called()
        assert "Aborted" in result.stderr

    def test_cancel_alias_works(self, runner, mock_config):
        """The hidden 'cancel' command should work identically to 'void'."""
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.cancel_shipment.return_value = SAMPLE_CANCELLED_SHIPMENT

        with cfg_p, cli_p:
            result = runner.invoke(app, ["seller", "shipping-labels", "cancel", "S-test-001", "--force"])

        assert result.exit_code == 0
        client.cancel_shipment.assert_called_once_with("S-test-001")


class TestShippingLabelsDownload:
    def test_downloads_with_explicit_path(self, runner, mock_config, tmp_path):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.download_label_file.return_value = b"%PDF-1.4 test content"

        out_path = str(tmp_path / "label_S-test-001.pdf")

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-labels", "download", "S-test-001", "--out", out_path,
            ])

        assert result.exit_code == 0
        client.download_label_file.assert_called_once_with("S-test-001")

        # Verify file was written
        assert os.path.exists(out_path)
        with open(out_path, "rb") as f:
            assert f.read() == b"%PDF-1.4 test content"

        # Verify JSON output
        data = json.loads(result.stdout)
        assert data["shipment_id"] == "S-test-001"
        assert data["size_bytes"] == 21

    def test_download_saves_pdf(self, runner, mock_config, tmp_path):
        client, cfg_p, cli_p = _mock_client(mock_config)
        pdf_data = b"%PDF-1.4 larger content with more bytes for testing"
        client.download_label_file.return_value = pdf_data

        out_path = str(tmp_path / "my-label.pdf")

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "shipping-labels", "download", "S-test-001", "--out", out_path,
            ])

        assert result.exit_code == 0
        with open(out_path, "rb") as f:
            assert f.read() == pdf_data
