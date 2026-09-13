"""Account-token metadata contracts, with transport-only fixtures."""
import json
from unittest.mock import Mock

import pytest
import requests
from typer.testing import CliRunner

from cloudflare_cli import client as client_module
from cloudflare_cli.client import CloudflareClient, required_permission_group
from cloudflare_cli.main import app
from cli_tools_shared.exceptions import ClientError


ACCOUNT = "a" * 32
TOKEN = {"id": "b" * 32, "name": "service", "status": "active", "policies": []}
PERMISSION = {"id": "c" * 32, "name": "Queues Write", "scopes": ["com.cloudflare.api.account"]}


@pytest.fixture
def transport(monkeypatch):
    config = Mock(api_key="fixture-private-bearer", base_url="https://api.cloudflare.com/client/v4")
    config.has_credentials.return_value = True
    monkeypatch.setattr(client_module, "get_config", lambda: config)
    request = Mock()
    monkeypatch.setattr(client_module.requests, "request", request)
    return request


def response(result, info=None, status=200):
    res = requests.Response()
    res.status_code = status
    res._content = json.dumps({"success": status == 200, "result": result, "result_info": info,
                               "errors": [] if status == 200 else [{"message": "Authentication error"}]}).encode()
    return res


def test_public_group_exists():
    result = CliRunner().invoke(app, ["account-tokens", "--help"])
    assert result.exit_code == 0, result.output
    assert "permissions" in result.stdout


def test_filters_before_limit_across_token_pages(transport):
    transport.side_effect = [
        response([dict(TOKEN, name="other")], {"page": 1, "per_page": 1, "total_count": 2}),
        response([TOKEN], {"page": 2, "per_page": 1, "total_count": 2}),
    ]
    assert CloudflareClient().list_account_tokens(ACCOUNT, 1, ["name:eq:service"]) == [TOKEN]
    assert [c.kwargs["params"] for c in transport.call_args_list] == [
        {"page": 1, "per_page": 50}, {"page": 2, "per_page": 50}]
    assert [c.kwargs["method"] for c in transport.call_args_list] == ["GET", "GET"]


def test_zero_limit_returns_all_and_empty_collection(transport):
    transport.return_value = response([TOKEN], {"page": 1, "per_page": 50, "total_count": 1})
    assert CloudflareClient().list_account_tokens(ACCOUNT, 0) == [TOKEN]
    transport.return_value = response([], {"page": 1, "per_page": 50, "total_count": 0})
    assert CloudflareClient().list_account_tokens(ACCOUNT, 0) == []


def test_get_token_metadata_uses_get(transport):
    transport.return_value = response(TOKEN)
    assert CloudflareClient().get_account_token(ACCOUNT, TOKEN["id"]) == TOKEN
    assert transport.call_args.kwargs["url"].endswith(f"/accounts/{ACCOUNT}/tokens/{TOKEN['id']}")
    assert transport.call_args.kwargs["method"] == "GET"


def test_catalog_filter_and_id_lookup(transport):
    transport.return_value = response([dict(PERMISSION, id="other", name="Other"), PERMISSION])
    client = CloudflareClient()
    assert client.list_account_token_permissions(ACCOUNT, 1, ["name:eq:Queues Write"]) == [PERMISSION]
    assert client.get_account_token_permission(ACCOUNT, PERMISSION["id"]) == PERMISSION
    assert transport.call_args.kwargs["params"] is None
    assert transport.call_args.kwargs["url"].endswith("/tokens/permission_groups")
    with pytest.raises(ClientError, match="Permission group not found"):
        client.get_account_token_permission(ACCOUNT, "missing")


@pytest.mark.parametrize("value", [None, {}, ["invalid"]])
def test_malformed_catalog_fails_clearly(transport, value):
    transport.return_value = response(value)
    with pytest.raises(ClientError, match="expected result array of objects"):
        CloudflareClient().list_account_token_permissions(ACCOUNT)


def test_malformed_pagination_fails_clearly(transport):
    transport.return_value = response([TOKEN], {"page": 1})
    with pytest.raises(ClientError, match="Invalid account-token pagination"):
        CloudflareClient().list_account_tokens(ACCOUNT, 0)


def test_read_refusal_names_read_permission_without_claiming_write(transport):
    transport.return_value = response(None, status=403)
    with pytest.raises(ClientError, match="Account API Tokens Read or Account API Tokens Write"):
        CloudflareClient().list_account_tokens(ACCOUNT)
    assert transport.call_count == 1
    assert required_permission_group("POST", f"/accounts/{ACCOUNT}/tokens") == "Account API Tokens Write"


def test_cli_json_table_and_errors_never_print_bearer(monkeypatch, transport):
    from cloudflare_cli.commands import account_tokens
    monkeypatch.setattr(account_tokens, "get_client", CloudflareClient)
    transport.return_value = response([TOKEN], {"page": 1, "per_page": 50, "total_count": 1})
    runner = CliRunner()
    result = runner.invoke(account_tokens.app, ["list", ACCOUNT, "--properties", "id,name"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"id": TOKEN["id"], "name": "service"}]
    assert "fixture-private-bearer" not in result.output
    transport.return_value = response([PERMISSION])
    result = runner.invoke(account_tokens.app, ["permissions", "list", ACCOUNT, "--table", "--properties", "name"])
    assert result.exit_code == 0, result.output
    assert "Queues Write" in result.stdout
    assert PERMISSION["id"] not in result.stdout
    transport.return_value = response(None, status=403)
    result = runner.invoke(account_tokens.app, ["list", ACCOUNT])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "fixture-private-bearer" not in result.output
    assert "Account API Tokens Read" in result.stderr
