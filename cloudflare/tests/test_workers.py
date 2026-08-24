"""Deterministic tests for account-level Workers script support.

Covers the client methods (list/get/upload/delete on
/accounts/{account_id}/workers/scripts), account resolution, and the workers
command layer (JSON/table output, filtering, bindings parsing, delete
confirmation). No network access: every request is captured by a recording
transport or a fake client, mirroring test_write_path_auth.py conventions.
"""
import json

import pytest
from typer.testing import CliRunner

from cloudflare_cli import client as client_module
from cloudflare_cli.client import CloudflareClient, required_permission_group
from cloudflare_cli.commands import workers as workers_module
from cli_tools_shared.exceptions import ClientError


ACCOUNT_ID = "aa11bb33cc55dd77ee99ff0012345678"
SCRIPT_NAME = "cli-test-worker"
FAKE_TOKEN = "test-token-not-a-real-credential"
SCRIPT_CONTENT = 'export default { fetch() { return new Response("ok"); } };\n'


# --------------------------------------------------------------------------
# Shared fakes (local copies; tests/ has no __init__.py package imports).
# --------------------------------------------------------------------------


class _FakeConfig:
    """Minimal stand-in for the real Config so tests need no stored credential."""

    api_key = FAKE_TOKEN
    base_url = "https://api.cloudflare.com/client/v4"

    def has_credentials(self):
        return True

    def get_missing_credentials(self):
        return []


class _FakeResponse:
    def __init__(self, status_code, payload, text=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}
        self.ok = status_code < 400
        self.text = text if text is not None else str(payload)

    def json(self):
        return self._payload


class _RecordingTransport:
    """Captures every outbound request and replays queued responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, json=None, params=None, files=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "json": json,
                "params": params,
                "files": files,
            }
        )
        return self._responses.pop(0)


def _build_client(monkeypatch, responses):
    monkeypatch.setattr(client_module, "get_config", lambda: _FakeConfig())
    transport = _RecordingTransport(responses)
    monkeypatch.setattr(client_module.requests, "request", transport)
    # No retry sleeps in tests.
    return CloudflareClient(max_retries=0), transport


def _ok(result, text=None):
    return _FakeResponse(200, {"success": True, "errors": [], "result": result}, text=text)


def _script(index):
    return {
        "id": f"worker-{index}",
        "created_on": "2026-01-15T10:30:00Z",
        "modified_on": "2026-02-20T08:00:00Z",
    }


class _FakeWorkersClient:
    """Fake client for command-layer tests; records every call."""

    def __init__(self):
        self.calls = []
        self.scripts = [_script(1), _script(2)]
        self.content = SCRIPT_CONTENT
        self.upload_result = {"id": SCRIPT_NAME, "created_on": "2026-03-01T00:00:00Z"}
        self.delete_result = {"id": SCRIPT_NAME}

    def resolve_account_id(self, account):
        if account == "my-account":
            self.calls.append(("resolve_account_id", account))
            return ACCOUNT_ID
        raise ClientError(f"Account not found: {account}")

    def default_account_id(self):
        self.calls.append(("default_account_id",))
        return ACCOUNT_ID

    def list_worker_scripts(self, account_id, limit=100):
        self.calls.append(("list_worker_scripts", account_id, limit))
        return [dict(s) for s in self.scripts][:limit]

    def get_worker_script(self, account_id, script_name):
        self.calls.append(("get_worker_script", account_id, script_name))
        return self.content

    def upload_worker_script(self, **kwargs):
        self.calls.append(("upload_worker_script", kwargs))
        return dict(self.upload_result)

    def delete_worker_script(self, account_id, script_name):
        self.calls.append(("delete_worker_script", account_id, script_name))
        return dict(self.delete_result)


@pytest.fixture()
def fake_client(monkeypatch):
    fake = _FakeWorkersClient()
    monkeypatch.setattr(workers_module, "get_client", lambda: fake)
    return fake


runner = CliRunner()


# --------------------------------------------------------------------------
# Client: list pagination and parsing.
# --------------------------------------------------------------------------


def test_list_worker_scripts_returns_all_in_single_call(monkeypatch):
    scripts = [_script(i) for i in range(3)]
    client, transport = _build_client(
        monkeypatch, [_ok(scripts)]
    )

    result = client.list_worker_scripts(ACCOUNT_ID, limit=10)

    assert [s["id"] for s in result] == ["worker-0", "worker-1", "worker-2"]
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"].endswith(f"/accounts/{ACCOUNT_ID}/workers/scripts")
    assert "params" not in transport.calls[0] or not transport.calls[0]["params"]
    assert transport.calls[0]["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_list_worker_scripts_enforces_limit_client_side(monkeypatch):
    # The Workers Scripts endpoint returns everything in one response and
    # ignores pagination query params, so the limit must slice client-side.
    scripts = [_script(i) for i in range(13)]
    client, transport = _build_client(
        monkeypatch, [_ok(scripts)]
    )

    result = client.list_worker_scripts(ACCOUNT_ID, limit=1)

    assert [s["id"] for s in result] == ["worker-0"]
    assert len(transport.calls) == 1


def test_get_worker_script_returns_raw_content_with_javascript_accept(monkeypatch):
    body = SCRIPT_CONTENT
    response = _FakeResponse(
        200,
        {"success": True, "errors": [], "result": None},
        text=body,
    )
    client, transport = _build_client(monkeypatch, [response])

    content = client.get_worker_script(ACCOUNT_ID, SCRIPT_NAME)

    assert content == body
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/workers/scripts/{SCRIPT_NAME}")
    assert call["headers"]["Accept"] == "application/javascript"


# --------------------------------------------------------------------------
# Client: multipart upload payload construction.
# --------------------------------------------------------------------------


def test_upload_worker_script_builds_multipart_modules_payload(monkeypatch):
    client, transport = _build_client(
        monkeypatch, [_ok({"id": SCRIPT_NAME, "modified_on": "2026-03-01T00:00:00Z"})]
    )

    result = client.upload_worker_script(
        ACCOUNT_ID,
        SCRIPT_NAME,
        SCRIPT_CONTENT,
        bindings=[{"type": "plain_text", "name": "TITLE", "text": "hi"}],
        compatibility_date="2026-01-15",
    )

    assert result["id"] == SCRIPT_NAME
    call = transport.calls[0]
    assert call["method"] == "PUT"
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/workers/scripts/{SCRIPT_NAME}")
    assert call["json"] is None
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"
    # Multipart must not carry the JSON Content-Type header.
    assert "Content-Type" not in call["headers"]

    metadata_name, metadata_value, metadata_type = call["files"]["metadata"]
    assert metadata_name is None
    assert json.loads(metadata_value) == {
        "main_module": "worker.js",
        "compatibility_date": "2026-01-15",
        "bindings": [{"type": "plain_text", "name": "TITLE", "text": "hi"}],
    }
    assert metadata_type == "application/json"

    file_name, file_content, file_type = call["files"]["file"]
    assert file_name == f"{SCRIPT_NAME}.js"
    assert file_content == SCRIPT_CONTENT
    assert file_type == "application/javascript+module"


def test_upload_worker_script_service_worker_format_omits_main_module(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok({"id": SCRIPT_NAME})])

    client.upload_worker_script(
        ACCOUNT_ID, SCRIPT_NAME, SCRIPT_CONTENT, script_format="service-worker"
    )

    _, _, metadata_type = transport.calls[0]["files"]["metadata"]
    _, _, file_type = transport.calls[0]["files"]["file"]
    metadata = json.loads(transport.calls[0]["files"]["metadata"][1])
    assert metadata == {}
    assert metadata_type == "application/json"
    assert file_type == "application/javascript"


def test_delete_worker_script_returns_result_and_authenticates(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok({"id": SCRIPT_NAME})])

    result = client.delete_worker_script(ACCOUNT_ID, SCRIPT_NAME)

    assert result == {"id": SCRIPT_NAME}
    call = transport.calls[0]
    assert call["method"] == "DELETE"
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/workers/scripts/{SCRIPT_NAME}")
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


# --------------------------------------------------------------------------
# Account resolution.
# --------------------------------------------------------------------------


def test_resolve_account_id_passes_hex_ids_through(monkeypatch):
    client, _ = _build_client(monkeypatch, [])
    assert client.resolve_account_id(ACCOUNT_ID) == ACCOUNT_ID


def test_resolve_account_id_matches_by_name(monkeypatch):
    accounts = [{"id": ACCOUNT_ID, "name": "Adam's Account"}]
    client, _ = _build_client(monkeypatch, [_ok(accounts)])

    assert client.resolve_account_id("Adam's Account") == ACCOUNT_ID


def test_resolve_account_id_unknown_name_raises(monkeypatch):
    client, _ = _build_client(monkeypatch, [_ok([{"id": ACCOUNT_ID, "name": "Other"}])])

    with pytest.raises(ClientError) as excinfo:
        client.resolve_account_id("Nope")
    assert "Account not found: Nope" in str(excinfo.value)


def test_default_account_id_single_account(monkeypatch):
    accounts = [{"id": ACCOUNT_ID, "name": "Only Account"}]
    client, _ = _build_client(monkeypatch, [_ok(accounts)])

    assert client.default_account_id() == ACCOUNT_ID


def test_default_account_id_multiple_accounts_names_them(monkeypatch):
    accounts = [
        {"id": ACCOUNT_ID, "name": "One"},
        {"id": "bb22cc44dd66ee88ff0012345678abcd", "name": "Two"},
    ]
    client, _ = _build_client(monkeypatch, [_ok(accounts)])

    with pytest.raises(ClientError) as excinfo:
        client.default_account_id()
    message = str(excinfo.value)
    assert "Multiple Cloudflare accounts are visible" in message
    assert "One" in message and "Two" in message


def test_default_account_id_zero_accounts_raises(monkeypatch):
    client, _ = _build_client(monkeypatch, [_ok([])])

    with pytest.raises(ClientError) as excinfo:
        client.default_account_id()
    assert "No Cloudflare accounts are visible" in str(excinfo.value)


# --------------------------------------------------------------------------
# Permission-group mapping for Workers endpoints.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, endpoint, expected",
    [
        ("GET", f"/accounts/{ACCOUNT_ID}/workers/scripts", "Account > Workers Scripts > Read"),
        (
            "PUT",
            f"/accounts/{ACCOUNT_ID}/workers/scripts/{SCRIPT_NAME}",
            "Account > Workers Scripts > Edit",
        ),
        (
            "DELETE",
            f"/accounts/{ACCOUNT_ID}/workers/scripts/{SCRIPT_NAME}",
            "Account > Workers Scripts > Edit",
        ),
        (
            "GET",
            f"/zones/{ACCOUNT_ID}/workers/routes",
            "Zone > Workers Routes > Read",
        ),
    ],
)
def test_workers_permission_group_mapping(method, endpoint, expected):
    assert required_permission_group(method, endpoint) == expected


# --------------------------------------------------------------------------
# Command layer: list output, filtering, properties.
# --------------------------------------------------------------------------


def test_list_command_json_output_defaults_to_single_account(fake_client):
    result = runner.invoke(workers_module.app, ["list"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert [s["id"] for s in parsed] == ["worker-1", "worker-2"]
    assert ("list_worker_scripts", ACCOUNT_ID, 100) in fake_client.calls


def test_list_command_applies_filter_and_properties(fake_client):
    result = runner.invoke(
        workers_module.app,
        ["list", "--filter", "id:eq:worker-1", "--properties", "id"],
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed == [{"id": "worker-1"}]


def test_list_command_table_formats_local_timestamps(fake_client):
    result = runner.invoke(workers_module.app, ["list", "--table"])

    assert result.exit_code == 0
    out = result.stdout
    assert "ID" in out and "Created" in out and "Modified" in out
    assert "worker-1" in out
    # No raw ISO timestamps in table output.
    assert "2026-01-15T" not in out
    assert "2026-01-15" in out


def test_get_command_prints_raw_content_to_stdout(fake_client):
    result = runner.invoke(workers_module.app, ["get", SCRIPT_NAME])

    assert result.exit_code == 0
    assert result.stdout == SCRIPT_CONTENT + "\n"
    assert ("get_worker_script", ACCOUNT_ID, SCRIPT_NAME) in fake_client.calls


def test_upload_command_reads_file_and_builds_payload(fake_client, tmp_path):
    source = tmp_path / "worker.js"
    source.write_text(SCRIPT_CONTENT, encoding="utf-8")

    result = runner.invoke(
        workers_module.app,
        [
            "upload",
            SCRIPT_NAME,
            "--file",
            str(source),
            "--compatibility-date",
            "2026-01-15",
        ],
    )

    assert result.exit_code == 0
    # print_success writes to stderr with a check-symbol prefix.
    assert "Uploaded worker script cli-test-worker" in result.output
    entry = next(c for c in fake_client.calls if c[0] == "upload_worker_script")
    kwargs = entry[1]
    assert kwargs["account_id"] == ACCOUNT_ID
    assert kwargs["script_name"] == SCRIPT_NAME
    assert kwargs["content"] == SCRIPT_CONTENT
    assert kwargs["script_format"] == "modules"
    assert kwargs["compatibility_date"] == "2026-01-15"


def test_upload_command_rejects_invalid_bindings_json(fake_client):
    result = runner.invoke(
        workers_module.app,
        ["upload", SCRIPT_NAME, "--file", "-", "--bindings", "{not json"],
        input=SCRIPT_CONTENT,
    )

    assert result.exit_code == 1
    assert "Invalid --bindings JSON" in result.output
    assert all(c[0] != "upload_worker_script" for c in fake_client.calls)


def test_upload_command_rejects_non_array_bindings(fake_client):
    result = runner.invoke(
        workers_module.app,
        ["upload", SCRIPT_NAME, "--file", "-", "--bindings", '{"type":"x"}'],
        input=SCRIPT_CONTENT,
    )

    assert result.exit_code == 1
    assert "--bindings must be a JSON array" in result.output


def test_delete_command_requires_confirmation_in_non_tty(fake_client):
    result = runner.invoke(workers_module.app, ["delete", SCRIPT_NAME])

    assert result.exit_code != 0
    assert "Refusing to delete worker script" in result.output
    assert "--force" in result.output
    assert all(c[0] != "delete_worker_script" for c in fake_client.calls)


def test_delete_command_force_skips_prompt_and_deletes(fake_client):
    result = runner.invoke(workers_module.app, ["delete", SCRIPT_NAME, "--force"])

    assert result.exit_code == 0
    assert "Deleted worker script cli-test-worker" in result.output
    assert ("delete_worker_script", ACCOUNT_ID, SCRIPT_NAME) in fake_client.calls


def test_commands_accept_explicit_account_argument(fake_client):
    result = runner.invoke(
        workers_module.app, ["list", "my-account", "--properties", "id"]
    )

    assert result.exit_code == 0
    assert ("resolve_account_id", "my-account") in fake_client.calls


# --------------------------------------------------------------------------
# Worker routes: command layer (list flags, get) and client.
# --------------------------------------------------------------------------


def _route(index):
    return {
        "id": f"route-{index}",
        "pattern": f"example.com/path{index}*",
        "script": f"worker-{index}",
    }


def test_list_worker_routes_returns_result_list(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok([_route(1), _route(2)])])

    result = client.list_worker_routes(zone_id=ACCOUNT_ID)

    assert [r["id"] for r in result] == ["route-1", "route-2"]
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"].endswith(f"/zones/{ACCOUNT_ID}/workers/routes")


def test_get_worker_route_hits_detail_endpoint(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(_route(1))])

    result = client.get_worker_route(zone_id=ACCOUNT_ID, route_id="route-1")

    assert result["id"] == "route-1"
    assert len(transport.calls) == 1
    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["url"].endswith(
        f"/zones/{ACCOUNT_ID}/workers/routes/route-1"
    )


def test_worker_routes_detail_permission_group():
    assert (
        required_permission_group(
            "GET", f"/zones/{ACCOUNT_ID}/workers/routes/{SCRIPT_NAME}"
        )
        == "Zone > Workers Routes > Read"
    )


class _FakeRoutesClient(_FakeWorkersClient):
    """Extends the fake workers client with zone-route methods."""

    def __init__(self):
        super().__init__()
        self.routes = [_route(1), _route(2)]

    def resolve_zone_id(self, zone):
        self.calls.append(("resolve_zone_id", zone))
        return ACCOUNT_ID

    def list_worker_routes(self, zone_id):
        self.calls.append(("list_worker_routes", zone_id))
        return [dict(r) for r in self.routes]

    def get_worker_route(self, zone_id, route_id):
        self.calls.append(("get_worker_route", zone_id, route_id))
        return dict(self.routes[0])


@pytest.fixture()
def fake_routes_client(monkeypatch):
    fake = _FakeRoutesClient()
    monkeypatch.setattr(workers_module, "get_client", lambda: fake)
    return fake


def test_routes_list_json_output(fake_routes_client):
    result = runner.invoke(workers_module.app, ["routes", "list", "example.com"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert [r["id"] for r in parsed] == ["route-1", "route-2"]
    assert ("list_worker_routes", ACCOUNT_ID) in fake_routes_client.calls


def test_routes_list_table_output(fake_routes_client):
    result = runner.invoke(
        workers_module.app, ["routes", "list", "example.com", "--table"]
    )

    assert result.exit_code == 0
    out = result.stdout
    assert "ID" in out and "Pattern" in out and "Script" in out
    assert "route-1" in out and "example.com/path1*" in out


def test_routes_list_applies_limit_filter_and_properties(fake_routes_client):
    result = runner.invoke(
        workers_module.app,
        [
            "routes",
            "list",
            "example.com",
            "--limit",
            "1",
            "--filter",
            "script:eq:worker-1",
            "--properties",
            "id",
        ],
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed == [{"id": "route-1"}]


def test_routes_get_json_output(fake_routes_client):
    result = runner.invoke(
        workers_module.app, ["routes", "get", "example.com", "route-1"]
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["id"] == "route-1"
    assert ("get_worker_route", ACCOUNT_ID, "route-1") in fake_routes_client.calls


def test_routes_get_table_output(fake_routes_client):
    result = runner.invoke(
        workers_module.app, ["routes", "get", "example.com", "route-1", "--table"]
    )

    assert result.exit_code == 0
    out = result.stdout
    assert "Field" in out and "Value" in out
    assert "route-1" in out
