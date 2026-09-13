"""Tests for guarded eBay seller mutations."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ebay_cli.client import EbayClient
from ebay_cli.commands import listings, policies, store
from ebay_cli.main import app
from ebay_cli.models import Listing


def _active_listing_for_unpublish() -> Listing:
    return Listing(
        sku="EBAY-20260912153647",
        offer_id="264476167011",
        title="Test listing",
        status="active",
    )


def test_unpublish_returns_only_verified_offer_state(monkeypatch, runner):
    client = MagicMock()
    client.get_offer.return_value = {
        "offerId": "264476167011",
        "status": "UNPUBLISHED",
    }
    monkeypatch.setattr(listings, "get_client", lambda: client)
    monkeypatch.setattr(
        listings,
        "_get_listing_by_sku",
        lambda _client, _sku: _active_listing_for_unpublish(),
    )

    result = runner.invoke(
        app,
        ["seller", "listings", "unpublish", "EBAY-20260912153647", "--force"],
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "sku": "EBAY-20260912153647",
        "offer_id": "264476167011",
        "status": "UNPUBLISHED",
    }
    client.withdraw_offer.assert_called_once_with("264476167011")
    client.get_offer.assert_called_once_with("264476167011")


def test_unpublish_fails_when_offer_readback_is_still_published(monkeypatch, runner):
    client = MagicMock()
    client.get_offer.return_value = {
        "offerId": "264476167011",
        "status": "PUBLISHED",
    }
    monkeypatch.setattr(listings, "get_client", lambda: client)
    monkeypatch.setattr(
        listings,
        "_get_listing_by_sku",
        lambda _client, _sku: _active_listing_for_unpublish(),
    )

    result = runner.invoke(
        app,
        ["seller", "listings", "unpublish", "EBAY-20260912153647", "--force"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "expected UNPUBLISHED, got 'PUBLISHED'" in result.stderr
    client.withdraw_offer.assert_called_once_with("264476167011")
    client.get_offer.assert_called_once_with("264476167011")


def test_store_category_create_refuses_without_confirmation(monkeypatch, runner):
    client = MagicMock()
    monkeypatch.setattr(store, "get_client", lambda: client)

    result = runner.invoke(
        app,
        ["seller", "store", "categories", "create", "LEGO Sets"],
    )

    assert result.exit_code == 1
    assert "Refusing to create an eBay store category without --yes or --dry-run" in result.stderr
    client.create_store_category.assert_not_called()


def test_store_category_create_dry_run_prints_top_level_request(monkeypatch, runner):
    client = MagicMock()
    monkeypatch.setattr(store, "get_client", lambda: client)

    result = runner.invoke(
        app,
        ["seller", "store", "categories", "create", "LEGO Sets", "--dry-run"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "dry_run": True,
        "request": {"categoryName": "LEGO Sets"},
    }
    client.create_store_category.assert_not_called()


def test_store_category_create_yes_calls_stores_api(monkeypatch, runner):
    client = MagicMock()
    client.create_store_category.return_value = {
        "location": "/sell/stores/v1/store/tasks/task-123",
        "retryAfter": "5000",
    }
    monkeypatch.setattr(store, "get_client", lambda: client)

    result = runner.invoke(
        app,
        ["seller", "store", "categories", "create", "LEGO Sets", "--yes"],
    )

    assert result.exit_code == 0
    client.create_store_category.assert_called_once_with({"categoryName": "LEGO Sets"})
    assert json.loads(result.stdout) == {
        "categoryName": "LEGO Sets",
        "location": "/sell/stores/v1/store/tasks/task-123",
        "retryAfter": "5000",
    }


def test_policy_create_refuses_without_confirmation(monkeypatch, runner):
    client = MagicMock()
    monkeypatch.setattr(policies, "get_client", lambda: client)

    result = runner.invoke(
        app,
        [
            "seller",
            "policies",
            "create",
            "--name",
            "UPS Ground Saver buyer paid",
            "--handling-days",
            "3",
            "--carrier",
            "UPS",
            "--service",
            "US_UPSSurePost",
        ],
    )

    assert result.exit_code == 1
    assert "Refusing to create an eBay fulfillment policy without --yes or --dry-run" in result.stderr
    client.create_fulfillment_policy.assert_not_called()


def test_policy_create_dry_run_prints_buyer_paid_calculated_payload(monkeypatch, runner):
    client = MagicMock()
    monkeypatch.setattr(policies, "get_client", lambda: client)

    result = runner.invoke(
        app,
        [
            "seller",
            "policies",
            "create",
            "--name",
            "UPS Ground Saver buyer paid",
            "--handling-days",
            "3",
            "--carrier",
            "UPS",
            "--service",
            "US_UPSSurePost",
            "--exclude-us-special-locations",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    request = payload["request"]
    assert request["handlingTime"] == {"unit": "DAY", "value": 3}
    assert request["shipToLocations"]["regionExcluded"] == [
        {"regionName": "Alaska/Hawaii"},
        {"regionName": "US Protectorates"},
        {"regionName": "APO/FPO"},
    ]
    shipping_option = request["shippingOptions"][0]
    assert shipping_option["costType"] == "CALCULATED"
    assert shipping_option["shippingServices"] == [
        {
            "sortOrder": 1,
            "shippingCarrierCode": "UPS",
            "shippingServiceCode": "US_UPSSurePost",
            "freeShipping": False,
            "buyerResponsibleForShipping": True,
            "buyerResponsibleForPickup": False,
        }
    ]
    client.create_fulfillment_policy.assert_not_called()


def test_policy_create_yes_calls_account_api(monkeypatch, runner):
    client = MagicMock()
    client.create_fulfillment_policy.return_value = {
        "fulfillmentPolicyId": "policy-123",
        "name": "UPS Ground Saver buyer paid",
    }
    monkeypatch.setattr(policies, "get_client", lambda: client)

    result = runner.invoke(
        app,
        [
            "seller",
            "policies",
            "create",
            "--name",
            "UPS Ground Saver buyer paid",
            "--handling-days",
            "3",
            "--carrier",
            "UPS",
            "--service",
            "US_UPSSurePost",
            "--exclude-us-special-locations",
            "--yes",
        ],
    )

    assert result.exit_code == 0
    payload = client.create_fulfillment_policy.call_args.args[0]
    assert payload["shippingOptions"][0]["costType"] == "CALCULATED"
    assert payload["shippingOptions"][0]["shippingServices"][0]["buyerResponsibleForShipping"] is True
    assert payload["shipToLocations"]["regionExcluded"][2] == {"regionName": "APO/FPO"}


def test_store_category_client_uses_async_stores_endpoint(mock_config):
    with patch("ebay_cli.client.TokenManager") as token_manager:
        token_manager.return_value.is_expired.return_value = False
        client = EbayClient(config=mock_config)

    response = MagicMock()
    response.ok = True
    response.status_code = 202
    response.content = b""
    response.headers = {
        "Location": "/sell/stores/v1/store/tasks/task-123",
        "Retry-After": "5000",
    }

    with patch("ebay_cli.client.requests.request", return_value=response) as request:
        result = client.create_store_category({"categoryName": "LEGO Sets"})

    assert request.call_args.kwargs["method"] == "POST"
    assert request.call_args.kwargs["url"].endswith("/sell/stores/v1/store/categories")
    assert request.call_args.kwargs["json"] == {"categoryName": "LEGO Sets"}
    assert result == {
        "location": "/sell/stores/v1/store/tasks/task-123",
        "retryAfter": "5000",
    }


@pytest.mark.parametrize("allow_offers", [False, None])
def test_template_does_not_enable_best_offer_without_true(allow_offers):
    pricing = {
        "format": "FIXED_PRICE",
        "price": {"value": "49.99", "currency": "USD"},
    }
    if allow_offers is not None:
        pricing["allowOffers"] = allow_offers

    payload = listings._template_to_offer_payload({"pricing": pricing})

    assert "listingPolicies" not in payload


def test_template_allow_offers_enables_best_offer_terms():
    payload = listings._template_to_offer_payload(
        {
            "pricing": {
                "format": "FIXED_PRICE",
                "price": {"value": "49.99", "currency": "USD"},
                "allowOffers": True,
            }
        }
    )

    assert payload["listingPolicies"]["bestOfferTerms"] == {
        "bestOfferEnabled": True,
    }
