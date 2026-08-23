"""Tests for the shipping_label property surfaced on orders commands.

Covers the fix for two bugs found while investigating why printed shipping
labels didn't match what sellers expected:
  1. `orders get`/`orders fulfillments` read `f.get("trackingNumber")`, but
     the Fulfillment API field is actually `shipmentTrackingNumber` - tracking
     numbers always rendered blank in table mode.
  2. There was no way to see which carrier/service/tracking a label used
     without a separate `orders fulfillments` call per order. `orders list
     --include-shipping-labels` and `orders get --include-shipping-labels`
     now attach a friendly `shipping_label` property.
"""
from unittest.mock import patch, MagicMock

from ebay_cli.main import app

from .conftest import SAMPLE_ORDER

SAMPLE_FULFILLMENT = {
    "fulfillmentId": "383134020340",
    "shipmentTrackingNumber": "383134020340",
    "shippingCarrierCode": "FedEx",
    "shippingServiceCode": "FedExSmartPost",
    "shippedDate": "2026-08-12T13:45:42.000Z",
    "lineItems": [{"lineItemId": "10083841615314"}],
}


def _mock_client(mock_config):
    client = MagicMock()
    config_patch = patch("ebay_cli.commands.orders.get_config", return_value=mock_config)
    client_patch = patch("ebay_cli.commands.orders.get_client", return_value=client)
    return client, config_patch, client_patch


class TestShippingLabelProperty:
    def test_orders_get_includes_shipping_label_summary(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = dict(SAMPLE_ORDER)
        client.get_shipping_fulfillments.return_value = {"total": 1, "fulfillments": [SAMPLE_FULFILLMENT]}

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "orders", "get", "04-08365-42542", "--include-shipping-labels",
            ])

        assert result.exit_code == 0
        import json
        data = json.loads(result.stdout)
        assert data["shipping_label"] == {
            "carrier": "FedEx",
            "service": "FedExSmartPost",
            "tracking_number": "383134020340",
            "shipped_date": "2026-08-12T13:45:42.000Z",
        }

    def test_orders_get_shipping_label_none_when_unshipped(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_order.return_value = dict(SAMPLE_ORDER)
        client.get_shipping_fulfillments.return_value = {"total": 0, "fulfillments": []}

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "orders", "get", "04-08365-42542", "--include-shipping-labels",
            ])

        assert result.exit_code == 0
        import json
        data = json.loads(result.stdout)
        assert data["shipping_label"] is None

    def test_orders_list_includes_shipping_label_per_order(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_orders.return_value = {"orders": [dict(SAMPLE_ORDER)], "total": 1}
        client.get_shipping_fulfillments.return_value = {"total": 1, "fulfillments": [SAMPLE_FULFILLMENT]}

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "orders", "list", "--include-shipping-labels",
            ])

        assert result.exit_code == 0
        import json
        data = json.loads(result.stdout)
        assert data["orders"][0]["shipping_label"]["carrier"] == "FedEx"
        assert data["orders"][0]["shipping_label"]["tracking_number"] == "383134020340"
        client.get_shipping_fulfillments.assert_called_once_with("04-08365-42542")

    def test_orders_list_omits_shipping_label_by_default(self, runner, mock_config):
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_orders.return_value = {"orders": [dict(SAMPLE_ORDER)], "total": 1}

        with cfg_p, cli_p:
            result = runner.invoke(app, ["seller", "orders", "list"])

        assert result.exit_code == 0
        import json
        data = json.loads(result.stdout)
        assert "shipping_label" not in data["orders"][0]
        client.get_shipping_fulfillments.assert_not_called()

    def test_orders_fulfillments_uses_correct_tracking_field(self, runner, mock_config):
        """Regression test: the API field is shipmentTrackingNumber, not trackingNumber."""
        client, cfg_p, cli_p = _mock_client(mock_config)
        client.get_shipping_fulfillments.return_value = {"total": 1, "fulfillments": [SAMPLE_FULFILLMENT]}

        with cfg_p, cli_p:
            result = runner.invoke(app, [
                "seller", "orders", "fulfillments", "04-08365-42542", "--table",
            ])

        assert result.exit_code == 0
        assert "383134020340" in result.stdout
