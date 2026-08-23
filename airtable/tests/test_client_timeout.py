"""Tests for bounded Airtable HTTP requests."""

import pytest
import requests

from airtable_cli.client import AirtableClient
from cli_tools_shared.exceptions import ClientError


class _Response:
    status_code = 200
    ok = True
    headers = {}

    def json(self):
        return {"ok": True}


def _client() -> AirtableClient:
    client = AirtableClient.__new__(AirtableClient)
    client.base_url = "https://api.airtable.test/v0"
    client.headers = {"Authorization": "Bearer test"}
    return client


def test_make_request_uses_bounded_http_timeout(monkeypatch):
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(requests, "request", fake_request)

    result = _client()._make_request("GET", "/appBase/Courses")

    assert result == {"ok": True}
    assert captured["timeout"] == AirtableClient.REQUEST_TIMEOUT_SECONDS


def test_make_request_converts_request_timeout_to_client_error(monkeypatch):
    monkeypatch.setattr(AirtableClient, "MAX_RETRIES", 1)

    def fake_request(**kwargs):
        raise requests.Timeout("request exceeded test timeout")

    monkeypatch.setattr(requests, "request", fake_request)

    with pytest.raises(ClientError, match="Connection error: request exceeded test timeout"):
        _client()._make_request("GET", "/appBase/Courses")
