from __future__ import annotations

import pytest
from cli_tools_shared.exceptions import ClientError

from wpengine_cli.client import WpengineClient


class DummyConfig:
    base_url = "https://api.wpengineapi.com/v1"

    def __init__(
        self,
        username: str | None = "api-user",
        password: str | None = "api-pass",
        storage_dir=None,
    ):
        self.username = username
        self.password = password
        self.storage_dir = storage_dir

    def get_missing_credentials(self) -> list[str]:
        missing = []
        if not self.username:
            missing.append("USERNAME")
        if not self.password:
            missing.append("PASSWORD")
        return missing


class DummyResponse:
    def __init__(
        self,
        payload,
        *,
        status_code: int = 200,
        ok: bool = True,
        headers: dict[str, str] | None = None,
    ):
        self._payload = payload
        self.status_code = status_code
        self.ok = ok
        self.headers = headers or {}
        self.text = str(payload)
        self.content = b"{}"

    def json(self):
        return self._payload


class DummySession:
    def __init__(self, responses: list[DummyResponse]):
        self.responses = responses
        self.requests = []

    def request(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def test_client_uses_basic_auth_and_preserves_response_fields(tmp_path):
    session = DummySession(
        [
            DummyResponse(
                {
                    "results": [
                        {"id": "acc-1", "name": "ATA", "extra": {"plan": "agency"}},
                    ],
                    "next": None,
                }
            )
        ]
    )
    client = WpengineClient(config=DummyConfig(storage_dir=tmp_path), session=session)

    accounts = client.list_accounts(limit=1)

    assert accounts == [{"id": "acc-1", "name": "ATA", "extra": {"plan": "agency"}}]
    request = session.requests[0]
    assert request["auth"] == ("api-user", "api-pass")
    assert request["url"] == "https://api.wpengineapi.com/v1/accounts"
    assert request["params"] == {"limit": 1, "offset": 0}


def test_api_status_does_not_send_auth():
    session = DummySession([DummyResponse({"message": "ok", "status": "healthy"})])
    client = WpengineClient(config=DummyConfig(username=None, password=None), session=session, require_auth=False)

    status = client.get_api_status()

    assert status == {"message": "ok", "status": "healthy"}
    assert session.requests[0]["auth"] is None
    assert session.requests[0]["url"].endswith("/status")


def test_missing_credentials_fail_before_request():
    session = DummySession([])

    with pytest.raises(ClientError) as exc_info:
        WpengineClient(config=DummyConfig(username=None, password=None), session=session)

    assert "Missing credentials: USERNAME, PASSWORD" in str(exc_info.value)
    assert session.requests == []


def test_list_sites_uses_server_account_filter_and_client_filters(tmp_path):
    session = DummySession(
        [
            DummyResponse(
                {
                    "results": [
                        {"id": "site-1", "name": "ATA Prod", "account_id": "acc-1"},
                        {"id": "site-2", "name": "Other", "account_id": "acc-1"},
                    ],
                    "next": None,
                }
            )
        ]
    )
    client = WpengineClient(config=DummyConfig(storage_dir=tmp_path), session=session)

    sites = client.list_sites(limit=10, filters=["account_id:eq:acc-1,name:contains:ATA"])

    assert sites == [{"id": "site-1", "name": "ATA Prod", "account_id": "acc-1"}]
    assert session.requests[0]["params"] == {"account_id": "acc-1", "limit": 10, "offset": 0}


def test_list_environments_pages_until_next_is_empty(tmp_path):
    session = DummySession(
        [
            DummyResponse({"results": [{"id": "env-1"}], "next": "/installs?offset=1"}),
            DummyResponse({"results": [{"id": "env-2"}], "next": None}),
        ]
    )
    client = WpengineClient(config=DummyConfig(storage_dir=tmp_path), session=session)

    environments = client.list_environments(limit=2)

    assert environments == [{"id": "env-1"}, {"id": "env-2"}]
    assert session.requests[0]["params"] == {"limit": 2, "offset": 0}
    assert session.requests[1]["params"] == {"limit": 1, "offset": 1}


def test_purge_cache_posts_documented_type_payload():
    session = DummySession([DummyResponse({}, status_code=202)])
    client = WpengineClient(config=DummyConfig(), session=session)

    result = client.purge_cache("env-123", "cdn")

    assert result == {"accepted": True, "environment_id": "env-123", "type": "cdn"}
    request = session.requests[0]
    assert request["method"] == "POST"
    assert request["url"].endswith("/installs/env-123/purge_cache")
    assert request["json"] == {"type": "cdn"}


def test_ssh_key_methods_use_documented_endpoints():
    session = DummySession(
        [
            DummyResponse({"results": [{"uuid": "key-1", "fingerprint": "fp"}], "next": None}),
            DummyResponse({"id": "key-1", "fingerprint": "fp"}),
            DummyResponse({}, status_code=204),
        ]
    )
    client = WpengineClient(config=DummyConfig(), session=session)

    fetched = client.get_ssh_key("key-1")
    created = client.add_ssh_key("ssh-ed25519 AAAA test")
    deleted = client.delete_ssh_key("key-1")

    assert fetched == {"uuid": "key-1", "fingerprint": "fp"}
    assert created == {"id": "key-1", "fingerprint": "fp"}
    assert deleted == {"deleted": True, "ssh_key_id": "key-1"}
    assert session.requests[0]["method"] == "GET"
    assert session.requests[0]["url"].endswith("/ssh_keys")
    assert session.requests[0]["params"] == {"limit": 100, "offset": 0}
    assert session.requests[1]["url"].endswith("/ssh_keys")
    assert session.requests[1]["json"] == {"public_key": "ssh-ed25519 AAAA test"}
    assert session.requests[2]["method"] == "DELETE"
    assert session.requests[2]["url"].endswith("/ssh_keys/key-1")
