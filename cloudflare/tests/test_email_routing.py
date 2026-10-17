"""Email Routing contracts: settings, rules (zone-scoped), addresses (account-scoped).

Transport-only fixtures mirroring tests/test_account_tokens.py. No live network
calls; every response is synthesized locally.
"""
import json
from unittest.mock import Mock

import pytest
import requests
import typer
from typer.testing import CliRunner

from cloudflare_cli import client as client_module
from cloudflare_cli.client import CloudflareClient, required_permission_group
from cloudflare_cli.commands import email_routing
from cloudflare_cli.main import app
from cli_tools_shared.exceptions import ClientError


ZONE_ID = "1bb82acebb2c9cc1e8c334e599db915d"
ACCOUNT_ID = "a" * 32
SETTINGS = {"id": "b" * 32, "name": "example.com", "enabled": True, "status": "ready"}
RULE = {
    "id": "c" * 32,
    "name": "Send to user",
    "enabled": True,
    "priority": 0,
    "matchers": [{"type": "literal", "field": "to", "value": "sales@example.com"}],
    "actions": [{"type": "forward", "value": ["dest@example.net"]}],
}
ADDRESS = {"id": "d" * 32, "email": "dest@example.net", "verified": None}


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
    res._content = json.dumps({
        "success": status == 200,
        "result": result,
        "result_info": info,
        "errors": [] if status == 200 else [{"message": "Authentication error"}],
    }).encode()
    return res


# ==================== Settings ====================


def test_get_settings_uses_get(transport):
    transport.return_value = response(SETTINGS)
    assert CloudflareClient().get_email_routing_settings(ZONE_ID) == SETTINGS
    assert transport.call_args.kwargs["url"].endswith(f"/zones/{ZONE_ID}/email/routing")
    assert transport.call_args.kwargs["method"] == "GET"


def test_enable_and_disable_use_post(transport):
    transport.return_value = response(SETTINGS)
    client = CloudflareClient()
    assert client.enable_email_routing(ZONE_ID) == SETTINGS
    assert transport.call_args.kwargs["url"].endswith(f"/zones/{ZONE_ID}/email/routing/enable")
    assert transport.call_args.kwargs["method"] == "POST"

    assert client.disable_email_routing(ZONE_ID) == SETTINGS
    assert transport.call_args.kwargs["url"].endswith(f"/zones/{ZONE_ID}/email/routing/disable")
    assert transport.call_args.kwargs["method"] == "POST"


@pytest.mark.parametrize("value", [None, {}, {"enabled": True}])
def test_malformed_settings_response_fails_clearly(transport, value):
    transport.return_value = response(value)
    with pytest.raises(ClientError, match="expected result object with id"):
        CloudflareClient().get_email_routing_settings(ZONE_ID)


# ==================== Rules ====================


def test_filters_before_limit_across_rule_pages(transport):
    transport.side_effect = [
        response([dict(RULE, name="other")], {"page": 1, "per_page": 1, "total_pages": 2}),
        response([RULE], {"page": 2, "per_page": 1, "total_pages": 2}),
    ]
    assert CloudflareClient().list_email_routing_rules(ZONE_ID, 1, ["name:eq:Send to user"]) == [RULE]
    assert [c.kwargs["params"]["page"] for c in transport.call_args_list] == [1, 2]
    assert [c.kwargs["params"]["per_page"] for c in transport.call_args_list] == [50, 50]


def test_zero_limit_returns_all_rules_and_empty_collection(transport):
    transport.return_value = response([RULE], {"page": 1, "per_page": 50, "total_pages": 1})
    assert CloudflareClient().list_email_routing_rules(ZONE_ID, 0) == [RULE]
    transport.return_value = response([], {"page": 1, "per_page": 50, "total_pages": 1})
    assert CloudflareClient().list_email_routing_rules(ZONE_ID, 0) == []


def test_rules_list_sends_enabled_filter_param(transport):
    transport.return_value = response([RULE], {"page": 1, "per_page": 50, "total_pages": 1})
    CloudflareClient().list_email_routing_rules(ZONE_ID, enabled=True)
    assert transport.call_args.kwargs["params"]["enabled"] is True


def test_get_rule_uses_get(transport):
    transport.return_value = response(RULE)
    assert CloudflareClient().get_email_routing_rule(ZONE_ID, RULE["id"]) == RULE
    assert transport.call_args.kwargs["url"].endswith(f"/zones/{ZONE_ID}/email/routing/rules/{RULE['id']}")
    assert transport.call_args.kwargs["method"] == "GET"


def test_create_rule_sends_matchers_and_actions(transport):
    transport.return_value = response(RULE)
    client = CloudflareClient()
    result = client.create_email_routing_rule(
        ZONE_ID,
        matchers=[{"type": "literal", "field": "to", "value": "sales@example.com"}],
        actions=[{"type": "forward", "value": ["dest@example.net"]}],
        name="Send to user",
        enabled=True,
        priority=0,
    )
    assert result == RULE
    call = transport.call_args
    assert call.kwargs["method"] == "POST"
    assert call.kwargs["url"].endswith(f"/zones/{ZONE_ID}/email/routing/rules")
    assert call.kwargs["json"]["matchers"][0]["value"] == "sales@example.com"
    assert call.kwargs["json"]["actions"][0]["type"] == "forward"
    assert call.kwargs["json"]["name"] == "Send to user"


def test_update_rule_sends_only_provided_fields(transport):
    transport.return_value = response(dict(RULE, enabled=False))
    client = CloudflareClient()
    client.update_email_routing_rule(ZONE_ID, RULE["id"], enabled=False)
    call = transport.call_args
    assert call.kwargs["method"] == "PUT"
    assert call.kwargs["url"].endswith(f"/zones/{ZONE_ID}/email/routing/rules/{RULE['id']}")
    assert call.kwargs["json"] == {"enabled": False}


def test_delete_rule_uses_delete(transport):
    transport.return_value = response({"id": RULE["id"]})
    assert CloudflareClient().delete_email_routing_rule(ZONE_ID, RULE["id"]) == {"id": RULE["id"]}
    assert transport.call_args.kwargs["method"] == "DELETE"


@pytest.mark.parametrize("value", [None, {}, ["invalid"]])
def test_malformed_rules_list_response_fails_clearly(transport, value):
    transport.return_value = response(value)
    with pytest.raises(ClientError, match="expected result array of objects"):
        CloudflareClient().list_email_routing_rules(ZONE_ID)


def test_malformed_rules_pagination_fails_clearly(transport):
    transport.return_value = response([RULE], {"page": 1})
    with pytest.raises(ClientError, match="Invalid Email Routing rule pagination"):
        CloudflareClient().list_email_routing_rules(ZONE_ID, 0)


# ==================== Destination Addresses ====================


def test_filters_before_limit_across_address_pages(transport):
    transport.side_effect = [
        response([dict(ADDRESS, email="other@example.net")], {"page": 1, "per_page": 1, "total_pages": 2}),
        response([ADDRESS], {"page": 2, "per_page": 1, "total_pages": 2}),
    ]
    assert CloudflareClient().list_email_routing_addresses(ACCOUNT_ID, 1, ["email:eq:dest@example.net"]) == [ADDRESS]


def test_addresses_list_sends_verified_filter_param(transport):
    transport.return_value = response([ADDRESS], {"page": 1, "per_page": 50, "total_pages": 1})
    CloudflareClient().list_email_routing_addresses(ACCOUNT_ID, verified=False)
    assert transport.call_args.kwargs["params"]["verified"] is False


def test_get_address_uses_get(transport):
    transport.return_value = response(ADDRESS)
    assert CloudflareClient().get_email_routing_address(ACCOUNT_ID, ADDRESS["id"]) == ADDRESS
    assert transport.call_args.kwargs["url"].endswith(f"/accounts/{ACCOUNT_ID}/email/routing/addresses/{ADDRESS['id']}")


def test_create_address_sends_email_and_does_not_retry(transport):
    transport.return_value = response(ADDRESS)
    client = CloudflareClient()
    result = client.create_email_routing_address(ACCOUNT_ID, "dest@example.net")
    assert result == ADDRESS
    call = transport.call_args
    assert call.kwargs["method"] == "POST"
    assert call.kwargs["url"].endswith(f"/accounts/{ACCOUNT_ID}/email/routing/addresses")
    assert call.kwargs["json"] == {"email": "dest@example.net"}


def test_create_address_rejects_empty_email(transport):
    with pytest.raises(ClientError, match="must not be empty"):
        CloudflareClient().create_email_routing_address(ACCOUNT_ID, "  ")
    assert transport.call_count == 0


def test_create_address_failure_names_the_list_command_to_check(transport):
    transport.return_value = response(None, status=403)
    with pytest.raises(ClientError, match="email-routing addresses list"):
        CloudflareClient().create_email_routing_address(ACCOUNT_ID, "dest@example.net")
    assert transport.call_count == 1


def test_delete_address_uses_delete(transport):
    transport.return_value = response({"id": ADDRESS["id"]})
    assert CloudflareClient().delete_email_routing_address(ACCOUNT_ID, ADDRESS["id"]) == {"id": ADDRESS["id"]}
    assert transport.call_args.kwargs["method"] == "DELETE"


@pytest.mark.parametrize("value", [None, {}, ["invalid"]])
def test_malformed_addresses_list_response_fails_clearly(transport, value):
    transport.return_value = response(value)
    with pytest.raises(ClientError, match="expected result array of objects"):
        CloudflareClient().list_email_routing_addresses(ACCOUNT_ID)


# ==================== Permission group mapping ====================


@pytest.mark.parametrize(
    "method, endpoint, expected",
    [
        ("GET", f"/zones/{ZONE_ID}/email/routing/rules", "Zone > Email Routing Rules > Read"),
        ("POST", f"/zones/{ZONE_ID}/email/routing/rules", "Zone > Email Routing Rules > Edit"),
        ("DELETE", f"/zones/{ZONE_ID}/email/routing/rules/{RULE['id']}", "Zone > Email Routing Rules > Edit"),
        (
            "GET",
            f"/accounts/{ACCOUNT_ID}/email/routing/addresses",
            "Account > Email Routing Addresses > Read",
        ),
        (
            "POST",
            f"/accounts/{ACCOUNT_ID}/email/routing/addresses",
            "Account > Email Routing Addresses > Edit",
        ),
        ("GET", f"/zones/{ZONE_ID}/email/routing", "Zone > Zone Settings > Read"),
        ("POST", f"/zones/{ZONE_ID}/email/routing/enable", "Zone > Zone Settings > Edit"),
        ("POST", f"/zones/{ZONE_ID}/email/routing/disable", "Zone > Zone Settings > Edit"),
    ],
)
def test_required_permission_group_for_email_routing(method, endpoint, expected):
    """The specific rules/addresses fragments must win over the generic
    "/email/routing" settings fragment, since the latter is a substring of
    every email-routing endpoint."""
    assert required_permission_group(method, endpoint) == expected


# ==================== CLI matcher/action building ====================


def test_build_matchers_and_actions_shortcuts():
    assert email_routing._build_matchers("sales@example.com", False, None) == [
        {"type": "literal", "field": "to", "value": "sales@example.com"}
    ]
    assert email_routing._build_matchers(None, True, None) == [{"type": "all"}]
    assert email_routing._build_actions("dest@example.net", False, None) == [
        {"type": "forward", "value": ["dest@example.net"]}
    ]
    assert email_routing._build_actions(None, True, None) == [{"type": "drop"}]


def test_build_matchers_and_actions_json_overrides():
    matchers = email_routing._build_matchers(None, False, '[{"type": "literal", "field": "to", "value": "x@example.com"}]')
    assert matchers == [{"type": "literal", "field": "to", "value": "x@example.com"}]
    actions = email_routing._build_actions(None, False, '[{"type": "worker", "value": ["my-worker"]}]')
    assert actions == [{"type": "worker", "value": ["my-worker"]}]


def test_build_matchers_and_actions_require_a_choice():
    with pytest.raises(typer.BadParameter):
        email_routing._build_matchers(None, False, None)
    with pytest.raises(typer.BadParameter):
        email_routing._build_actions(None, False, None)


def test_build_matchers_rejects_invalid_json():
    with pytest.raises(typer.BadParameter):
        email_routing._build_matchers(None, False, "not json")


# ==================== CLI-level: JSON/table output, no bearer leak ====================


def test_cli_settings_and_rules_json_never_print_bearer(monkeypatch, transport):
    monkeypatch.setattr(email_routing, "get_client", CloudflareClient)
    runner = CliRunner()

    transport.return_value = response(SETTINGS)
    result = runner.invoke(email_routing.app, ["settings", "get", ZONE_ID])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == SETTINGS
    assert "fixture-private-bearer" not in result.output

    transport.return_value = response([RULE], {"page": 1, "per_page": 50, "total_pages": 1})
    result = runner.invoke(email_routing.app, ["rules", "list", ZONE_ID, "--table", "--properties", "name"])
    assert result.exit_code == 0, result.output
    assert "Send to user" in result.stdout
    assert RULE["id"] not in result.stdout
    assert "fixture-private-bearer" not in result.output

    transport.return_value = response(None, status=403)
    result = runner.invoke(email_routing.app, ["rules", "list", ZONE_ID])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "fixture-private-bearer" not in result.output
    assert "Zone > Email Routing Rules > Read" in result.stderr


def test_cli_rules_create_forward_requires_address_or_catch_all(monkeypatch, transport):
    monkeypatch.setattr(email_routing, "get_client", CloudflareClient)
    transport.return_value = response(SETTINGS)  # resolve_zone_id short-circuits on hex zone id, unused
    runner = CliRunner()
    result = runner.invoke(email_routing.app, ["rules", "create", ZONE_ID, "--forward-to", "dest@example.net"])
    assert result.exit_code != 0
    assert "--address" in result.output or "--catch-all" in result.output or "--matchers-json" in result.output


def test_cli_addresses_create_and_delete_with_force(monkeypatch, transport):
    monkeypatch.setattr(email_routing, "get_client", CloudflareClient)
    runner = CliRunner()

    transport.return_value = response(ADDRESS)
    result = runner.invoke(email_routing.app, ["addresses", "create", "dest@example.net", ACCOUNT_ID])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == ADDRESS
    assert "verification link" in result.stderr

    transport.return_value = response({"id": ADDRESS["id"]})
    result = runner.invoke(email_routing.app, ["addresses", "delete", ADDRESS["id"], ACCOUNT_ID, "--force"])
    assert result.exit_code == 0, result.output
    assert ADDRESS["id"] in result.stderr


def test_cli_addresses_delete_without_force_refuses_noninteractive(monkeypatch, transport):
    monkeypatch.setattr(email_routing, "get_client", CloudflareClient)
    runner = CliRunner()
    result = runner.invoke(email_routing.app, ["addresses", "delete", ADDRESS["id"], ACCOUNT_ID])
    assert result.exit_code != 0
    assert transport.call_count == 0
    assert "--force" in result.output


def test_cli_rules_update_disabled_alone_sends_enabled_false(monkeypatch, transport):
    monkeypatch.setattr(email_routing, "get_client", CloudflareClient)
    transport.return_value = response(dict(RULE, enabled=False))
    runner = CliRunner()
    result = runner.invoke(email_routing.app, ["rules", "update", ZONE_ID, RULE["id"], "--disabled"])
    assert result.exit_code == 0, result.output
    assert transport.call_args.kwargs["json"] == {"enabled": False}


def test_cli_rules_update_priority_zero_alone_sends_priority_zero(monkeypatch, transport):
    monkeypatch.setattr(email_routing, "get_client", CloudflareClient)
    transport.return_value = response(dict(RULE, priority=0))
    runner = CliRunner()
    result = runner.invoke(email_routing.app, ["rules", "update", ZONE_ID, RULE["id"], "--priority", "0"])
    assert result.exit_code == 0, result.output
    assert transport.call_args.kwargs["json"] == {"priority": 0}


def test_cli_rules_update_with_no_fields_still_errors(monkeypatch, transport):
    monkeypatch.setattr(email_routing, "get_client", CloudflareClient)
    runner = CliRunner()
    result = runner.invoke(email_routing.app, ["rules", "update", ZONE_ID, RULE["id"]])
    assert result.exit_code != 0
    assert transport.call_count == 0
    assert "At least one field to update must be specified" in result.output


def test_public_groups_exist():
    result = CliRunner().invoke(app, ["email-routing", "--help"])
    assert result.exit_code == 0, result.output
    assert "settings" in result.stdout
    assert "rules" in result.stdout
    assert "addresses" in result.stdout
