"""Queue contracts at the CLI and HTTP boundaries; no live mutations."""
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
QUEUE = {"queue_id": "b" * 32, "queue_name": "issue-manager", "consumers": []}
CONSUMER = {"consumer_id": "c" * 32, "type": "http_pull", "settings": {"batch_size": 1, "visibility_timeout_ms": 30000}}


@pytest.fixture
def transport(monkeypatch):
    config = Mock(api_key="fixture-token", base_url="https://api.cloudflare.com/client/v4")
    config.has_credentials.return_value = True
    monkeypatch.setattr(client_module, "get_config", lambda: config)
    request = Mock()
    monkeypatch.setattr(client_module.requests, "request", request)
    return request


def response(result, status=200, success=True, result_info=None):
    res = requests.Response()
    res.status_code = status
    res._content = json.dumps({"success": success, "result": result, "errors": [], "result_info": result_info}).encode()
    return res


def test_should_expose_queues_at_public_boundary():
    result = CliRunner().invoke(app, ["queues", "--help"])
    assert result.exit_code == 0, result.output
    assert "create" in result.output
    assert "list" in result.output
    assert "get" in result.output


def test_should_follow_pages_before_filter_and_limit(transport):
    transport.side_effect = [
        response([{"queue_id": "other", "queue_name": "other"}], result_info={"page": 1, "total_pages": 2}),
        response([QUEUE], result_info={"page": 2, "total_pages": 2}),
    ]
    rows = CloudflareClient().list_queues(ACCOUNT, limit=1, filters=["queue_name:eq:issue-manager"])
    assert rows == [QUEUE]
    assert [call.kwargs["params"] for call in transport.call_args_list] == [{"page": 1}, {"page": 2}]


def test_should_return_all_queues_with_zero_limit(transport):
    queues = [{"queue_id": str(i), "queue_name": str(i)} for i in range(150)]
    transport.return_value = response(queues)
    assert CloudflareClient().list_queues(ACCOUNT, limit=0) == queues


def test_should_return_every_page_with_zero_limit(transport):
    other = {"queue_id": "other", "queue_name": "other"}
    transport.side_effect = [
        response([other], result_info={"page": 1, "total_pages": 2}),
        response([QUEUE], result_info={"page": 2, "total_pages": 2}),
    ]
    assert CloudflareClient().list_queues(ACCOUNT, limit=0) == [other, QUEUE]


def test_should_reject_nonadvancing_page_metadata(transport):
    transport.return_value = response([QUEUE], result_info={"page": 0, "total_pages": 2})
    with pytest.raises(ClientError, match="page did not advance"):
        CloudflareClient().list_queues(ACCOUNT, limit=0)


def test_should_stop_after_matching_limit(transport):
    transport.return_value = response([QUEUE], result_info={"page": 1, "total_pages": 2})
    assert CloudflareClient().list_queues(ACCOUNT, limit=1) == [QUEUE]
    assert transport.call_count == 1


def test_should_get_queue_by_id(transport):
    transport.return_value = response(QUEUE)
    assert CloudflareClient().get_queue(ACCOUNT, QUEUE["queue_id"]) == QUEUE
    assert transport.call_args.kwargs["url"] == f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/queues/{QUEUE['queue_id']}"


@pytest.mark.parametrize("jurisdiction", [None, "eu", "us", "fedramp"])
def test_should_create_queue_with_native_body(transport, jurisdiction):
    transport.return_value = response(QUEUE)
    assert CloudflareClient().create_queue(ACCOUNT, "issue-manager", jurisdiction) == QUEUE
    expected = {"queue_name": "issue-manager"}
    if jurisdiction is not None:
        expected["jurisdiction"] = jurisdiction
    assert transport.call_args.kwargs["method"] == "POST"
    assert transport.call_args.kwargs["json"] == expected
    assert transport.call_args.kwargs["headers"]["Authorization"] == "Bearer fixture-token"


@pytest.mark.parametrize("failure", [requests.Timeout("fixture timeout"), response(None, 503, False)])
def test_should_never_retry_ambiguous_creation(transport, failure):
    transport.side_effect = failure if isinstance(failure, Exception) else [failure]
    with pytest.raises(ClientError, match="Check.*queues list.*before retrying"):
        CloudflareClient().create_queue(ACCOUNT, "issue-manager")
    assert transport.call_count == 1


def test_should_reject_missing_result_after_create_without_retry(transport):
    res = requests.Response()
    res.status_code = 200
    res._content = b"{}"
    transport.return_value = res
    with pytest.raises(ClientError, match="Check.*queues list.*before retrying"):
        CloudflareClient().create_queue(ACCOUNT, "issue-manager")
    assert transport.call_count == 1


@pytest.mark.parametrize("method,permission", [("GET", "Queues Read"), ("POST", "Queues Write")])
def test_should_name_queue_permission(method, permission):
    assert permission in required_permission_group(method, f"/accounts/{ACCOUNT}/queues")


def test_should_emit_cli_json_and_project_table_properties(monkeypatch, transport):
    from cloudflare_cli.commands import queues
    transport.return_value = response([QUEUE])
    monkeypatch.setattr(queues, "get_client", CloudflareClient)
    result = CliRunner().invoke(queues.app, ["list", ACCOUNT, "--properties", "queue_id,queue_name"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"queue_id": QUEUE["queue_id"], "queue_name": "issue-manager"}]
    result = CliRunner().invoke(queues.app, ["list", ACCOUNT, "--table", "--properties", "queue_name"])
    assert result.exit_code == 0, result.output
    assert "issue-manager" in result.stdout
    assert QUEUE["queue_id"] not in result.stdout


def test_should_create_then_get_through_cli(monkeypatch, transport):
    from cloudflare_cli.commands import queues
    transport.return_value = response(QUEUE)
    monkeypatch.setattr(queues, "get_client", CloudflareClient)
    runner = CliRunner()
    created = runner.invoke(queues.app, ["create", "issue-manager", ACCOUNT, "--jurisdiction", "us"])
    assert created.exit_code == 0, created.output
    queue_id = json.loads(created.stdout)["queue_id"]
    fetched = runner.invoke(queues.app, ["get", queue_id, ACCOUNT])
    assert fetched.exit_code == 0, fetched.output
    assert json.loads(fetched.stdout) == QUEUE


def test_should_reject_invalid_jurisdiction_without_request(transport):
    result = CliRunner().invoke(app, ["queues", "create", "issue-manager", ACCOUNT, "--jurisdiction", "invalid"])
    assert result.exit_code != 0
    assert "invalid" in result.output
    transport.assert_not_called()


def test_should_expose_consumer_commands():
    result = CliRunner().invoke(app, ["queues", "consumers", "--help"])
    assert result.exit_code == 0, result.output
    assert "create" in result.output


def test_should_list_existing_consumers_before_filter_limit(transport):
    transport.return_value = response([{"consumer_id": "worker", "type": "worker"}, CONSUMER])
    rows = CloudflareClient().list_queue_consumers(ACCOUNT, QUEUE["queue_id"], limit=1, filters=["type:eq:http_pull"])
    assert rows == [CONSUMER]
    assert transport.call_args.kwargs["url"].endswith(f"/queues/{QUEUE['queue_id']}/consumers")


def test_should_get_consumer_by_native_endpoint(transport):
    transport.return_value = response(CONSUMER)
    assert CloudflareClient().get_queue_consumer(ACCOUNT, QUEUE["queue_id"], CONSUMER["consumer_id"]) == CONSUMER
    assert transport.call_args.kwargs["url"].endswith(f"/queues/{QUEUE['queue_id']}/consumers/{CONSUMER['consumer_id']}")


def test_should_create_http_pull_consumer_with_only_supplied_settings(transport):
    transport.return_value = response(CONSUMER)
    result = CloudflareClient().create_queue_http_consumer(ACCOUNT, QUEUE["queue_id"], batch_size=1, max_retries=0, visibility_timeout_ms=30000)
    assert result == CONSUMER
    assert transport.call_args.kwargs["json"] == {"type": "http_pull", "settings": {"batch_size": 1, "max_retries": 0, "visibility_timeout_ms": 30000}}
    assert transport.call_args.kwargs["method"] == "POST"


def test_should_omit_unset_consumer_settings(transport):
    transport.return_value = response(CONSUMER)
    CloudflareClient().create_queue_http_consumer(ACCOUNT, QUEUE["queue_id"])
    assert transport.call_args.kwargs["json"] == {"type": "http_pull"}


@pytest.mark.parametrize("failure", [requests.Timeout("fixture timeout"), response(None, 503, False), response({})])
def test_should_not_retry_consumer_creation_after_uncertain_response(transport, failure):
    transport.side_effect = failure if isinstance(failure, Exception) else [failure]
    with pytest.raises(ClientError, match="Check.*queues consumers list.*before retrying"):
        CloudflareClient().create_queue_http_consumer(ACCOUNT, QUEUE["queue_id"])
    assert transport.call_count == 1


@pytest.mark.parametrize("envelope", [[], None, "invalid", 42, True])
def test_should_preserve_consumer_recovery_guidance_for_non_object_envelope(transport, envelope):
    res = requests.Response()
    res.status_code = 200
    res._content = json.dumps(envelope).encode()
    transport.return_value = res

    with pytest.raises(ClientError, match="Check.*queues consumers list.*before retrying"):
        CloudflareClient().create_queue_http_consumer(ACCOUNT, QUEUE["queue_id"])

    assert transport.call_count == 1


def test_should_exercise_consumer_cli_create_get_list(monkeypatch, transport):
    from cloudflare_cli.commands import queues
    monkeypatch.setattr(queues, "get_client", CloudflareClient)
    transport.return_value = response(CONSUMER)
    runner = CliRunner()
    created = runner.invoke(queues.consumers_app, ["create", QUEUE["queue_id"], ACCOUNT, "--batch-size", "1", "--visibility-timeout-ms", "30000"])
    assert created.exit_code == 0, created.output
    assert json.loads(created.stdout) == CONSUMER
    fetched = runner.invoke(queues.consumers_app, ["get", QUEUE["queue_id"], CONSUMER["consumer_id"], ACCOUNT])
    assert fetched.exit_code == 0, fetched.output
    assert json.loads(fetched.stdout) == CONSUMER
    transport.return_value = response([CONSUMER])
    listed = runner.invoke(queues.consumers_app, ["list", QUEUE["queue_id"], ACCOUNT, "--table", "--properties", "consumer_id,type"])
    assert listed.exit_code == 0, listed.output
    assert CONSUMER["consumer_id"] in listed.stdout
    assert "http_pull" in listed.stdout
