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
