"""Offline contract tests; no live advertising mutations or spend."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import facebook_business.adobjects
from facebook_business.api import FacebookAdsApi
from facebook_business.session import FacebookSession
import pytest
import requests
from typer.testing import CliRunner
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.http_session import RequestsRetryPolicy

from facebook_ads_cli.catalog import catalog, resource_class, schema
from facebook_ads_cli.client import FacebookAdsClient, GraphSession, native_filters, redact
from facebook_ads_cli.main import app


@pytest.fixture
def client():
    config = SimpleNamespace(personal_access_token="TEST_TOKEN")
    return FacebookAdsClient(config=config, api=FacebookAdsApi(FacebookSession(), api_version="v26.0"))


def test_manifest_covers_every_generated_request_and_builds_schema():
    expected = set()
    root = Path(facebook_business.adobjects.__file__).parent
    for source in root.glob("*.py"):
        if source.stem.startswith("abstract"):
            continue
        for cls in (n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef)):
            for method in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
                if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "FacebookRequest"
                       for n in ast.walk(method)):
                    expected.add((cls.name, method.name))
    actual = {(name, method) for name, record in catalog().items() for method in record["methods"]}
    assert actual == expected
    assert len(actual) == 1503
    assert len(catalog()) == 1105
    assert sum(bool(record["methods"]) for record in catalog().values()) == 362
    for name in catalog():
        json.dumps(schema(name))
    assert "spend" in schema("AdsInsights")["fields"]
    for name, method in actual:
        entry = schema(name, method)
        json.dumps(entry)
        assert entry["operation"]["method"] in {"GET", "POST", "DELETE", "PUT", "PATCH"}
        assert entry["operation"]["endpoint"]
    assert "api_get" in catalog()["Campaign"]["methods"]
    assert "get_endpoint" not in catalog()["Campaign"]["methods"]
    assert "today" in schema("AdAccount", "get_insights")["operation"]["enums"]["date_preset_enum"]


def test_sdk_call_uses_official_request_and_preserves_fields(client, monkeypatch):
    cls = resource_class("Campaign")
    request = Mock()
    request.execute.return_value = SimpleNamespace(export_all_data=lambda: {"id": "123", "unknown_new_field": {"x": 1}})
    method = Mock(return_value=request)
    monkeypatch.setattr(cls, "api_get", method)
    result = client.call("Campaign", "api_get", "123", fields=["id"])
    assert result["unknown_new_field"] == {"x": 1}
    assert method.call_args.kwargs == {"params": {"limit": 100}, "pending": True, "fields": ["id"]}


def test_mutation_guard_precedes_sdk_construction(client):
    with pytest.raises(ClientError, match="Mutation requires"):
        client.call("Campaign", "api_update", "123", {"status": "ACTIVE"})
    dry = client.call("Campaign", "api_update", "123", {"status": "PAUSED"}, dry_run=True)
    assert dry["method"] == "POST"
    assert dry["params"]["status"] == "PAUSED"


@pytest.mark.parametrize("path", ["https://evil.example/", "//evil.example/../me", "me?access_token=x", "../me", "me\\evil"])
def test_graph_path_rejection(client, path):
    with pytest.raises(ClientError):
        client.graph("GET", path)


@pytest.mark.parametrize("url", ["http://graph.facebook.com/me", "https://evil.example/me", "https://graph.facebook.com.evil.example/me", "https://user@graph.facebook.com/me"])
def test_transport_blocks_credential_leak(url):
    with pytest.raises(ClientError, match="Only https"):
        GraphSession(RequestsRetryPolicy()).request("GET", url)


def response(status, body=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body or {}).encode()
    return result


def test_get_retry_but_mutations_single_attempt(monkeypatch):
    calls = []
    replies = iter([response(503), response(200), response(503)])
    def send(self, method, url, **kwargs):
        calls.append((method, kwargs))
        return next(replies)
    monkeypatch.setattr(requests.Session, "request", send)
    session = GraphSession(RequestsRetryPolicy(max_retries=2, base_delay=0, jitter=0))
    assert session.request("GET", "https://graph.facebook.com/v26.0/me").status_code == 200
    assert session.request("POST", "https://graph.facebook.com/v26.0/me").status_code == 503
    assert [row[0] for row in calls] == ["GET", "GET", "POST"]
    assert all(row[1]["allow_redirects"] is False for row in calls)


def test_redirect_refused(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *args, **kwargs: response(302))
    with pytest.raises(ClientError, match="redirect refused"):
        GraphSession(RequestsRetryPolicy()).request("GET", "https://graph.facebook.com/me")


def test_graph_upload_closes_file_and_preserves_response(client, tmp_path):
    path = tmp_path / "image.jpg"
    path.write_bytes(b"IMAGE")
    captured = {}
    def call(method, tokens, **kwargs):
        captured.update(kwargs)
        assert kwargs["files"]["filename"].read() == b"IMAGE"
        return SimpleNamespace(json=lambda: {"images": {"hash": "a"}, "new": 2})
    client.api.call = call
    result = client.graph("POST", "act_1/adimages", files={"filename": str(path)}, yes=True)
    assert result["new"] == 2
    assert captured["files"]["filename"].closed


def test_native_filters_validate_and_translate():
    assert native_filters(["spend:gt:3", "status:in:ACTIVE|PAUSED"]) == [
        {"field": "spend", "operator": "GREATER_THAN", "value": 3},
        {"field": "status", "operator": "IN", "value": ["ACTIVE", "PAUSED"]}]
    with pytest.raises(ClientError, match="no supported Meta translation"):
        native_filters(["name:like:%x%"])


def test_server_cursor_paging_preserves_rows_and_limit(client):
    calls = []
    def graph(method, path, params):
        calls.append(dict(params))
        if len(calls) == 1:
            return {"data": [{"id": 1}], "paging": {"next": "yes", "cursors": {"after": "A"}}}
        return {"data": [{"id": 2}]}
    client.graph = graph
    assert client.list_edge("act_1", "campaigns", 2, ["status:PAUSED"]) == [{"id": 1}, {"id": 2}]
    assert [v["limit"] for v in calls] == [2, 1]
    assert calls[1]["after"] == "A"
    assert calls[0]["filtering"][0]["operator"] == "EQUAL"


def test_repeated_cursor_fails_explicitly(client):
    client.graph = lambda *args: {"data": [{"id": "1"}], "paging": {"next": "yes", "cursors": {"after": "A"}}}
    with pytest.raises(ClientError, match="repeated"):
        client.list_edge("act_1", "campaigns", 4)


def test_batch_reports_individual_errors_and_guard(client):
    client.graph = Mock(return_value=[{"code": 200, "body": '{"id":"1"}'}, {"code": 400, "body": '{"error":{"message":"bad"}}'}])
    rows, failed = client.batch([{"method": "GET", "relative_url": "me"}, {"method": "GET", "relative_url": "missing"}])
    assert failed and rows[0]["body"]["id"] == "1"
    assert rows[1]["body"]["error"]["message"] == "bad"
    with pytest.raises(ClientError, match="Mutation requires"):
        client.batch([{"method": "POST", "relative_url": "act_1/campaigns"}])
    with pytest.raises(ClientError, match="1..50"):
        client.batch([])


def test_async_wait_success_failure_and_timeout(client, monkeypatch):
    client.graph = lambda *args: {"async_status": "Job Completed"}
    assert client.wait_report("1")["async_status"] == "Job Completed"
    client.graph = lambda *args: {"async_status": "Job Failed"}
    with pytest.raises(ClientError, match="Job Failed"):
        client.wait_report("1")
    client.graph = lambda *args: {"async_status": "Job Running"}
    clock = iter([100.0, 101.0])
    monkeypatch.setattr("facebook_ads_cli.client.time.monotonic", lambda: next(clock))
    with pytest.raises(ClientError, match="timed out"):
        client.wait_report("1", timeout=0.01)


def test_redaction_nested_token_and_paging_url():
    data = redact({"access_token": "SECRET", "paging": {"next": "https://graph.facebook.com/x?access_token=SECRET&after=A"}})
    assert "SECRET" not in json.dumps(data)
    assert "after=A" in data["paging"]["next"]


def test_cli_discovery_and_unauthed_dry_run():
    runner = CliRunner()
    result = runner.invoke(app, ["sdk", "resources", "list", "--filter", "name:eq:Campaign", "--properties", "name"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"name": "Campaign"}]
    result = runner.invoke(app, ["campaigns", "create", "act_1", "--params", '{"status":"PAUSED"}', "--dry-run"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["params"]["status"] == "PAUSED"
    result = runner.invoke(app, ["sdk", "call", "Campaign", "api_update", "1", "--params", '{"status":"PAUSED"}', "--dry-run"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["operation"] == "api_update"


def test_sdk_cursor_pages_send_server_limit(client):
    calls = []
    def api_call(method, path, params=None, **kwargs):
        calls.append(dict(params or {}))
        data = {"data": [{"id": "1", "custom": "preserved"}], "paging": {"next": "x", "cursors": {"after": "A"}}} if len(calls) == 1 else {"data": [{"id": "2"}]}
        return SimpleNamespace(json=lambda: data, headers=lambda: {}, error=lambda: None)
    client.api.call = api_call
    rows = client.call("AdAccount", "get_campaigns", "act_1", all_pages=True, max_items=2)
    assert [row["id"] for row in rows] == ["1", "2"]
    assert rows[0]["custom"] == "preserved"
    assert calls[0]["limit"] == 2
    assert calls[1]["after"] == "A"


def test_list_limit_survives_oversized_server_response(client):
    client.graph = lambda *args: {"data": [{"id": x} for x in range(20)]}
    assert client.list_edge("act_1", "campaigns", 2) == [{"id": 0}, {"id": 1}]


def test_batch_legitimate_omitted_success_preserved(client):
    client.graph = Mock(return_value=[None, {"code": 200, "body": '{"id":"1"}'}])
    rows, failed = client.batch([{"method": "GET", "relative_url": "me", "omit_response_on_success": True}, {"method": "GET", "relative_url": "me"}])
    assert rows[0] is None and not failed
    client.graph = Mock(return_value=[None])
    with pytest.raises(ClientError, match="Unexpected omitted"):
        client.batch([{"method": "GET", "relative_url": "me"}])


def test_video_upload_host_and_closed_file(client, tmp_path):
    path = tmp_path / "chunk.bin"
    path.write_bytes(b"VIDEO")
    client.api.call = Mock(return_value=SimpleNamespace(json=lambda: {"id": "1"}))
    assert client.graph("POST", "act_1/advideos", files={"video_file_chunk": str(path)}, yes=True, video_host=True) == {"id": "1"}
    assert client.api.call.call_args.kwargs["url_override"] == "https://graph-video.facebook.com"
    assert client.api.call.call_args.kwargs["files"]["video_file_chunk"].closed


def test_sdk_upload_uses_official_file_request(client, tmp_path):
    path = tmp_path / "image.jpg"
    path.write_bytes(b"IMAGE")
    files = {}
    def api_call(method, path, **kwargs):
        files.update(kwargs["files"])
        assert next(iter(files.values())).read() == b"IMAGE"
        return SimpleNamespace(json=lambda: {"images": {"i": {"hash": "a"}}}, error=lambda: None)
    client.api.call = api_call
    result = client.call("AdAccount", "create_ad_image", "act_1", files={"filename": str(path)}, yes=True)
    assert result["images"]["i"]["hash"] == "a"
    assert all(stream.closed for stream in files.values())


@pytest.mark.parametrize("entry", [{"method": 1, "relative_url": "me"}, {"method": "GET", "relative_url": 5},
                                    {"method": "GET", "relative_url": "me", "omit_response_on_success": "false"}])
def test_batch_invalid_types_fail_explicitly(client, entry):
    with pytest.raises(ClientError):
        client.batch([entry])


def test_retry_after_header_is_honored(monkeypatch):
    replies = [response(429), response(200)]
    replies[0].headers["Retry-After"] = "7"
    monkeypatch.setattr(requests.Session, "request", lambda *args, **kwargs: replies.pop(0))
    captured = []
    class Policy(RequestsRetryPolicy):
        def calculate_delay(self, attempt, retry_after=None):
            captured.append(retry_after)
            return 0
    GraphSession(Policy()).request("GET", "https://graph.facebook.com/v26.0/me")
    assert captured == [7.0]


def test_sdk_preserves_success_and_nested_edge_envelopes(client):
    data = {"id": "1", "success": True, "campaigns": {"data": [{"id": "2"}], "paging": {"cursors": {"after": "A"}}}}
    client.api.call = lambda *args, **kwargs: SimpleNamespace(json=lambda: data, error=lambda: None)
    assert client.call("Campaign", "api_get", "1") == data


def test_tables_preserve_more_than_six_fields(monkeypatch):
    from rich.console import Console
    monkeypatch.setattr("cli_tools_shared.output.console", Console(width=200, force_terminal=False, color_system=None))
    rows = [{f"field_{i}": f"value_{i}" for i in range(9)}]
    runner = CliRunner()
    monkeypatch.setattr("facebook_ads_cli.main.get_client", lambda profile: SimpleNamespace(list_edge=lambda *args: rows))
    result = runner.invoke(app, ["accounts", "list", "--table"])
    assert result.exit_code == 0, result.output
    assert all(f"field_{i}" in result.stdout for i in range(9))
    assert all(f"value_{i}" in result.stdout for i in range(9))


@pytest.mark.parametrize("key", ["access_token", "appsecret_proof", "app_secret"])
def test_redaction_uses_same_keys_for_objects_and_urls(key):
    output = json.dumps(redact({key: "SECRET", "next": f"https://graph.facebook.com/x?{key}=SECRET&after=A"}))
    assert "SECRET" not in output
    assert "after=A" in output


def test_app_secret_fails_fast_without_terminal(monkeypatch):
    monkeypatch.setattr("cli_tools_shared.output._stdin_is_interactive_tty", lambda: False)
    monkeypatch.setattr("facebook_ads_cli.main.get_config", lambda *args: pytest.fail("Must not save without terminal"))
    result = CliRunner().invoke(app, ["app-secret"])
    assert result.exit_code == 1
    assert "no interactive terminal" in result.stderr
    assert not result.stdout


def test_app_secret_uses_shared_prompt_and_secret_save(monkeypatch):
    saved = {}
    monkeypatch.setattr("facebook_ads_cli.main.prompt_secret", lambda label: "SYNTHETIC_SECRET")
    monkeypatch.setattr("facebook_ads_cli.main.get_config", lambda profile: SimpleNamespace(save_credentials=lambda **kwargs: saved.update(kwargs)))
    result = CliRunner().invoke(app, ["app-secret"])
    assert result.exit_code == 0
    assert saved == {"APP_SECRET": "SYNTHETIC_SECRET"}
    assert "SYNTHETIC_SECRET" not in result.output


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -1, 0])
@pytest.mark.parametrize("argument", ["timeout", "interval"])
def test_report_rejects_nonfinite_or_nonpositive_timing(client, value, argument):
    client.graph = Mock(side_effect=AssertionError("Must validate before network"))
    with pytest.raises(ClientError, match="finite"):
        client.wait_report("1", **{argument: value})
    client.graph.assert_not_called()


@pytest.mark.parametrize("name", ["HTTP_TIMEOUT", "MAX_RETRIES", "BASE_DELAY", "MAX_DELAY", "RETRY_JITTER"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-1"])
def test_config_rejects_nonfinite_retry_and_timeout(name, value):
    config = SimpleNamespace(personal_access_token="SYNTHETIC", api_version="v26.0", _get=lambda key: value if key == name else None)
    with pytest.raises(ClientError, match="finite"):
        FacebookAdsClient(config=config)


def test_shared_retry_defaults_and_zero_overrides():
    config = SimpleNamespace(personal_access_token="SYNTHETIC", api_version="v26.0", _get=lambda key: None)
    client = FacebookAdsClient(config=config)
    assert client.api._session.requests.policy == RequestsRetryPolicy()
    values = {"MAX_RETRIES": "0", "BASE_DELAY": "0", "MAX_DELAY": "0", "RETRY_JITTER": "0"}
    config._get = values.get
    client = FacebookAdsClient(config=config)
    assert client.api._session.requests.policy == RequestsRetryPolicy(max_retries=0, base_delay=0, max_delay=0, jitter=0)


def test_report_status_shared_by_cli_and_polling(client, monkeypatch):
    client.graph = Mock(return_value={"async_status": "Job Completed"})
    monkeypatch.setattr("facebook_ads_cli.main.get_client", lambda profile: client)
    result = CliRunner().invoke(app, ["insights", "status", "1"])
    assert result.exit_code == 0
    assert client.wait_report("1") == {"async_status": "Job Completed"}
    expected = ("GET", "1", {"fields": "id,async_status,async_percent_completion"})
    assert all(call.args == expected for call in client.graph.call_args_list)


def test_filter_parser_handles_whitespace_and_escaped_comma():
    assert native_filters([r"status:eq:PAUSED, name:contains:Alpha\, Beta"]) == [
        {"field": "status", "operator": "EQUAL", "value": "PAUSED"},
        {"field": "name", "operator": "CONTAIN", "value": "Alpha, Beta"}]


@pytest.mark.parametrize("params", ['{"daily_budget":NaN}', '{"nested":[Infinity]}', '{"value":1e999}'])
@pytest.mark.parametrize("prefix", [["graph", "request", "POST", "act_1/campaigns"],
                                    ["sdk", "call", "AdAccount", "create_campaign", "act_1"]])
def test_nonfinite_json_rejected_before_dry_run_and_client(params, prefix, monkeypatch):
    monkeypatch.setattr("facebook_ads_cli.main.get_client", lambda *args: pytest.fail("Must reject before client"))
    result = CliRunner().invoke(app, prefix + ["--params", params, "--dry-run"])
    assert result.exit_code == 1
    assert "JSON numbers must be finite" in result.stderr
    assert not result.stdout


def test_sdk_repeated_cursor_rejected_before_duplicate_records(client):
    calls = []
    def api_call(method, path, params=None, **kwargs):
        calls.append(dict(params or {}))
        data = {"data": [{"id": "same"}], "paging": {"next": "yes", "cursors": {"after": "repeat"}}}
        return SimpleNamespace(json=lambda: data, headers=lambda: {}, error=lambda: None)
    client.api.call = api_call
    with pytest.raises(ClientError, match="repeated a paging cursor"):
        client.call("AdAccount", "get_campaigns", "act_1", all_pages=True, max_items=3)
    assert len(calls) == 2


def test_sdk_empty_cursor_page_with_next_is_not_end(client):
    responses = iter([{"data": [], "paging": {"next": "yes", "cursors": {"after": "A"}}}, {"data": [{"id": "1"}]}])
    client.api.call = lambda *args, **kwargs: SimpleNamespace(json=lambda: next(responses), headers=lambda: {}, error=lambda: None)
    assert client.call("AdAccount", "get_campaigns", "act_1", all_pages=True, max_items=3) == [{"id": "1"}]


@pytest.mark.parametrize("value", ["not-json", None, 7, True, {"data": "bad"}])
def test_malformed_sdk_edge_fails_cleanly(value, monkeypatch):
    config = SimpleNamespace(personal_access_token="SYNTHETIC", api_version="v26.0", _get=lambda key: None)
    client = FacebookAdsClient(config=config)
    upstream = response(200)
    upstream._content = json.dumps(value).encode()
    monkeypatch.setattr(requests.Session, "request", lambda *args, **kwargs: upstream)
    with pytest.raises(ClientError, match="JSON response|data array"):
        client.call("AdAccount", "get_campaigns", "act_1")


def test_malformed_raw_graph_response_fails_cleanly(client):
    client.api.call = lambda *args, **kwargs: SimpleNamespace(json=lambda: "not-json")
    with pytest.raises(ClientError, match="invalid JSON response"):
        client.graph("GET", "me")


def test_malformed_transport_response_fails_cleanly(monkeypatch):
    bad = response(200)
    bad._content = b"not-json"
    monkeypatch.setattr(requests.Session, "request", lambda *args, **kwargs: bad)
    with pytest.raises(ClientError, match="invalid JSON"):
        GraphSession(RequestsRetryPolicy()).request("GET", "https://graph.facebook.com/v26.0/me")


def test_error_redacts_configured_app_secret_and_proof(monkeypatch):
    config = SimpleNamespace(personal_access_token="SYNTHETIC_TOKEN", api_version="v26.0", _get=lambda key: "SYNTHETIC_APP_SECRET" if key == "APP_SECRET" else None)
    client = FacebookAdsClient(config=config)
    proof = client.api._session.requests.params["appsecret_proof"]
    error = response(400, {"error": {"message": f"SYNTHETIC_TOKEN app_secret=SYNTHETIC_APP_SECRET appsecret_proof={proof}", "code": 190}})
    monkeypatch.setattr(requests.Session, "request", lambda *args, **kwargs: error)
    with pytest.raises(ClientError) as caught:
        client.graph("GET", "me")
    message = str(caught.value)
    assert "SYNTHETIC" not in message and proof not in message
    assert message.count("[REDACTED]") == 3


def test_batch_error_message_sensitive_assignments_redacted(client):
    client.graph = lambda *args, **kwargs: [{"code": 400, "body": json.dumps({"error": {"message": "app_secret=SECRET appsecret_proof=PROOF access_token=TOKEN"}})}]
    rows, failed = client.batch([{"method": "GET", "relative_url": "me"}])
    assert failed
    assert rows[0]["body"]["error"]["message"].count("[REDACTED]") == 3


@pytest.mark.parametrize("key", ["method", "_method"])
def test_method_override_requires_confirmation_before_graph_and_sdk(client, key):
    client.api.call = Mock(side_effect=AssertionError("Must guard before dispatch"))
    with pytest.raises(ClientError, match="Mutation requires"):
        client.graph("GET", "me", {key: "POST"})
    with pytest.raises(ClientError, match="Mutation requires"):
        client.call("Campaign", "api_get", "1", {key: "POST"})
    client.api.call.assert_not_called()
    assert client.graph("GET", "me", {key: "POST"}, dry_run=True)["params"][key] == "POST"
    assert client.call("Campaign", "api_get", "1", {key: "POST"}, dry_run=True)["params"][key] == "POST"


@pytest.mark.parametrize("entry", [{"method": "GET", "relative_url": "me?method=POST"},
                                    {"method": "GET", "relative_url": "me", "body": "_method=POST"}])
def test_batch_method_override_requires_confirmation(client, entry):
    client.graph = Mock(side_effect=AssertionError("Must guard before dispatch"))
    with pytest.raises(ClientError, match="Mutation requires"):
        client.batch([entry])
    client.graph.assert_not_called()


@pytest.mark.parametrize("kwargs,url", [({"params": {"method": "POST"}}, "https://graph.facebook.com/v26.0/me"),
                                        ({}, "https://graph.facebook.com/v26.0/me?_method=POST")])
def test_get_with_method_override_is_never_retried(monkeypatch, kwargs, url):
    calls = []
    def send(*args, **values):
        calls.append(values)
        return response(503, {"error": {"message": "busy"}})
    monkeypatch.setattr(requests.Session, "request", send)
    result = GraphSession(RequestsRetryPolicy(base_delay=0, jitter=0)).request("GET", url, **kwargs)
    assert result.status_code == 503
    assert len(calls) == 1


def test_nested_business_method_field_not_override(client):
    client.api.call = Mock(return_value=SimpleNamespace(json=lambda: {"id": "1"}))
    assert client.graph("GET", "me", {"business": {"method": "POST"}}) == {"id": "1"}
    client.api.call.assert_called_once()


@pytest.mark.parametrize("paging", [None, "bad", {"next": "https://graph.facebook.com/x", "cursors": None}])
@pytest.mark.parametrize("kind", ["sdk", "named"])
def test_malformed_paging_fails_before_sdk_or_named_traversal(monkeypatch, paging, kind):
    config = SimpleNamespace(personal_access_token="SYNTHETIC", api_version="v26.0", _get=lambda key: None)
    client = FacebookAdsClient(config=config)
    upstream = response(200, {"data": [{"id": "1"}], "paging": paging})
    monkeypatch.setattr(requests.Session, "request", lambda *args, **kwargs: upstream)
    with pytest.raises(ClientError, match="invalid paging"):
        if kind == "sdk":
            client.call("AdAccount", "get_campaigns", "act_1", all_pages=True)
        else:
            client.list_edge("act_1", "campaigns", 5)


@pytest.mark.parametrize("kind", ["raw", "sdk"])
def test_confirmed_get_override_dispatches_once_without_retry(monkeypatch, kind):
    config = SimpleNamespace(personal_access_token="SYNTHETIC", api_version="v26.0", _get=lambda key: None)
    client = FacebookAdsClient(config=config)
    calls = []
    def send(self, method, url, **kwargs):
        calls.append((method, kwargs))
        return response(503, {"error": {"message": "busy", "code": 2}})
    monkeypatch.setattr(requests.Session, "request", send)
    with pytest.raises(ClientError, match="Meta API error"):
        if kind == "raw":
            client.graph("GET", "me", {"method": "POST"}, yes=True)
        else:
            client.call("Campaign", "api_get", "1", {"_method": "POST"}, yes=True)
    assert len(calls) == 1 and calls[0][0] == "GET"
    assert any(key in calls[0][1]["params"] for key in ("method", "_method"))


def test_confirmed_batch_override_preserves_params(client):
    client.graph = Mock(return_value=[{"code": 200, "body": '{"id":"1"}'}])
    entry = {"method": "GET", "relative_url": "me?method=POST", "body": "_method=POST"}
    rows, failed = client.batch([entry], yes=True)
    assert not failed and rows[0]["body"] == {"id": "1"}
    assert client.graph.call_args.args[2]["batch"] == [entry]
