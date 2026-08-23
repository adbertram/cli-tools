"""Regression tests for OAuth token-refresh error handling in FreshBooksClient.

Covers the defect where a failed proactive token refresh (invalid/expired
refresh token -> OAuth ``invalid_grant``) was silently swallowed by
``except Exception: pass``, leaving a dead access token that produced a
confusing downstream HTTP 401 instead of a clear "re-authenticate" message.

The fix makes ``_is_token_expired()``-triggered refresh failures propagate a
clear ``ClientError`` instructing the user to run ``freshbooks auth login`` —
while leaving the successful-refresh path behaving exactly as before.
"""
import types

import pytest
import requests

from cli_tools_shared.exceptions import ClientError
from freshbooks_cli import client as client_module
from freshbooks_cli.client import FreshBooksClient


class FakeConfig:
    """Minimal stand-in for the FreshBooks Config object."""

    OAUTH_REDIRECT_URI = "https://localhost/callback"

    def __init__(self, *, expired: bool, refresh_token: str = "stored-refresh-token"):
        self.access_token = "stored-access-token"
        self.account_id = "123456"
        self.client_id = "client-id"
        self.client_secret = "client-secret"
        self.refresh_token = refresh_token
        self.redirect_uri = None
        # Drive _is_token_expired(): a past timestamp -> expired, far future -> valid.
        self.token_expires_at = "0" if expired else "99999999999"
        self.saved_tokens = None

    def get_missing_credentials(self):
        return []

    def save_tokens(self, access, refresh, expires_at):
        self.access_token = access
        self.refresh_token = refresh
        self.token_expires_at = expires_at
        self.saved_tokens = (access, refresh, expires_at)


class FakeResponse:
    def __init__(self, status_code, json_data=None, *, ok=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.ok = ok if ok is not None else (200 <= status_code < 300)
        self.text = text
        self.headers = {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


def _make_client(monkeypatch, *, expired, refresh_token="stored-refresh-token"):
    """Build a FreshBooksClient backed by FakeConfig (no real .env / network)."""
    fake_config = FakeConfig(expired=expired, refresh_token=refresh_token)
    monkeypatch.setattr(client_module, "get_config", lambda: fake_config)
    fb = FreshBooksClient()
    return fb, fake_config


def test_expired_token_refresh_invalid_grant_raises_clear_error(monkeypatch):
    """A proactive refresh that fails with invalid_grant must raise a clear
    re-authenticate error instead of being swallowed and falling through to a
    downstream 401."""
    fb, _config = _make_client(monkeypatch, expired=True)

    def fake_post(url, data=None, **kwargs):
        # OAuth token endpoint returns the FreshBooks invalid_grant error.
        return FakeResponse(400, {"error": "invalid_grant"}, ok=False)

    def fail_if_called(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError(
            "API request was attempted with a dead token; refresh failure was swallowed"
        )

    monkeypatch.setattr(client_module.requests, "post", fake_post)
    monkeypatch.setattr(client_module.requests, "request", fail_if_called)

    with pytest.raises(ClientError) as excinfo:
        fb.get_invoices()

    message = str(excinfo.value)
    assert "freshbooks auth login" in message
    # Must be the actionable refresh error, NOT a confusing downstream 401.
    assert "401" not in message


def test_expired_token_missing_refresh_token_raises_clear_error(monkeypatch):
    """When the token is expired and no refresh token is stored, the proactive
    refresh must raise a clear re-authenticate error (not swallow it)."""
    fb, _config = _make_client(monkeypatch, expired=True, refresh_token="")

    def fail_if_called(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("API request attempted despite missing refresh token")

    monkeypatch.setattr(client_module.requests, "request", fail_if_called)

    with pytest.raises(ClientError) as excinfo:
        fb.get_invoices()

    assert "freshbooks auth login" in str(excinfo.value)


def test_expired_token_successful_refresh_preserves_success_path(monkeypatch):
    """A successful proactive refresh must still work exactly as before: new
    tokens are saved and the original request proceeds and returns data."""
    fb, config = _make_client(monkeypatch, expired=True)

    invoices_payload = {
        "response": {"result": {"invoices": [{"id": 1, "invoice_number": "INV-1"}]}}
    }

    def fake_post(url, data=None, **kwargs):
        # OAuth token endpoint returns a fresh token set.
        return FakeResponse(
            200,
            {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "expires_in": 43200,
            },
        )

    def fake_request(method, url, **kwargs):
        # The API call must carry the refreshed bearer token.
        assert kwargs["headers"]["Authorization"] == "Bearer new-access-token"
        return FakeResponse(200, invoices_payload)

    monkeypatch.setattr(client_module.requests, "post", fake_post)
    monkeypatch.setattr(client_module.requests, "request", fake_request)

    invoices = fb.get_invoices()

    assert invoices == [{"id": 1, "invoice_number": "INV-1"}]
    # Tokens were rotated and persisted via save_tokens().
    assert config.saved_tokens is not None
    assert config.access_token == "new-access-token"
    assert config.refresh_token == "new-refresh-token"


def test_valid_token_skips_refresh_and_succeeds(monkeypatch):
    """When the token is not expired, no refresh is attempted and the request
    proceeds normally (unchanged behavior)."""
    fb, _config = _make_client(monkeypatch, expired=False)

    invoices_payload = {"response": {"result": {"invoices": []}}}

    def fail_post(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("token refresh attempted for a still-valid token")

    def fake_request(method, url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer stored-access-token"
        return FakeResponse(200, invoices_payload)

    monkeypatch.setattr(client_module.requests, "post", fail_post)
    monkeypatch.setattr(client_module.requests, "request", fake_request)

    assert fb.get_invoices() == []
