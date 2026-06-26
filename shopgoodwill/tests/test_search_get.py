from typer.testing import CliRunner

from shopgoodwill_cli.client import ClientError, ShopGoodwillClient
from shopgoodwill_cli.commands import search


runner = CliRunner()


class _FakeClient:
    def __init__(self, require_auth=False):
        self.require_auth = require_auth

    def get_item(self, item_id):
        return {
            "itemId": item_id,
            "title": "Bulk LEGO Assorted Building Bricks 25.8 lbs",
            "currentPrice": 14.99,
            "buyNowPrice": 49.99,
            "numBids": 0,
            "endTime": "2026-06-17T16:05:00",
            "sellerName": "Goodwill",
            "sellerCity": "Rockville",
            "sellerState": "MD",
            "sellerId": 43,
            "allowShippingCalculation": True,
            "displayWeight": 25.8,
        }

    def calculate_shipping(self, item):
        return {
            "destinationZip": "47725",
            "shippingPrice": 19.67,
            "handlingPrice": 3.00,
            "total": 22.67,
            "serviceDescription": "GROUND_HOME_DELIVERY",
        }


class _NoBuyNowClient(_FakeClient):
    def get_item(self, item_id):
        item = super().get_item(item_id)
        item["buyNowPrice"] = 0
        return item


class _NoShippingCalculationClient(_FakeClient):
    def get_item(self, item_id):
        item = super().get_item(item_id)
        item["allowShippingCalculation"] = False
        return item

    def calculate_shipping(self, item):
        raise AssertionError("shipping should not be calculated")


class _ShippingCalculationFailureClient(_FakeClient):
    def calculate_shipping(self, item):
        raise ClientError("Shipping calculation failed: PACKAGE.WEIGHT.INVALID")


def test_search_get_table_shows_buy_now_price_when_available(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _FakeClient)

    result = runner.invoke(search.app, ["get", "267415400", "--table"])

    assert result.exit_code == 0
    assert "Current Price" in result.stdout
    assert "$14.99" in result.stdout
    assert "Buy Now Price" in result.stdout
    assert "$49.99" in result.stdout


def test_search_get_table_keeps_current_price_without_buy_now(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _NoBuyNowClient)

    result = runner.invoke(search.app, ["get", "267415400", "--table"])

    assert result.exit_code == 0
    assert "Current Price" in result.stdout
    assert "$14.99" in result.stdout
    assert "Buy Now Price" not in result.stdout


def test_search_get_table_shows_destination_shipping_when_available(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _FakeClient)

    result = runner.invoke(search.app, ["get", "267415400", "--table"])

    assert result.exit_code == 0
    assert "Destination ZIP" in result.stdout
    assert "47725" in result.stdout
    assert "Destination Shipping" in result.stdout
    assert "$19.67" in result.stdout
    assert "Shipping + Handling" in result.stdout
    assert "$22.67" in result.stdout


def test_search_get_json_adds_destination_shipping_when_available(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _FakeClient)

    result = runner.invoke(search.app, ["get", "267415400"])

    assert result.exit_code == 0
    assert '"destinationZip": "47725"' in result.stdout
    assert '"shippingPrice": 19.67' in result.stdout
    assert '"total": 22.67' in result.stdout


def test_search_get_does_not_calculate_shipping_when_unavailable(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _NoShippingCalculationClient)

    result = runner.invoke(search.app, ["get", "267415400"])

    assert result.exit_code == 0
    assert "shippingEstimate" not in result.stdout


def test_search_get_returns_item_when_shipping_calculation_fails(monkeypatch):
    monkeypatch.setattr(search, "ShopGoodwillClient", _ShippingCalculationFailureClient)

    result = runner.invoke(search.app, ["get", "267415400"])

    assert result.exit_code == 0
    assert '"itemId": 267415400' in result.stdout
    assert '"shippingEstimate": null' in result.stdout
    assert '"shippingEstimateUnavailable": true' in result.stdout
    assert "PACKAGE.WEIGHT.INVALID" in result.stdout


def test_calculate_shipping_parses_shopgoodwill_estimate_response(monkeypatch):
    class _Response:
        status_code = 200
        text = (
            "<p>Estimated Shipping and Handling:</p>"
            "<p>Shipping: <span id='shipping-span'>$19.67 (GROUND_HOME_DELIVERY)</span></p>"
            "<p>Handling: $3.00</p>"
            "<p><b>Total Shipping and Handling: $22.67</b></p>"
        )

    captured = {}

    def post(url, json):
        captured["url"] = url
        captured["json"] = json
        return _Response()

    client = ShopGoodwillClient(require_auth=False)
    monkeypatch.setattr(client.session, "post", post)

    result = client.calculate_shipping({
        "itemId": 267415400,
        "sellerId": 43,
        "displayWeight": 25.8,
        "handlingPrice": 3.0,
    })

    assert captured["url"].endswith("/ItemDetail/CalculateShipping")
    assert captured["json"] == {
        "itemId": 267415400,
        "sellerId": 43,
        "zipCode": "47725",
        "country": "US",
        "packageWeight": 25.8,
        "quantity": 1,
    }
    assert result == {
        "destinationZip": "47725",
        "country": "US",
        "shippingPrice": 19.67,
        "handlingPrice": 3.0,
        "total": 22.67,
        "serviceDescription": "GROUND_HOME_DELIVERY",
    }
