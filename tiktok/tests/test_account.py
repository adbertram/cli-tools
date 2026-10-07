"""Whitelist live identity fields and preserve 64-bit account IDs."""
import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from tiktok_cli.client import ACCOUNT_INFO_PATH, ClientError, TikTokWebClient, normalize_account_identity
from tiktok_cli.commands import account as account_cmd
from tiktok_cli.main import app

ACCOUNT_ID = "6827268896283624454"


def payload():
    return {"message": "success", "data": {"user_id_str": ACCOUNT_ID, "user_id": int(ACCOUNT_ID), "username": "itstories", "session_key": "DO-NOT-EXPOSE", "email": "PRIVATE-CONTACT", "mobile": "PRIVATE-MOBILE"}}


class Page:
    def __init__(self, body=None, status=200):
        self.body = body if body is not None else json.dumps(payload())
        self.status = status
        self.requests = []

    def evaluate(self, js, args):
        self.requests.append((js, args))
        assert "await resp.text()" in js
        assert "await resp.json()" not in js
        return {"status": self.status, "body": self.body, "statusText": ""}


def client(page):
    urls = []
    browser = SimpleNamespace(get_page=lambda url: urls.append(url) or page, close=lambda: None, urls=urls)
    config = SimpleNamespace(base_url="https://www.tiktok.com", get_browser=lambda: browser, get_active_profile_name=lambda: "clipping")
    return TikTokWebClient(config=config, max_retries=0)


def test_observed_64_bit_id_survives_raw_text_boundary_and_secrets_are_excluded():
    page = Page()
    result = client(page).get_account(expected_username="@itstories", expected_account_id=ACCOUNT_ID)
    assert result["account_id"] == ACCOUNT_ID
    assert result["username"] == "itstories"
    assert result["profile"] == "clipping"
    assert set(result) == {"account_id", "username", "profile", "observed_at", "provenance"}
    assert result["provenance"] == "https://www.tiktok.com" + ACCOUNT_INFO_PATH
    assert page.requests[0][1] == {"path": ACCOUNT_INFO_PATH, "method": "GET", "csrf": False}
    assert "PRIVATE" not in json.dumps(result) and "DO-NOT-EXPOSE" not in json.dumps(result)


@pytest.mark.parametrize("change", [
    {"user_id_str": ""}, {"user_id_str": "0"}, {"user_id_str": "-1"}, {"user_id_str": "001"},
    {"user_id_str": 6827268896283624454}, {"user_id_str": "1" * 65},
    {"user_id": float(ACCOUNT_ID)}, {"user_id": int(float(ACCOUNT_ID))}, {"user_id": True},
    {"username": ""}, {"username": "u@example.com"}, {"username": "a/b"}, {"username": "..."},
    {"username": None}, {"error_code": "0"},
])
def test_malformed_or_inconsistent_identity_fails_closed(change):
    body = payload()
    body["data"].update(change)
    with pytest.raises(ClientError, match="malformed"):
        normalize_account_identity(body)


@pytest.mark.parametrize("body", [None, [], "bad", {}, {"message": "success", "data": []}, {"message": "unexpected", "data": {}}])
def test_malformed_envelope_fails_closed(body):
    with pytest.raises(ClientError, match="malformed"):
        normalize_account_identity(body)


@pytest.mark.parametrize("body", [{"message": "error", "data": {"error_code": 13, "session_key": "DO-NOT-EXPOSE"}}, {"message": "success", "data": {"error_code": 13}}])
def test_expired_session_is_explicit_and_contains_no_payload(body):
    with pytest.raises(ClientError, match="not authenticated") as error:
        normalize_account_identity(body)
    assert "DO-NOT-EXPOSE" not in str(error.value)


@pytest.mark.parametrize("kwargs", [{"expected_username": "ata_clipping"}, {"expected_account_id": "6827268896283624455"}])
def test_expected_account_mismatch_returns_no_identity(kwargs):
    with pytest.raises(ClientError, match="identity mismatch"):
        client(Page()).get_account(**kwargs)


@pytest.mark.parametrize("kwargs", [{"expected_username": "  "}, {"expected_username": "u@example.com"}, {"expected_account_id": "-1"}])
def test_bad_expected_guard_fails_before_browser_read(kwargs):
    page = Page()
    with pytest.raises(ClientError):
        client(page).get_account(**kwargs)
    assert not page.requests


@pytest.mark.parametrize("page", [Page("PRIVATE-CONTACT DO-NOT-EXPOSE", 403), Page("invalid JSON PRIVATE-CONTACT"), Page("[]")])
def test_transport_or_bad_json_errors_never_echo_response_body(page):
    with pytest.raises(ClientError, match="identity request failed") as error:
        client(page).get_account()
    assert "PRIVATE" not in str(error.value) and "DO-NOT-EXPOSE" not in str(error.value)


@pytest.mark.parametrize("failure", [False, True])
def test_cli_uses_requested_profile_and_always_closes_client(monkeypatch, failure):
    seen = []
    closed = []
    class FakeClient:
        def __init__(self):
            from tiktok_cli.config import get_config
            seen.append(get_config().get_active_profile_name())
        def get_account(self, **kwargs):
            assert kwargs == {"expected_username": "itstories", "expected_account_id": None}
            if failure:
                raise ClientError("TikTok account identity mismatch")
            return {"account_id": ACCOUNT_ID, "username": "itstories"}
        def close(self):
            closed.append(True)
    monkeypatch.setattr(account_cmd, "TikTokWebClient", FakeClient)
    result = CliRunner().invoke(app, ["account", "get", "--profile", "clipping", "--expected-username", "itstories"])
    assert seen == ["clipping"]
    assert closed == [True]
    assert result.exit_code == (1 if failure else 0), result.output
    if not failure:
        assert json.loads(result.stdout)["account_id"] == ACCOUNT_ID


def test_account_identity_is_bound_to_tiktok_origin():
    instance = client(Page())
    instance.config.base_url = "https://untrusted.invalid"
    result = instance.get_account()
    assert instance.config.get_browser().urls == ["https://www.tiktok.com/"]
    assert result["provenance"].startswith("https://www.tiktok.com/")


@pytest.mark.parametrize('header',['172801','Tue, 06 Oct 2026 00:00:01 GMT'])
def test_identity_preserves_provider_delay_and_never_retries_before_long_minimum(monkeypatch,header):
    from datetime import datetime,timezone
    import tiktok_cli.studio as studio
    fake=Page('PRIVATE-CONTACT DO-NOT-EXPOSE',429)
    original=fake.evaluate
    def evaluate(script,args):
        result=original(script,args);result['retryAfter']=header;return result
    fake.evaluate=evaluate
    c=client(fake);c._retry_policy=__import__('cli_tools_shared.http_session',fromlist=['RequestsRetryPolicy']).RequestsRetryPolicy(max_retries=3,max_delay=30)
    delays=[];monkeypatch.setattr('tiktok_cli.client.time.sleep',delays.append)
    real=studio.retry_after_seconds
    monkeypatch.setattr(studio,'retry_after_seconds',lambda raw:real(raw,datetime(2026,10,4,tzinfo=timezone.utc)))
    with pytest.raises(ClientError,match='identity request failed') as failure:c.get_account()
    error=failure.value
    assert error.status==429 and error.category=='rate_limit' and error.retry_after_seconds==172801
    assert len(fake.requests)==1 and not delays and 'PRIVATE' not in str(error) and 'DO-NOT-EXPOSE' not in str(error)


@pytest.mark.parametrize('status,category',[(401,'auth'),(403,'auth'),(503,'transient')])
def test_identity_sanitization_preserves_typed_http_failure(status,category):
    with pytest.raises(ClientError,match='identity request failed') as failure:client(Page('SECRET',status)).get_account()
    assert failure.value.category==category and failure.value.status==status and 'SECRET' not in str(failure.value)


def test_unauthenticated_passport_response_has_typed_auth_category():
    with pytest.raises(ClientError,match='not authenticated') as failure:
        normalize_account_identity({'message':'error','data':{'session_key':'DO_NOT_EXPOSE'}})
    assert failure.value.category=='auth' and failure.value.code=='account_not_authenticated'
    assert 'DO_NOT_EXPOSE' not in str(failure.value)
