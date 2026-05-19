"""Shared fixtures for eBay CLI tests."""
import pytest
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner


@pytest.fixture
def runner():
    """Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_config():
    """Mock Config that returns test credentials and ship-from address."""
    config = MagicMock()
    config.access_token = "test-token-123"
    config.client_id = "test-client-id"
    config.client_secret = "test-client-secret"
    config.api_base_url = "https://api.ebay.com"
    config.auth_base_url = "https://auth.ebay.com"
    config.environment = "production"
    config.from_name = "Test Seller"
    config.from_street = "123 Test St"
    config.from_city = "Testville"
    config.from_state = "OH"
    config.from_zip = "43001"
    config.from_country = "US"
    config.from_phone = "5551234567"
    config.get_from_name.return_value = config.from_name
    config.get_from_street.return_value = config.from_street
    config.get_from_city.return_value = config.from_city
    config.get_from_state.return_value = config.from_state
    config.get_from_zip.return_value = config.from_zip
    config.get_from_country.return_value = config.from_country
    config.get_from_phone.return_value = config.from_phone
    config.get_missing_credentials.return_value = []
    config.OAUTH_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    config.refresh_token = "test-refresh-token"
    config.OAUTH_TOKEN_AUTH = "basic"
    return config


# -- Sample API responses --

SAMPLE_ORDER = {
    "orderId": "04-08365-42542",
    "orderFulfillmentStatus": "NOT_STARTED",
    "orderPaymentStatus": "PAID",
    "buyer": {"username": "testbuyer"},
    "pricingSummary": {"total": {"value": "29.99", "currency": "USD"}},
    "creationDate": "2026-02-20T10:00:00.000Z",
    "cancelStatus": {"cancelState": "NONE_REQUESTED"},
    "fulfillmentStartInstructions": [{
        "shippingStep": {
            "shipTo": {
                "fullName": "Jane Buyer",
                "contactAddress": {
                    "addressLine1": "456 Oak Ave",
                    "addressLine2": "Apt 3",
                    "city": "Newark",
                    "stateOrProvince": "NJ",
                    "postalCode": "07101",
                    "countryCode": "US",
                },
                "primaryPhone": {"phoneNumber": "5559876543"},
            }
        }
    }],
    "lineItems": [{
        "lineItemId": "LI001",
        "title": "LEGO Set 12345",
        "sku": "SKU-001",
        "quantity": 1,
        "lineItemCost": {"value": "29.99", "currency": "USD"},
    }],
}

SAMPLE_QUOTE_RESPONSE = {
    "shippingQuoteId": "Q-test-001",
    "creationDate": "2026-02-25T20:00:00.000Z",
    "expirationDate": "2026-02-25T21:00:00.000Z",
    "rates": [
        {
            "rateId": "R-ground-001",
            "shippingCarrierCode": "USPS",
            "shippingCarrierName": "USPS",
            "shippingServiceCode": "GROUND_ADVANTAGE",
            "shippingServiceName": "Ground Advantage",
            "shippingPackageCode": "PACKAGE",
            "shippingPackageName": "Package",
            "pickupType": "DROP_OFF",
            "baseShippingCost": {"value": "7.46", "currency": "USD"},
            "minEstimatedDeliveryDate": "2026-02-27T08:00:00.000Z",
            "maxEstimatedDeliveryDate": "2026-03-03T08:00:00.000Z",
            "additionalOptions": [
                {
                    "optionType": "PROOF_OF_DELIVERY",
                    "additionalCost": {"value": "3.95", "currency": "USD"},
                },
                {
                    "optionType": "SHIP_COVER_INSURANCE",
                    "additionalCost": {"value": "1.70", "currency": "USD"},
                },
            ],
            "rateRecommendation": [],
        },
        {
            "rateId": "R-priority-001",
            "shippingCarrierCode": "USPS",
            "shippingCarrierName": "USPS",
            "shippingServiceCode": "STANDARD",
            "shippingServiceName": "Priority Mail",
            "shippingPackageCode": "PACKAGE",
            "shippingPackageName": "Package",
            "pickupType": "DROP_OFF",
            "baseShippingCost": {"value": "10.64", "currency": "USD"},
            "minEstimatedDeliveryDate": "2026-02-26T08:00:00.000Z",
            "maxEstimatedDeliveryDate": "2026-03-02T08:00:00.000Z",
            "additionalOptions": [
                {
                    "optionType": "PROOF_OF_DELIVERY",
                    "additionalCost": {"value": "3.95", "currency": "USD"},
                },
                {
                    "optionType": "SHIP_COVER_INSURANCE",
                    "additionalCost": {"value": "1.70", "currency": "USD"},
                },
            ],
            "rateRecommendation": ["CHEAPEST_ON_TIME"],
        },
    ],
    "shipFrom": {
        "fullName": "Test Seller",
        "contactAddress": {
            "addressLine1": "123 Test St",
            "city": "Testville",
            "stateOrProvince": "OH",
            "postalCode": "43001",
            "countryCode": "US",
        },
    },
    "shipTo": {
        "fullName": "Jane Buyer",
        "contactAddress": {
            "addressLine1": "456 Oak Ave",
            "city": "Newark",
            "stateOrProvince": "NJ",
            "postalCode": "07101",
            "countryCode": "US",
        },
    },
    "orders": [{"orderId": "04-08365-42542", "channel": "EBAY"}],
    "warnings": [],
}

SAMPLE_SHIPMENT_RESPONSE = {
    "shipmentId": "S-test-001",
    "shipmentTrackingNumber": "9400111899223100012345",
    "creationDate": "2026-02-25T20:05:00.000Z",
    "orders": [{"orderId": "04-08365-42542", "channel": "EBAY"}],
    "rate": {
        "rateId": "R-ground-001",
        "shippingQuoteId": "Q-test-001",
        "shippingCarrierCode": "USPS",
        "shippingCarrierName": "USPS",
        "shippingServiceCode": "GROUND_ADVANTAGE",
        "shippingServiceName": "Ground Advantage",
        "baseShippingCost": {"value": "7.46", "currency": "USD"},
        "totalShippingCost": {"value": "7.46", "currency": "USD"},
        "minEstimatedDeliveryDate": "2026-02-27T08:00:00.000Z",
        "maxEstimatedDeliveryDate": "2026-03-03T08:00:00.000Z",
    },
    "cancellation": None,
}

SAMPLE_CANCELLED_SHIPMENT = {
    **SAMPLE_SHIPMENT_RESPONSE,
    "cancellation": {
        "cancellationRequestedDate": "2026-02-25T21:00:00.000Z",
        "cancellationStatus": "CANCELLATION_ACCEPTED",
    },
}
