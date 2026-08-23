"""Tests for plain-date normalization in order date filters.

The eBay Fulfillment API requires full ISO 8601 timestamps in the
creationdate/lastmodifieddate range filter. The documented CLI examples use
plain dates (e.g. created:gte:2023-01-01), so the client must expand a plain
YYYY-MM-DD value to a full timestamp before building the API filter string.
"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client(mock_config):
    """Create an EbayClient with mocked config and token manager."""
    with patch("ebay_cli.client.get_config", return_value=mock_config), \
         patch("ebay_cli.client.TokenManager") as MockTM:
        tm = MockTM.return_value
        tm.is_expired.return_value = False
        tm.force_refresh.return_value = None

        from ebay_cli.client import EbayClient
        return EbayClient()


class TestPlainDateExpansion:
    def test_created_gte_plain_date_expands_to_start_of_day(self, client):
        params = client.filter_map.to_api_params(["created:gte:2025-08-11"])
        assert params == {"filter": "creationdate:[2025-08-11T00:00:00.000Z..]"}

    def test_created_gt_plain_date_expands_to_start_of_day(self, client):
        params = client.filter_map.to_api_params(["created:gt:2025-08-11"])
        assert params == {"filter": "creationdate:[2025-08-11T00:00:00.000Z..]"}

    def test_created_lte_plain_date_expands_to_end_of_day(self, client):
        params = client.filter_map.to_api_params(["created:lte:2025-08-11"])
        assert params == {"filter": "creationdate:[..2025-08-11T23:59:59.999Z]"}

    def test_created_lt_plain_date_expands_to_end_of_day(self, client):
        params = client.filter_map.to_api_params(["created:lt:2025-08-11"])
        assert params == {"filter": "creationdate:[..2025-08-11T23:59:59.999Z]"}

    def test_creationdate_field_plain_date_expands(self, client):
        params = client.filter_map.to_api_params(["creationdate:gte:2025-08-11"])
        assert params == {"filter": "creationdate:[2025-08-11T00:00:00.000Z..]"}

    def test_modified_plain_date_expands_on_lastmodifieddate(self, client):
        params = client.filter_map.to_api_params(["modified:gte:2025-08-11"])
        assert params == {"filter": "lastmodifieddate:[2025-08-11T00:00:00.000Z..]"}

    def test_lastmodifieddate_plain_date_expands(self, client):
        params = client.filter_map.to_api_params(["lastmodifieddate:lte:2025-08-11"])
        assert params == {"filter": "lastmodifieddate:[..2025-08-11T23:59:59.999Z]"}

    def test_full_timestamp_passes_through_unchanged(self, client):
        params = client.filter_map.to_api_params(
            ["created:gte:2025-08-11T12:30:00.000Z"]
        )
        assert params == {"filter": "creationdate:[2025-08-11T12:30:00.000Z..]"}

    def test_bounded_range_joins_both_expanded_bounds(self, client):
        params = client.filter_map.to_api_params(
            ["created:gte:2025-08-01", "created:lte:2025-08-11"]
        )
        assert params == {
            "filter": (
                "creationdate:[2025-08-01T00:00:00.000Z..],"
                "creationdate:[..2025-08-11T23:59:59.999Z]"
            )
        }


class TestGetOrdersDateFilterRequest:
    def test_get_orders_sends_expanded_creationdate_filter(self, client):
        with patch.object(client, "_make_request", return_value={"orders": []}) as req:
            client.get_orders(filters=["created:gte:2025-08-11"], limit=5)

        req.assert_called_once()
        args, kwargs = req.call_args
        assert args == ("GET", "/sell/fulfillment/v1/order")
        assert kwargs["params"]["filter"] == "creationdate:[2025-08-11T00:00:00.000Z..]"
        assert kwargs["params"]["limit"] == 5
