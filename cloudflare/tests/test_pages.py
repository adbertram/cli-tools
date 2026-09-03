"""Deterministic tests for Cloudflare Pages support.

Covers projects, deployments, and domains command groups plus their client
methods on /accounts/{account_id}/pages/... Every endpoint path, method, and
query/body shape mirrors the live API docs at
https://developers.cloudflare.com/api/resources/pages/. No network access:
every request is captured by a recording transport or a fake client,
mirroring test_workers.py conventions.
"""
import json

import pytest
from typer.testing import CliRunner

from cloudflare_cli import client as client_module
from cloudflare_cli.client import CloudflareClient, required_permission_group
from cloudflare_cli.commands import pages as pages_module
from cli_tools_shared.exceptions import ClientError


ACCOUNT_ID = "aa11bb33cc55dd77ee99ff0012345678"
PROJECT_NAME = "cli-test-site"
DEPLOYMENT_ID = "ab12cd34ef56ab78cd90ef12ab34cd56"
DOMAIN_NAME = "docs.example.com"
FAKE_TOKEN = "test-token-not-a-real-credential"


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


def _ok(result, result_info=None):
    payload = {"success": True, "errors": [], "result": result}
    if result_info is not None:
        payload["result_info"] = result_info
    return _FakeResponse(200, payload)


def _project(index):
    return {
        "id": f"proj-{index}",
        "name": f"site-{index}",
        "production_branch": "main",
        "created_on": "2026-01-15T10:30:00Z",
    }


def _deployment(index):
    return {
        "id": f"deploy-{index}",
        "env": "production" if index % 2 == 0 else "preview",
        "deployment_trigger": {"metadata": {"branch": "main"}},
        "latest_stage": {"status": "success"},
        "created_on": "2026-02-20T08:00:00Z",
    }


def _domain(index):
    return {
        "id": f"domain-{index}",
        "name": f"docs{index}.example.com",
        "status": "active",
        "creation_date": "2026-03-01T09:00:00Z",
        "modified_date": "2026-03-02T09:00:00Z",
    }


class _FakePagesClient:
    """Fake client for command-layer tests; records every call."""

    def __init__(self):
        self.calls = []
        self.projects = [_project(1), _project(2)]
        self.deployments = [_deployment(1), _deployment(2)]
        self.domains = [_domain(1)]
        self.project_result = dict(_project(9))
        self.deployment_result = dict(_deployment(9))
        self.domain_result = dict(_domain(9))
        self.upload_token_result = {"jwt": "fake-upload-token"}
        # Asset hashes Cloudflare reports as missing (empty = nothing to upload).
        self.missing_hashes = []

    def resolve_account_id(self, account):
        if account == "my-account":
            self.calls.append(("resolve_account_id", account))
            return ACCOUNT_ID
        raise ClientError(f"Account not found: {account}")

    def default_account_id(self):
        self.calls.append(("default_account_id",))
        return ACCOUNT_ID

    # Projects
    def list_pages_projects(self, account_id, limit=100):
        self.calls.append(("list_pages_projects", account_id, limit))
        return [dict(p) for p in self.projects][:limit]

    def get_pages_project(self, account_id, project_name):
        self.calls.append(("get_pages_project", account_id, project_name))
        return dict(self.project_result)

    def create_pages_project(self, account_id, name, production_branch, config=None):
        self.calls.append(("create_pages_project", account_id, name, production_branch, config))
        return dict(self.project_result)

    def patch_pages_project(self, account_id, project_name, data):
        self.calls.append(("patch_pages_project", account_id, project_name, data))
        return dict(self.project_result)

    def delete_pages_project(self, account_id, project_name):
        self.calls.append(("delete_pages_project", account_id, project_name))
        return {"id": project_name}

    def purge_pages_build_cache(self, account_id, project_name):
        self.calls.append(("purge_pages_build_cache", account_id, project_name))
        return {}

    def get_pages_upload_token(self, account_id, project_name):
        self.calls.append(("get_pages_upload_token", account_id, project_name))
        return dict(self.upload_token_result)

    def check_missing_page_assets(self, jwt, hashes):
        self.calls.append(("check_missing_page_assets", jwt, list(hashes)))
        return list(self.missing_hashes)

    def upload_page_assets(self, jwt, payload):
        self.calls.append(("upload_page_assets", jwt, list(payload)))
        return {}

    def upsert_page_asset_hashes(self, jwt, hashes):
        self.calls.append(("upsert_page_asset_hashes", jwt, list(hashes)))
        return {}

    # Deployments
    def list_pages_deployments(self, account_id, project_name, limit=100, env=None):
        self.calls.append(("list_pages_deployments", account_id, project_name, limit, env))
        items = [dict(d) for d in self.deployments]
        if env:
            items = [d for d in items if d["env"] == env]
        return items[:limit]

    def get_pages_deployment(self, account_id, project_name, deployment_id):
        self.calls.append(("get_pages_deployment", account_id, project_name, deployment_id))
        return dict(self.deployment_result)

    def create_pages_deployment(self, **kwargs):
        self.calls.append(("create_pages_deployment", kwargs))
        return dict(self.deployment_result)

    def build_worker_bundle(self, worker_script):
        self.calls.append(("build_worker_bundle", worker_script))
        return b"FAKE-WORKER-BUNDLE:" + worker_script["filename"].encode("utf-8")

    def retry_pages_deployment(self, account_id, project_name, deployment_id):
        self.calls.append(("retry_pages_deployment", account_id, project_name, deployment_id))
        return dict(self.deployment_result)

    def rollback_pages_deployment(self, account_id, project_name, deployment_id):
        self.calls.append(("rollback_pages_deployment", account_id, project_name, deployment_id))
        return dict(self.deployment_result)

    def delete_pages_deployment(self, account_id, project_name, deployment_id, allow_aliased=False):
        self.calls.append(
            ("delete_pages_deployment", account_id, project_name, deployment_id, allow_aliased)
        )
        return {}

    # Domains
    def list_pages_domains(self, account_id, project_name):
        self.calls.append(("list_pages_domains", account_id, project_name))
        return [dict(d) for d in self.domains]

    def add_pages_domain(self, account_id, project_name, domain_name):
        self.calls.append(("add_pages_domain", account_id, project_name, domain_name))
        return dict(self.domain_result)

    def get_pages_domain(self, account_id, project_name, domain_name):
        self.calls.append(("get_pages_domain", account_id, project_name, domain_name))
        return dict(self.domain_result)

    def revalidate_pages_domain(self, account_id, project_name, domain_name):
        self.calls.append(("revalidate_pages_domain", account_id, project_name, domain_name))
        return dict(self.domain_result)

    def delete_pages_domain(self, account_id, project_name, domain_name):
        self.calls.append(("delete_pages_domain", account_id, project_name, domain_name))
        return {}


@pytest.fixture()
def fake_client(monkeypatch):
    fake = _FakePagesClient()
    monkeypatch.setattr(pages_module, "get_client", lambda: fake)
    return fake


runner = CliRunner()


# --------------------------------------------------------------------------
# Client: projects.
# --------------------------------------------------------------------------


def test_list_pages_projects_paginates_and_authenticates(monkeypatch):
    # Live /pages/projects rejects per_page > 10 with a 400, so the client
    # caps every request at 10 regardless of the requested limit.
    pages = [
        [_project(i) for i in range(0, 10)],
        [_project(i) for i in range(10, 20)],
        [_project(i) for i in range(20, 30)],
    ]
    responses = [
        _FakeResponse(
            200,
            {
                "success": True,
                "errors": [],
                "result": page_items,
                "result_info": {"total_pages": 3},
            },
        )
        for page_items in pages
    ]
    client, transport = _build_client(monkeypatch, responses)

    result = client.list_pages_projects(ACCOUNT_ID, limit=30)

    assert [p["name"] for p in result] == [f"site-{i}" for i in range(30)]
    assert len(transport.calls) == 3
    assert transport.calls[0]["url"].endswith(f"/accounts/{ACCOUNT_ID}/pages/projects")
    assert [call["params"] for call in transport.calls] == [
        {"per_page": 10, "page": 1},
        {"per_page": 10, "page": 2},
        {"per_page": 10, "page": 3},
    ]
    assert transport.calls[0]["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_get_pages_project_hits_project_path(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(_project(1))])

    result = client.get_pages_project(ACCOUNT_ID, PROJECT_NAME)

    assert result["name"] == "site-1"
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}")


def test_create_pages_project_posts_required_fields(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(_project(1))])

    result = client.create_pages_project(
        ACCOUNT_ID, PROJECT_NAME, "main", config={"build_config": {"build_command": "npm run build"}}
    )

    assert result["name"] == "site-1"
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/pages/projects")
    assert call["json"]["name"] == PROJECT_NAME
    assert call["json"]["production_branch"] == "main"
    assert call["json"]["build_config"] == {"build_command": "npm run build"}


def test_patch_pages_project_uses_patch_method(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(_project(1))])
    body = {"production_branch": "develop"}

    client.patch_pages_project(ACCOUNT_ID, PROJECT_NAME, body)

    call = transport.calls[0]
    assert call["method"] == "PATCH"
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}")
    assert call["json"] == {"production_branch": "develop"}


def test_delete_pages_project_uses_delete_method(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok({"id": PROJECT_NAME})])

    client.delete_pages_project(ACCOUNT_ID, PROJECT_NAME)

    call = transport.calls[0]
    assert call["method"] == "DELETE"
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}")


def test_purge_build_cache_and_upload_token_paths(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok({}), _ok({"jwt": "t"})])

    client.purge_pages_build_cache(ACCOUNT_ID, PROJECT_NAME)
    token = client.get_pages_upload_token(ACCOUNT_ID, PROJECT_NAME)

    assert token == {"jwt": "t"}
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["url"].endswith(
        f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/purge_build_cache"
    )
    assert transport.calls[1]["method"] == "GET"
    assert transport.calls[1]["url"].endswith(
        f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/upload-token"
    )


# --------------------------------------------------------------------------
# Client: deployments.
# --------------------------------------------------------------------------


def test_list_pages_deployments_sends_env_param(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok([_deployment(0)])])

    result = client.list_pages_deployments(ACCOUNT_ID, PROJECT_NAME, limit=10, env="production")

    assert len(result) == 1
    call = transport.calls[0]
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/deployments")
    assert call["params"] == {"per_page": 10, "page": 1, "env": "production"}


def test_list_pages_deployments_keeps_default_25_per_request(monkeypatch):
    # Unlike /pages/projects, the deployments endpoint accepts per_page up
    # to 25, so its pagination keeps the larger default cap.
    first = _FakeResponse(
        200,
        {
            "success": True,
            "errors": [],
            "result": [_deployment(i) for i in range(25)],
            "result_info": {"total_pages": 2},
        },
    )
    client, transport = _build_client(
        monkeypatch, [first, _ok([_deployment(i) for i in range(25, 30)])]
    )

    result = client.list_pages_deployments(ACCOUNT_ID, PROJECT_NAME, limit=30)

    assert len(result) == 30
    assert [call["params"] for call in transport.calls] == [
        {"per_page": 25, "page": 1},
        {"per_page": 5, "page": 2},
    ]


def test_get_pages_deployment_hits_deployment_path(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(_deployment(1))])

    client.get_pages_deployment(ACCOUNT_ID, PROJECT_NAME, DEPLOYMENT_ID)

    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["url"].endswith(
        f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/deployments/{DEPLOYMENT_ID}"
    )


def test_create_pages_deployment_builds_multipart_form(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(_deployment(1))])

    result = client.create_pages_deployment(
        ACCOUNT_ID,
        PROJECT_NAME,
        branch="main",
        commit_message="ship it",
        commit_dirty=True,
        manifest='{"index.html":"abc"}',
    )

    assert result["id"] == "deploy-1"
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/deployments")
    assert call["json"] is None
    # Multipart must not carry the JSON Content-Type header.
    assert "Content-Type" not in call["headers"]
    parts = {field_name: value for field_name, (_, value, _) in call["files"].items()}
    assert parts["branch"] == "main"
    assert parts["commit_message"] == "ship it"
    assert parts["commit_dirty"] == "true"
    assert parts["manifest"] == '{"index.html":"abc"}'
    for _, _, media_type in call["files"].values():
        assert media_type is None


def test_delete_pages_deployment_force_param_only_when_allow_aliased(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok({}), _ok({})])

    client.delete_pages_deployment(ACCOUNT_ID, PROJECT_NAME, DEPLOYMENT_ID)
    client.delete_pages_deployment(ACCOUNT_ID, PROJECT_NAME, DEPLOYMENT_ID, allow_aliased=True)

    plain = transport.calls[0]
    forced = transport.calls[1]
    assert plain["method"] == "DELETE"
    assert plain["params"] is None
    assert forced["params"] == {"force": "true"}
    expected_url_suffix = (
        f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/deployments/{DEPLOYMENT_ID}"
    )
    assert plain["url"].endswith(expected_url_suffix)
    assert forced["url"] == plain["url"]


def test_retry_and_rollback_hit_action_paths(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(_deployment(1)), _ok(_deployment(1))])

    client.retry_pages_deployment(ACCOUNT_ID, PROJECT_NAME, DEPLOYMENT_ID)
    client.rollback_pages_deployment(ACCOUNT_ID, PROJECT_NAME, DEPLOYMENT_ID)

    retry_call, rollback_call = transport.calls
    assert retry_call["method"] == "POST"
    assert retry_call["url"].endswith(
        f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/deployments/{DEPLOYMENT_ID}/retry"
    )
    assert rollback_call["method"] == "POST"
    assert rollback_call["url"].endswith(
        f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/deployments/{DEPLOYMENT_ID}/rollback"
    )


# --------------------------------------------------------------------------
# Client: domains.
# --------------------------------------------------------------------------


def test_list_pages_domains_single_unpaginated_request(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok([_domain(1)])])

    result = client.list_pages_domains(ACCOUNT_ID, PROJECT_NAME)

    assert len(result) == 1
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["params"] is None
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/domains")


def test_add_pages_domain_posts_name_body(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(_domain(1))])

    client.add_pages_domain(ACCOUNT_ID, PROJECT_NAME, DOMAIN_NAME)

    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/domains")
    assert call["json"] == {"name": DOMAIN_NAME}


def test_revalidate_pages_domain_uses_patch_with_empty_body(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(_domain(1))])

    client.revalidate_pages_domain(ACCOUNT_ID, PROJECT_NAME, DOMAIN_NAME)

    call = transport.calls[0]
    assert call["method"] == "PATCH"
    assert call["url"].endswith(
        f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/domains/{DOMAIN_NAME}"
    )
    assert call["json"] == {}


def test_delete_pages_domain_uses_delete_method(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok({})])

    client.delete_pages_domain(ACCOUNT_ID, PROJECT_NAME, DOMAIN_NAME)

    call = transport.calls[0]
    assert call["method"] == "DELETE"
    assert call["url"].endswith(
        f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/domains/{DOMAIN_NAME}"
    )


# --------------------------------------------------------------------------
# Permission-group mapping for Pages endpoints.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, endpoint, expected",
    [
        ("GET", f"/accounts/{ACCOUNT_ID}/pages/projects", "Pages Read"),
        ("POST", f"/accounts/{ACCOUNT_ID}/pages/projects", "Pages Write"),
        ("PATCH", f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}", "Pages Write"),
        (
            "DELETE",
            f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/deployments/{DEPLOYMENT_ID}",
            "Pages Write",
        ),
        (
            "GET",
            f"/accounts/{ACCOUNT_ID}/pages/projects/{PROJECT_NAME}/domains",
            "Pages Read",
        ),
    ],
)
def test_pages_permission_group_mapping(method, endpoint, expected):
    assert required_permission_group(method, endpoint) == expected


# --------------------------------------------------------------------------
# Command layer: projects.
# --------------------------------------------------------------------------


def test_projects_list_command_json_defaults_to_single_account(fake_client):
    result = runner.invoke(pages_module.projects_app, ["list"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert [p["name"] for p in parsed] == ["site-1", "site-2"]
    assert ("list_pages_projects", ACCOUNT_ID, 100) in fake_client.calls


def test_projects_list_command_applies_filter_and_properties(fake_client):
    result = runner.invoke(
        pages_module.projects_app,
        ["list", "--filter", "name:eq:site-1", "--properties", "name"],
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed == [{"name": "site-1"}]


def test_projects_list_command_table_columns(fake_client):
    result = runner.invoke(pages_module.projects_app, ["list", "--table"])

    assert result.exit_code == 0
    out = result.stdout
    for header in ("ID", "Name", "Production Branch", "Created"):
        assert header in out
    assert "site-1" in out
    assert "main" in out
    # No raw ISO timestamps in table output.
    assert "2026-01-15T" not in out
    assert "2026-01-15" in out


def test_projects_list_command_accepts_explicit_account(fake_client):
    result = runner.invoke(
        pages_module.projects_app, ["list", "my-account", "--properties", "name"]
    )

    assert result.exit_code == 0
    assert ("resolve_account_id", "my-account") in fake_client.calls


def test_projects_get_command_json_output(fake_client):
    result = runner.invoke(pages_module.projects_app, ["get", PROJECT_NAME])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["name"] == "site-9"
    assert ("get_pages_project", ACCOUNT_ID, PROJECT_NAME) in fake_client.calls


def test_projects_create_command_requires_production_branch(fake_client):
    result = runner.invoke(pages_module.projects_app, ["create", PROJECT_NAME])

    assert result.exit_code != 0
    assert all(c[0] != "create_pages_project" for c in fake_client.calls)


def test_projects_create_command_passes_branch_and_config(fake_client):
    result = runner.invoke(
        pages_module.projects_app,
        [
            "create",
            PROJECT_NAME,
            "--production-branch",
            "main",
            "--config",
            '{"build_config":{"build_command":"npm run build"}}',
        ],
    )

    assert result.exit_code == 0
    entry = next(c for c in fake_client.calls if c[0] == "create_pages_project")
    _, account_id, name, production_branch, config = entry
    assert account_id == ACCOUNT_ID
    assert name == PROJECT_NAME
    assert production_branch == "main"
    assert config == {"build_config": {"build_command": "npm run build"}}


def test_projects_update_command_builds_patch_body(fake_client):
    result = runner.invoke(
        pages_module.projects_app,
        ["update", PROJECT_NAME, "--production-branch", "develop", "--build-command", "npm run build"],
    )

    assert result.exit_code == 0
    entry = next(c for c in fake_client.calls if c[0] == "patch_pages_project")
    data = entry[3]
    assert data["production_branch"] == "develop"
    assert data["build_config"] == {"build_command": "npm run build"}


def test_projects_update_command_rejects_empty_update(fake_client):
    result = runner.invoke(pages_module.projects_app, ["update", PROJECT_NAME])

    assert result.exit_code == 1
    assert "At least one setting must be specified" in result.output
    assert all(c[0] != "patch_pages_project" for c in fake_client.calls)


def test_projects_update_command_merges_config_last(fake_client):
    result = runner.invoke(
        pages_module.projects_app,
        [
            "update",
            PROJECT_NAME,
            "--config",
            '{"deployment_configs":{"preview":{"env_vars":{"API_URL":{"value":"https://x.test"}}}}}',
        ],
    )

    assert result.exit_code == 0
    entry = next(c for c in fake_client.calls if c[0] == "patch_pages_project")
    data = entry[3]
    assert "deployment_configs" in data


def test_projects_delete_command_requires_confirmation_in_non_tty(fake_client):
    result = runner.invoke(pages_module.projects_app, ["delete", PROJECT_NAME])

    assert result.exit_code != 0
    assert "Refusing to delete Pages project" in result.output
    assert "--force" in result.output
    assert all(c[0] != "delete_pages_project" for c in fake_client.calls)


def test_projects_delete_command_force_skips_prompt(fake_client):
    result = runner.invoke(pages_module.projects_app, ["delete", PROJECT_NAME, "--force"])

    assert result.exit_code == 0
    assert f"Deleted Pages project {PROJECT_NAME}" in result.output
    assert ("delete_pages_project", ACCOUNT_ID, PROJECT_NAME) in fake_client.calls


def test_projects_purge_build_cache_requires_confirmation_in_non_tty(fake_client):
    result = runner.invoke(pages_module.projects_app, ["purge-build-cache", PROJECT_NAME])

    assert result.exit_code != 0
    assert "Refusing to purge build cache" in result.output
    assert all(c[0] != "purge_pages_build_cache" for c in fake_client.calls)


def test_projects_purge_build_cache_force_runs(fake_client):
    result = runner.invoke(pages_module.projects_app, ["purge-build-cache", PROJECT_NAME, "--force"])

    assert result.exit_code == 0
    assert ("purge_pages_build_cache", ACCOUNT_ID, PROJECT_NAME) in fake_client.calls


def test_projects_get_upload_token_prints_result(fake_client):
    result = runner.invoke(pages_module.projects_app, ["get-upload-token", PROJECT_NAME])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed == {"jwt": "fake-upload-token"}
    assert ("get_pages_upload_token", ACCOUNT_ID, PROJECT_NAME) in fake_client.calls


# --------------------------------------------------------------------------
# Command layer: deployments.
# --------------------------------------------------------------------------


def test_deployments_list_command_json_output(fake_client):
    result = runner.invoke(pages_module.deployments_app, ["list", PROJECT_NAME])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert [d["id"] for d in parsed] == ["deploy-1", "deploy-2"]
    assert ("list_pages_deployments", ACCOUNT_ID, PROJECT_NAME, 100, None) in fake_client.calls


def test_deployments_list_command_env_flag(fake_client):
    result = runner.invoke(
        pages_module.deployments_app, ["list", PROJECT_NAME, "--env", "production"]
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert all(d["env"] == "production" for d in parsed)
    assert ("list_pages_deployments", ACCOUNT_ID, PROJECT_NAME, 100, "production") in fake_client.calls


def test_deployments_list_command_table_flattening(fake_client):
    result = runner.invoke(pages_module.deployments_app, ["list", PROJECT_NAME, "--table"])

    assert result.exit_code == 0
    out = result.stdout
    for header in ("ID", "Env", "Branch", "Status", "Created"):
        assert header in out
    assert "deploy-1" in out
    assert "success" in out
    assert "2026-02-20T" not in out


def test_deployments_get_command_json_output(fake_client):
    result = runner.invoke(
        pages_module.deployments_app, ["get", PROJECT_NAME, DEPLOYMENT_ID]
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["id"] == "deploy-9"


def test_deployments_create_command_passes_flags(fake_client):
    result = runner.invoke(
        pages_module.deployments_app,
        [
            "create",
            PROJECT_NAME,
            "--branch",
            "feature-x",
            "--commit-message",
            "add docs",
            "--commit-dirty",
            "--manifest",
            '{"index.html":"abc"}',
        ],
    )

    assert result.exit_code == 0
    entry = next(c for c in fake_client.calls if c[0] == "create_pages_deployment")
    kwargs = entry[1]
    assert kwargs["account_id"] == ACCOUNT_ID
    assert kwargs["project_name"] == PROJECT_NAME
    assert kwargs["branch"] == "feature-x"
    assert kwargs["commit_message"] == "add docs"
    assert kwargs["commit_dirty"] is True
    assert kwargs["manifest"] == '{"index.html": "abc"}'


def test_deployments_create_command_rejects_non_object_manifest(fake_client):
    result = runner.invoke(
        pages_module.deployments_app,
        ["create", PROJECT_NAME, "--manifest", '["not-an-object"]'],
    )

    assert result.exit_code == 1
    assert "--manifest must be a JSON object" in result.output
    assert all(c[0] != "create_pages_deployment" for c in fake_client.calls)


def test_deployments_retry_command(fake_client):
    result = runner.invoke(
        pages_module.deployments_app, ["retry", PROJECT_NAME, DEPLOYMENT_ID]
    )

    assert result.exit_code == 0
    assert ("retry_pages_deployment", ACCOUNT_ID, PROJECT_NAME, DEPLOYMENT_ID) in fake_client.calls


def test_deployments_rollback_requires_confirmation_in_non_tty(fake_client):
    result = runner.invoke(
        pages_module.deployments_app, ["rollback", PROJECT_NAME, DEPLOYMENT_ID]
    )

    assert result.exit_code != 0
    assert "Refusing to roll production back" in result.output
    assert all(c[0] != "rollback_pages_deployment" for c in fake_client.calls)


def test_deployments_rollback_force_runs(fake_client):
    result = runner.invoke(
        pages_module.deployments_app, ["rollback", PROJECT_NAME, DEPLOYMENT_ID, "--force"]
    )

    assert result.exit_code == 0
    assert ("rollback_pages_deployment", ACCOUNT_ID, PROJECT_NAME, DEPLOYMENT_ID) in fake_client.calls


def test_deployments_delete_requires_confirmation_in_non_tty(fake_client):
    result = runner.invoke(
        pages_module.deployments_app, ["delete", PROJECT_NAME, DEPLOYMENT_ID]
    )

    assert result.exit_code != 0
    assert "Refusing to delete deployment" in result.output
    assert all(c[0] != "delete_pages_deployment" for c in fake_client.calls)


def test_deployments_delete_force_without_allow_aliased(fake_client):
    result = runner.invoke(
        pages_module.deployments_app, ["delete", PROJECT_NAME, DEPLOYMENT_ID, "--force"]
    )

    assert result.exit_code == 0
    assert ("delete_pages_deployment", ACCOUNT_ID, PROJECT_NAME, DEPLOYMENT_ID, False) in fake_client.calls


def test_deployments_delete_allow_aliased_flag_forwarded(fake_client):
    result = runner.invoke(
        pages_module.deployments_app,
        ["delete", PROJECT_NAME, DEPLOYMENT_ID, "--allow-aliased", "--force"],
    )

    assert result.exit_code == 0
    assert ("delete_pages_deployment", ACCOUNT_ID, PROJECT_NAME, DEPLOYMENT_ID, True) in fake_client.calls


# --------------------------------------------------------------------------
# Command layer: domains.
# --------------------------------------------------------------------------


def test_domains_list_command_json_output(fake_client):
    result = runner.invoke(pages_module.domains_app, ["list", PROJECT_NAME])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert [d["name"] for d in parsed] == ["docs1.example.com"]
    assert ("list_pages_domains", ACCOUNT_ID, PROJECT_NAME) in fake_client.calls


def test_domains_list_command_applies_filter_limit_properties(fake_client):
    result = runner.invoke(
        pages_module.domains_app,
        ["list", PROJECT_NAME, "--filter", "status:eq:pending", "--limit", "5", "--properties", "name"],
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    # The active domain is filtered out client-side by status:eq:pending.
    assert parsed == []


def test_domains_list_command_table_columns(fake_client):
    result = runner.invoke(pages_module.domains_app, ["list", PROJECT_NAME, "--table"])

    assert result.exit_code == 0
    out = result.stdout
    for header in ("Domain", "Status", "Created", "Modified"):
        assert header in out
    assert "docs1.example.com" in out
    assert "active" in out


def test_domains_get_command_json_output(fake_client):
    result = runner.invoke(
        pages_module.domains_app, ["get", PROJECT_NAME, DOMAIN_NAME]
    )

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["name"] == "docs9.example.com"


def test_domains_create_command_posts_domain(fake_client):
    result = runner.invoke(
        pages_module.domains_app, ["create", PROJECT_NAME, DOMAIN_NAME]
    )

    assert result.exit_code == 0
    assert ("add_pages_domain", ACCOUNT_ID, PROJECT_NAME, DOMAIN_NAME) in fake_client.calls


def test_domains_update_command_revalidates(fake_client):
    result = runner.invoke(
        pages_module.domains_app, ["update", PROJECT_NAME, DOMAIN_NAME]
    )

    assert result.exit_code == 0
    assert ("revalidate_pages_domain", ACCOUNT_ID, PROJECT_NAME, DOMAIN_NAME) in fake_client.calls


def test_domains_delete_requires_confirmation_in_non_tty(fake_client):
    result = runner.invoke(
        pages_module.domains_app, ["delete", PROJECT_NAME, DOMAIN_NAME]
    )

    assert result.exit_code != 0
    assert "Refusing to delete Pages domain" in result.output
    assert all(c[0] != "delete_pages_domain" for c in fake_client.calls)


def test_domains_delete_force_runs(fake_client):
    result = runner.invoke(
        pages_module.domains_app, ["delete", PROJECT_NAME, DOMAIN_NAME, "--force"]
    )

    assert result.exit_code == 0
    assert ("delete_pages_domain", ACCOUNT_ID, PROJECT_NAME, DOMAIN_NAME) in fake_client.calls


# --------------------------------------------------------------------------
# Direct-upload asset deploys (--directory).
# Protocol mirrored from wrangler 4.125.0; hash parity with the bundled
# blake3-wasm build was verified byte-for-byte before pinning the constant.
# --------------------------------------------------------------------------

WRANGLER_PARITY_HASH = "e2d19b823f138bc36bc735f95942b3c6"  # blake3(b64("hello world") + "txt")[:32]


def test_hash_file_matches_wrangler_blake3wasm(tmp_path):
    from cloudflare_cli.pages_assets import hash_file

    target = tmp_path / "sample.txt"
    target.write_bytes(b"hello world")

    assert hash_file(target) == WRANGLER_PARITY_HASH


def test_collect_files_applies_wrangler_ignore_list(tmp_path):
    from cloudflare_cli.pages_assets import collect_files

    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "data.json").write_text("{}")
    # Root-only ignores:
    (tmp_path / "_headers").write_text("/*\n  X-Test: 1\n")
    (tmp_path / "_redirects").write_text("/old /new 301\n")
    (tmp_path / "_routes.json").write_text("{}")
    (tmp_path / "_worker.js").write_text("//")
    (tmp_path / ".wrangler").mkdir()
    functions_dir = tmp_path / "functions"
    functions_dir.mkdir()
    (functions_dir / "foo.js").write_text("//")
    # Any-depth ignores:
    (tmp_path / ".DS_Store").write_bytes(b"\x00")
    (tmp_path / "assets" / ".DS_Store").write_bytes(b"\x00")
    node_modules_dir = tmp_path / "node_modules" / "pkg"
    node_modules_dir.mkdir(parents=True)
    (node_modules_dir / "x.js").write_text("//")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    nested_git_dir = tmp_path / "sub" / ".git"
    nested_git_dir.mkdir()

    assets = collect_files(tmp_path)

    rels = [a["rel"] for a in assets]
    assert rels == sorted(["index.html", "assets/app.js", "sub/data.json"])
    by_rel = {a["rel"]: a for a in assets}
    assert by_rel["assets/app.js"]["content_type"] == "application/javascript"
    assert by_rel["index.html"]["content_type"] == "text/html"


def test_collect_files_rejects_missing_and_empty_directories(tmp_path):
    from cloudflare_cli.pages_assets import collect_files

    with pytest.raises(ClientError, match="does not exist"):
        collect_files(tmp_path / "nope")

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ClientError, match="No uploadable files"):
        collect_files(empty)


def test_collect_files_rejects_oversize_files(tmp_path):
    from cloudflare_cli.pages_assets import MAX_ASSET_SIZE
    from cloudflare_cli.pages_assets import collect_files

    big = tmp_path / "big.bin"
    with open(big, "wb") as fh:
        fh.truncate(MAX_ASSET_SIZE + 1)

    with pytest.raises(ClientError, match="25 MiB"):
        collect_files(tmp_path)


def test_bucket_files_respects_size_and_count_caps():
    from cloudflare_cli.pages_assets import (
        MAX_BUCKET_FILE_COUNT,
        MAX_BUCKET_SIZE,
        bucket_files,
    )

    big_assets = [
        {"rel": f"f{i}", "size": MAX_BUCKET_SIZE // 2, "hash": f"h{i}"} for i in range(3)
    ]
    buckets = bucket_files(big_assets)
    assert len(buckets) == 2
    assert [len(b) for b in buckets] == [2, 1]

    many_assets = [
        {"rel": f"g{i}", "size": 1, "hash": f"h{i}"}
        for i in range(MAX_BUCKET_FILE_COUNT + 5)
    ]
    count_buckets = bucket_files(many_assets)
    assert len(count_buckets[-1]) == 5
    assert all(len(b) <= MAX_BUCKET_FILE_COUNT for b in count_buckets)
    assert all(sum(a["size"] for a in b) <= MAX_BUCKET_SIZE for b in count_buckets)


def test_build_manifest_keys_have_leading_slash():
    from cloudflare_cli.pages_assets import build_manifest

    manifest = build_manifest(
        [
            {"rel": "index.html", "hash": "h1"},
            {"rel": "blog/post/index.html", "hash": "h2"},
        ]
    )

    assert manifest == {"/index.html": "h1", "/blog/post/index.html": "h2"}


def test_check_missing_page_assets_posts_jwt_auth(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(["missing-hash"])])

    missing = client.check_missing_page_assets("fake-jwt", ["h1", "h2"])

    assert missing == ["missing-hash"]
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/pages/assets/check-missing")
    assert call["headers"]["Authorization"] == "Bearer fake-jwt"
    assert call["json"] == {"hashes": ["h1", "h2"]}


def test_upload_page_assets_sends_batch_records(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok({})])
    payload = [
        {
            "key": "abc",
            "value": "aGVsbG8=",
            "metadata": {"contentType": "text/html"},
            "base64": True,
        }
    ]

    client.upload_page_assets("fake-jwt", payload)

    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/pages/assets/upload")
    assert call["headers"]["Authorization"] == "Bearer fake-jwt"
    assert call["json"] == payload


def test_upsert_page_asset_hashes_posts_all_hashes(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok({})])

    client.upsert_page_asset_hashes("fake-jwt", ["h1"])

    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/pages/assets/upsert-hashes")
    assert call["json"] == {"hashes": ["h1"]}


def test_create_pages_deployment_sends_headers_redirects_parts(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(dict(_deployment(9)))])

    client.create_pages_deployment(
        account_id=ACCOUNT_ID,
        project_name=PROJECT_NAME,
        manifest='{"/index.html": "h1"}',
        headers_text="/*\\n  X-Test: 1\\n",
        redirects_text="/old /new 301\\n",
    )

    files = transport.calls[0]["files"]
    assert files["_headers"] == ("_headers", "/*\\n  X-Test: 1\\n")
    assert files["_redirects"] == ("_redirects", "/old /new 301\\n")
    assert files["manifest"] == (None, '{"/index.html": "h1"}', None)


def test_deployments_create_directory_happy_path(fake_client, tmp_path):
    from cloudflare_cli.pages_assets import collect_files, hash_file

    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log(1)")
    (tmp_path / "_headers").write_text("/*\n  X-Foo: bar\n")
    ignored_dir = tmp_path / "node_modules" / "pkg"
    ignored_dir.mkdir(parents=True)
    (ignored_dir / "x.js").write_text("//")
    fake_client.missing_hashes = [a["hash"] for a in collect_files(tmp_path)]

    result = runner.invoke(
        pages_module.deployments_app,
        ["create", PROJECT_NAME, "--directory", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert parsed["id"] == "deploy-9"

    names = [c[0] for c in fake_client.calls]
    assert names == [
        "default_account_id",
        "get_pages_upload_token",
        "check_missing_page_assets",
        "upload_page_assets",
        "upsert_page_asset_hashes",
        "create_pages_deployment",
    ]

    create_kwargs = dict(next(c for c in fake_client.calls if c[0] == "create_pages_deployment")[1])
    manifest = json.loads(create_kwargs["manifest"])
    assert set(manifest) == {"/index.html", "/assets/app.js"}
    from cloudflare_cli.pages_assets import hash_file
    assert manifest["/index.html"] == hash_file(tmp_path / "index.html")
    assert create_kwargs["headers_text"] == "/*\n  X-Foo: bar\n"
    assert create_kwargs["redirects_text"] is None

    upload_calls = [c for c in fake_client.calls if c[0] == "upload_page_assets"]
    records = [r for c in upload_calls for r in c[2]]
    assert len(records) == 2
    js_record = next(r for r in records if r["metadata"]["contentType"] == "application/javascript")
    assert js_record["base64"] is True
    assert js_record["value"] == "Y29uc29sZS5sb2coMSk="  # base64("console.log(1)")


def test_deployments_create_directory_respects_missing_hashes(fake_client, tmp_path):
    from cloudflare_cli.pages_assets import hash_file

    index = tmp_path / "index.html"
    index.write_text("<h1>hi</h1>")
    other = tmp_path / "other.txt"
    other.write_text("fresh")
    fake_client.missing_hashes = [hash_file(index)]  # Cloudflare already has other.txt

    result = runner.invoke(
        pages_module.deployments_app,
        ["create", PROJECT_NAME, "--directory", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    uploaded_records = next(c for c in fake_client.calls if c[0] == "upload_page_assets")[2]
    assert len(uploaded_records) == 1
    assert uploaded_records[0]["key"] == hash_file(index)


def test_deployments_create_directory_skip_caching_uploads_everything(fake_client, tmp_path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>")

    result = runner.invoke(
        pages_module.deployments_app,
        ["create", PROJECT_NAME, "--directory", str(tmp_path), "--skip-caching"],
    )

    assert result.exit_code == 0, result.output
    names = [c[0] for c in fake_client.calls]
    assert "check_missing_page_assets" not in names
    upload_payloads = [c for c in fake_client.calls if c[0] == "upload_page_assets"]
    assert sum(len(c[2]) for c in upload_payloads) == 1


def test_deployments_create_rejects_directory_and_manifest_together(fake_client, tmp_path):
    result = runner.invoke(
        pages_module.deployments_app,
        ["create", PROJECT_NAME, "--directory", str(tmp_path), "--manifest", '{"ok":"1"}'],
    )

    assert result.exit_code == 1
    assert "--directory and --manifest are mutually exclusive" in result.output
    assert all(c[0] != "create_pages_deployment" for c in fake_client.calls)


def test_deployments_create_rejects_missing_directory(fake_client):
    result = runner.invoke(
        pages_module.deployments_app,
        ["create", PROJECT_NAME, "--directory", "/nonexistent/deploy-dir"],
    )

    assert result.exit_code == 1
    assert "does not exist or is not a directory" in result.output
    assert all(c[0] != "create_pages_upload_token" and c[0] != "get_pages_upload_token" for c in fake_client.calls)


# --------------------------------------------------------------------------
# Cloudflare Pages Advanced Mode (_worker.js upload).
# Multipart shape verified byte-for-byte against wrangler 4.125.0's actual
# undici FormData/File/Response output for a config-less, no-bindings,
# single-module deploy before this was implemented: metadata is exactly
# {"main_module": "<filename>"}, the module part carries
# Content-Type: application/javascript+module, and the outer
# "_worker.bundle" field itself carries Content-Type: application/octet-stream
# (the File() constructor does not inherit the inner Blob's multipart type).
# --------------------------------------------------------------------------


def _decode_multipart(body: bytes):
    """Parse a multipart/form-data body into {part_name: (headers, content)}."""
    import email
    from email.message import Message

    first_line = body.split(b"\r\n", 1)[0]
    boundary = first_line[2:]  # strip leading "--"
    header_bytes = b'Content-Type: multipart/form-data; boundary="' + boundary + b'"\r\n\r\n'
    msg = email.message_from_bytes(header_bytes + body)
    parts = {}
    for part in msg.get_payload():
        assert isinstance(part, Message)
        name = part.get_param("name", header="Content-Disposition")
        parts[name] = (dict(part.items()), part.get_payload(decode=True))
    return parts


def test_read_worker_script_returns_none_without_worker_js(tmp_path):
    from cloudflare_cli.pages_assets import read_worker_script

    (tmp_path / "index.html").write_text("<h1>hi</h1>")

    assert read_worker_script(tmp_path) is None


def test_read_worker_script_reads_file_and_routes_json(tmp_path):
    from cloudflare_cli.pages_assets import read_worker_script

    (tmp_path / "_worker.js").write_text("export default { fetch() { return new Response('hi'); } };\n")
    (tmp_path / "_routes.json").write_text('{"version": 1, "include": ["/*"]}')

    result = read_worker_script(tmp_path)

    assert result["filename"] == "_worker.js"
    assert result["content"] == b"export default { fetch() { return new Response('hi'); } };\n"
    assert result["routes_json"] == '{"version": 1, "include": ["/*"]}'


def test_read_worker_script_omits_routes_json_when_absent(tmp_path):
    from cloudflare_cli.pages_assets import read_worker_script

    (tmp_path / "_worker.js").write_text("export default { fetch() { return new Response('hi'); } };\n")

    result = read_worker_script(tmp_path)

    assert result["routes_json"] is None


def test_read_worker_script_rejects_worker_js_directory(tmp_path):
    from cloudflare_cli.pages_assets import read_worker_script

    worker_dir = tmp_path / "_worker.js"
    worker_dir.mkdir()
    (worker_dir / "index.js").write_text("export default {};")

    with pytest.raises(ClientError, match="multi-file Cloudflare Pages Advanced Mode"):
        read_worker_script(tmp_path)


def test_read_worker_script_rejects_functions_dir_without_worker_js(tmp_path):
    from cloudflare_cli.pages_assets import read_worker_script

    functions_dir = tmp_path / "functions"
    functions_dir.mkdir()
    (functions_dir / "hello.js").write_text("export function onRequest() {}")

    with pytest.raises(ClientError, match="Cloudflare Pages Functions require"):
        read_worker_script(tmp_path)


def test_read_worker_script_ignores_functions_dir_when_worker_js_present(tmp_path):
    from cloudflare_cli.pages_assets import read_worker_script

    (tmp_path / "_worker.js").write_text("export default { fetch() { return new Response('hi'); } };\n")
    functions_dir = tmp_path / "functions"
    functions_dir.mkdir()
    (functions_dir / "hello.js").write_text("export function onRequest() {}")

    # Advanced Mode ignores functions/ entirely (matches wrangler); no error.
    result = read_worker_script(tmp_path)
    assert result["filename"] == "_worker.js"


def test_read_worker_script_rejects_unbundleable_import(tmp_path):
    from cloudflare_cli.pages_assets import read_worker_script

    (tmp_path / "_worker.js").write_text(
        "import helper from './helper.js';\nexport default { fetch() { return helper(); } };\n"
    )

    with pytest.raises(ClientError, match="importing from './helper.js'"):
        read_worker_script(tmp_path)


def test_read_worker_script_allows_node_and_cloudflare_builtins(tmp_path):
    from cloudflare_cli.pages_assets import read_worker_script

    (tmp_path / "_worker.js").write_text(
        "import { Buffer } from 'node:buffer';\n"
        "import { WorkerEntrypoint } from 'cloudflare:workers';\n"
        "export default { fetch() { return new Response(String(Buffer)); } };\n"
    )

    result = read_worker_script(tmp_path)
    assert result["filename"] == "_worker.js"


def test_build_worker_bundle_matches_wrangler_shape(monkeypatch):
    client, _ = _build_client(monkeypatch, [])

    bundle = client.build_worker_bundle(
        {"filename": "_worker.js", "content": b"export default { fetch() {} };\n"}
    )

    parts = _decode_multipart(bundle)
    assert set(parts) == {"metadata", "_worker.js"}

    metadata_headers, metadata_content = parts["metadata"]
    assert json.loads(metadata_content) == {"main_module": "_worker.js"}
    assert "Content-Type" not in metadata_headers  # plain field, no explicit type

    module_headers, module_content = parts["_worker.js"]
    assert module_headers["Content-Type"] == "application/javascript+module"
    assert module_content == b"export default { fetch() {} };\n"


def test_create_pages_deployment_sends_worker_bundle_and_routes_json(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(dict(_deployment(9)))])

    client.create_pages_deployment(
        account_id=ACCOUNT_ID,
        project_name=PROJECT_NAME,
        manifest='{"/index.html": "h1"}',
        worker_bundle=b"RAW-BUNDLE-BYTES",
        routes_json_text='{"version": 1}',
    )

    files = transport.calls[0]["files"]
    assert files["_worker.bundle"] == ("_worker.bundle", b"RAW-BUNDLE-BYTES", "application/octet-stream")
    assert files["_routes.json"] == ("_routes.json", '{"version": 1}')


def test_create_pages_deployment_omits_worker_bundle_by_default(monkeypatch):
    client, transport = _build_client(monkeypatch, [_ok(dict(_deployment(9)))])

    client.create_pages_deployment(
        account_id=ACCOUNT_ID,
        project_name=PROJECT_NAME,
        manifest='{"/index.html": "h1"}',
    )

    files = transport.calls[0]["files"]
    assert "_worker.bundle" not in files
    assert "_routes.json" not in files


def test_deployments_create_directory_uploads_worker_bundle(fake_client, tmp_path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    (tmp_path / "_worker.js").write_text(
        "export default { fetch(request, env) { return env.ASSETS.fetch(request); } };\n"
    )
    from cloudflare_cli.pages_assets import collect_files

    fake_client.missing_hashes = [a["hash"] for a in collect_files(tmp_path)]

    result = runner.invoke(
        pages_module.deployments_app,
        ["create", PROJECT_NAME, "--directory", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "Advanced Mode worker" in result.output

    build_call = next(c for c in fake_client.calls if c[0] == "build_worker_bundle")
    assert build_call[1]["filename"] == "_worker.js"

    create_kwargs = dict(next(c for c in fake_client.calls if c[0] == "create_pages_deployment")[1])
    assert create_kwargs["worker_bundle"] == b"FAKE-WORKER-BUNDLE:_worker.js"
    assert create_kwargs["routes_json_text"] is None

    # _worker.js itself must never appear in the static asset manifest.
    manifest = json.loads(create_kwargs["manifest"])
    assert "/_worker.js" not in manifest


def test_deployments_create_directory_rejects_worker_js_directory(fake_client, tmp_path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    worker_dir = tmp_path / "_worker.js"
    worker_dir.mkdir()
    (worker_dir / "index.js").write_text("export default {};")

    result = runner.invoke(
        pages_module.deployments_app,
        ["create", PROJECT_NAME, "--directory", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "multi-file Cloudflare Pages Advanced Mode" in result.output
    assert all(c[0] != "create_pages_deployment" for c in fake_client.calls)


def test_deployments_create_directory_rejects_functions_without_worker_js(fake_client, tmp_path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    functions_dir = tmp_path / "functions"
    functions_dir.mkdir()
    (functions_dir / "hello.js").write_text("export function onRequest() {}")

    result = runner.invoke(
        pages_module.deployments_app,
        ["create", PROJECT_NAME, "--directory", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "Cloudflare Pages Functions require" in result.output
    assert all(c[0] != "create_pages_deployment" for c in fake_client.calls)


