"""Tests for eBay Logistics API client methods."""
import json
import pytest
from unittest.mock import patch, MagicMock

from .conftest import (
    SAMPLE_QUOTE_RESPONSE,
    SAMPLE_SHIPMENT_RESPONSE,
    SAMPLE_CANCELLED_SHIPMENT,
)


@pytest.fixture
def client(mock_config):
    """Create an EbayClient with mocked config and token manager."""
    with patch("ebay_cli.client.get_config", return_value=mock_config), \
         patch("ebay_cli.client.TokenManager") as MockTM:
        tm = MockTM.return_value
        tm.is_expired.return_value = False
        tm.force_refresh.return_value = None

        from ebay_cli.client import EbayClient
        c = EbayClient()
        return c


class TestCreateShippingQuote:
    def test_sends_correct_payload(self, client):
        payload = {
            "orders": [{"channel": "EBAY", "orderId": "04-08365-42542"}],
            "packageSpecification": {
                "weight": {"value": "2", "unit": "POUND"},
                "dimensions": {"length": "10", "width": "8", "height": "4", "unit": "INCH"},
            },
            "shipFrom": {
                "fullName": "Seller",
                "contactAddress": {"addressLine1": "123 St", "postalCode": "43001", "countryCode": "US"},
            },
            "shipTo": {
                "fullName": "Buyer",
                "contactAddress": {"addressLine1": "456 Ave", "postalCode": "07101", "countryCode": "US"},
            },
        }

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 201
        mock_resp.json.return_value = SAMPLE_QUOTE_RESPONSE

        with patch("ebay_cli.client.requests.request", return_value=mock_resp) as mock_req:
            result = client.create_shipping_quote(payload)

            # Verify API call
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            assert call_args.kwargs["method"] == "POST"
            assert "/sell/logistics/v1_beta/shipping_quote" in call_args.kwargs["url"]
            assert call_args.kwargs["json"] == payload

            # Verify marketplace header was added
            headers = call_args.kwargs["headers"]
            assert headers.get("X-EBAY-C-MARKETPLACE-ID") == "EBAY_US"

        assert result["shippingQuoteId"] == "Q-test-001"
        assert len(result["rates"]) == 2

    def test_does_not_use_apiz_subdomain(self, client):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 201
        mock_resp.json.return_value = SAMPLE_QUOTE_RESPONSE

        with patch("ebay_cli.client.requests.request", return_value=mock_resp) as mock_req:
            client.create_shipping_quote({"orders": [{"channel": "EBAY", "orderId": "X"}]})

            url = mock_req.call_args.kwargs["url"]
            assert "apiz." not in url
            assert "api.ebay.com" in url


class TestCreateFromShippingQuote:
    def test_basic_purchase(self, client):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 201
        mock_resp.json.return_value = SAMPLE_SHIPMENT_RESPONSE

        with patch("ebay_cli.client.requests.request", return_value=mock_resp) as mock_req:
            result = client.create_from_shipping_quote("Q-test-001", "R-ground-001")

            sent_payload = mock_req.call_args.kwargs["json"]
            assert sent_payload["shippingQuoteId"] == "Q-test-001"
            assert sent_payload["rateId"] == "R-ground-001"
            assert "additionalOptions" not in sent_payload

        assert result["shipmentId"] == "S-test-001"
        assert result["shipmentTrackingNumber"] == "9400111899223100012345"

    def test_with_additional_options(self, client):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 201
        mock_resp.json.return_value = SAMPLE_SHIPMENT_RESPONSE

        options = [{"optionType": "SHIP_COVER_INSURANCE", "additionalCost": {"value": "1.70", "currency": "USD"}}]

        with patch("ebay_cli.client.requests.request", return_value=mock_resp) as mock_req:
            client.create_from_shipping_quote(
                "Q-test-001", "R-ground-001",
                additional_options=options,
                label_custom_message="Thank you!",
            )

            sent_payload = mock_req.call_args.kwargs["json"]
            assert sent_payload["additionalOptions"] == options
            assert sent_payload["labelCustomMessage"] == "Thank you!"

    def test_with_return_address(self, client):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 201
        mock_resp.json.return_value = SAMPLE_SHIPMENT_RESPONSE

        return_to = {"fullName": "Returns Dept", "contactAddress": {"postalCode": "43001", "countryCode": "US"}}

        with patch("ebay_cli.client.requests.request", return_value=mock_resp) as mock_req:
            client.create_from_shipping_quote("Q-test-001", "R-ground-001", return_to=return_to)

            sent_payload = mock_req.call_args.kwargs["json"]
            assert sent_payload["returnTo"] == return_to


class TestGetShippingQuote:
    def test_fetches_by_id(self, client):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_QUOTE_RESPONSE

        with patch("ebay_cli.client.requests.request", return_value=mock_resp) as mock_req:
            result = client.get_shipping_quote("Q-test-001")

            assert mock_req.call_args.kwargs["method"] == "GET"
            assert "/shipping_quote/Q-test-001" in mock_req.call_args.kwargs["url"]

        assert result["shippingQuoteId"] == "Q-test-001"


class TestGetShipment:
    def test_fetches_by_id(self, client):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_SHIPMENT_RESPONSE

        with patch("ebay_cli.client.requests.request", return_value=mock_resp) as mock_req:
            result = client.get_shipment("S-test-001")

            assert mock_req.call_args.kwargs["method"] == "GET"
            assert "/shipment/S-test-001" in mock_req.call_args.kwargs["url"]
            # Should NOT hit the cancel or download endpoints
            assert "cancel" not in mock_req.call_args.kwargs["url"]
            assert "download" not in mock_req.call_args.kwargs["url"]

        assert result["shipmentTrackingNumber"] == "9400111899223100012345"


class TestCancelShipment:
    def test_posts_to_cancel_endpoint(self, client):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_CANCELLED_SHIPMENT

        with patch("ebay_cli.client.requests.request", return_value=mock_resp) as mock_req:
            result = client.cancel_shipment("S-test-001")

            assert mock_req.call_args.kwargs["method"] == "POST"
            assert "/shipment/S-test-001/cancel" in mock_req.call_args.kwargs["url"]

        assert result["cancellation"]["cancellationStatus"] == "CANCELLATION_ACCEPTED"


class TestDownloadLabelFile:
    def test_returns_pdf_bytes(self, client):
        pdf_bytes = b"%PDF-1.4 fake label content"
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.content = pdf_bytes

        with patch("ebay_cli.client.requests.get", return_value=mock_resp) as mock_get:
            result = client.download_label_file("S-test-001")

            # Verify correct URL
            url = mock_get.call_args.args[0]
            assert "/shipment/S-test-001/download_label_file" in url
            assert "apiz." not in url

            # Verify Accept header
            headers = mock_get.call_args.kwargs["headers"]
            assert headers["Accept"] == "application/pdf"
            assert headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"

        assert result == pdf_bytes

    def test_retries_on_401(self, client):
        pdf_bytes = b"%PDF-1.4 content"
        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.ok = False
        resp_200 = MagicMock()
        resp_200.ok = True
        resp_200.status_code = 200
        resp_200.content = pdf_bytes

        with patch("ebay_cli.client.requests.get", side_effect=[resp_401, resp_200]):
            result = client.download_label_file("S-test-001")

        assert result == pdf_bytes


class TestErrorHandling:
    def test_template_parameter_substitution(self, client):
        """eBay returns errors like 'Missing field {fieldName}' with parameters."""
        from ebay_cli.client import ClientError

        error_body = {
            "errors": [{
                "errorId": 90010,
                "message": "Missing field {fieldName}.",
                "parameters": [{"name": "fieldName", "value": "packageSpecification.dimensions"}],
            }]
        }
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 400
        mock_resp.json.return_value = error_body
        mock_resp.text = json.dumps(error_body)

        with patch("ebay_cli.client.requests.request", return_value=mock_resp):
            with pytest.raises(ClientError, match="Missing field packageSpecification.dimensions"):
                client.create_shipping_quote({"orders": []})

    def test_marketplace_header_added_for_logistics(self, client):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_SHIPMENT_RESPONSE

        with patch("ebay_cli.client.requests.request", return_value=mock_resp) as mock_req:
            client.get_shipment("S-test-001")
            headers = mock_req.call_args.kwargs["headers"]
            assert "X-EBAY-C-MARKETPLACE-ID" in headers

    def test_marketplace_header_not_added_for_fulfillment(self, client):
        """Fulfillment API calls should not get the marketplace header."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"orders": [], "total": 0}

        # Reset headers to clean state (remove any marketplace header from prior calls)
        client._update_headers()

        with patch("ebay_cli.client.requests.request", return_value=mock_resp) as mock_req:
            client.get_orders()
            headers = mock_req.call_args.kwargs["headers"]
            assert "X-EBAY-C-MARKETPLACE-ID" not in headers
