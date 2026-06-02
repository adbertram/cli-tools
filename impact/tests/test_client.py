from types import SimpleNamespace

import pytest

from impact_cli import client as client_module
from impact_cli.client import ImpactClient
from impact_cli.models import ImpactResource


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300
        self.text = "response text"
        self.content = b"response bytes"

    def json(self):
        return self._payload


def fake_config():
    return SimpleNamespace(
        impact_account_sid="SID123",
        impact_auth_token="TOKEN456",
        base_url="https://api.impact.com",
        has_credentials=lambda: True,
        get_missing_credentials=lambda: [],
    )


def test_client_uses_basic_auth_and_account_scoped_url(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return FakeResponse(payload={"AccountName": "Example", "Id": "123"})

    monkeypatch.setattr(client_module, "get_config", lambda: fake_config())
    monkeypatch.setattr(client_module.requests, "request", fake_request)

    account = ImpactClient().get_account()

    assert isinstance(account, ImpactResource)
    assert account.model_dump(mode="json")["AccountName"] == "Example"
    assert calls == [
        {
            "method": "GET",
            "url": "https://api.impact.com/Mediapartners/SID123/CompanyInformation",
            "headers": {"Accept": "application/json", "Content-Type": "application/json"},
            "auth": ("SID123", "TOKEN456"),
            "params": None,
            "json": None,
            "timeout": 30,
            "allow_redirects": True,
        }
    ]


def test_list_translates_limit_and_equality_filters(monkeypatch):
    calls = []

    def fake_request(**kwargs):
        calls.append(kwargs)
        return FakeResponse(payload={"Ads": [{"Id": "A1", "Name": "Ad", "CampaignId": "123"}]})

    monkeypatch.setattr(client_module, "get_config", lambda: fake_config())
    monkeypatch.setattr(client_module.requests, "request", fake_request)

    ads = ImpactClient().list_ads(limit=5, filters=["CampaignId:eq:123"])

    assert [ad.model_dump(mode="json") for ad in ads] == [{"Id": "A1", "Name": "Ad", "CampaignId": "123"}]
    assert calls[0]["params"] == {"PageSize": 5, "CampaignId": "123"}


def test_unsupported_api_filter_operator_fails_before_request(monkeypatch):
    monkeypatch.setattr(client_module, "get_config", lambda: fake_config())

    def fake_request(**kwargs):
        raise AssertionError("request should not be made")

    monkeypatch.setattr(client_module.requests, "request", fake_request)

    with pytest.raises(Exception, match="Unsupported Impact filter"):
        ImpactClient().list_ads(filters=["CampaignId:contains:123"])
