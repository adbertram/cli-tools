"""Unit tests for BrickowlClient._execute_request.

Covers two defects found live on 2026-10-21 while api.brickowl.com was
dropping TCP 443 during announced maintenance:

1. requests.request() was called with no timeout, so a dead host hung
   indefinitely (observed >5 minutes per command, compounding with retries).
2. On connection failure the raised ClientError embedded the full request
   URL, including the live `key=<API_KEY>` query parameter, leaking the key
   into stdout/stderr and agent transcripts.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from brickowl_cli.client import ClientError, BrickowlClient, DEFAULT_TIMEOUT


class _StubConfig:
    """Minimal config stub so BrickowlClient() doesn't touch real profiles."""

    def __init__(self, api_key="sk_live_super_secret_key_123"):
        self.base_url = "https://api.brickowl.com/v1"
        self.api_key = api_key

    def has_api_credentials(self):
        return True


@pytest.fixture
def client():
    with patch("brickowl_cli.client.get_config", return_value=_StubConfig()):
        return BrickowlClient(max_retries=0)


def test_timeout_is_passed_to_requests_request(client):
    """requests.request must always receive the module's DEFAULT_TIMEOUT."""
    fake_response = MagicMock(spec=requests.Response)
    fake_response.ok = True
    fake_response.status_code = 200
    fake_response.json.return_value = {"ok": True}

    with patch("brickowl_cli.client.requests.request", return_value=fake_response) as mock_request:
        client._get("/user/details")

    assert mock_request.called
    _, kwargs = mock_request.call_args
    assert kwargs.get("timeout") == DEFAULT_TIMEOUT
    assert DEFAULT_TIMEOUT == (10, 60)


def test_connection_error_message_redacts_api_key(client):
    """A ConnectTimeout/ConnectionError whose text contains the live key must
    surface a ClientError without that key anywhere in the message."""
    leaking_message = (
        "HTTPSConnectionPool(host='api.brickowl.com', port=443): "
        "Max retries exceeded with url: /v1/order/view?key=sk_live_super_secret_key_123&order_id=3697857 "
        "(Caused by ConnectTimeoutError(..., 'Connection to api.brickowl.com timed out. "
        "(connect timeout=None)'))"
    )

    with patch(
        "brickowl_cli.client.requests.request",
        side_effect=requests.exceptions.ConnectionError(leaking_message),
    ):
        with pytest.raises(ClientError) as exc_info:
            client._get("/order/view", {"order_id": "3697857"})

    message = str(exc_info.value)
    assert "sk_live_super_secret_key_123" not in message
    assert "key=***" in message


def test_connect_timeout_message_redacts_api_key(client):
    """Same redaction guarantee for requests.exceptions.ConnectTimeout."""
    leaking_message = (
        "HTTPSConnectionPool(host='api.brickowl.com', port=443): "
        "Max retries exceeded with url: /v1/auth/status?key=sk_live_super_secret_key_123 "
        "(connect timeout=None)"
    )

    with patch(
        "brickowl_cli.client.requests.request",
        side_effect=requests.exceptions.ConnectTimeout(leaking_message),
    ):
        with pytest.raises(ClientError) as exc_info:
            client._get("/auth/status")

    message = str(exc_info.value)
    assert "sk_live_super_secret_key_123" not in message


def test_http_error_response_text_redacts_api_key(client):
    """Any API-error response body that happens to echo the key is also redacted."""
    fake_response = MagicMock(spec=requests.Response)
    fake_response.ok = False
    fake_response.status_code = 400
    fake_response.text = "Bad request for key=sk_live_super_secret_key_123"

    with patch("brickowl_cli.client.requests.request", return_value=fake_response):
        with pytest.raises(ClientError) as exc_info:
            client._get("/order/view", {"order_id": "3697857"})

    message = str(exc_info.value)
    assert "sk_live_super_secret_key_123" not in message
    assert "key=***" in message
