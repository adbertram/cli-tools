"""
Tests for the Copilot Studio capacity pre-check.

Covers the deterministic entitlement gate in ``copilot_cli.capacity`` and its
enforcement in the attaching agent commands (``agent tool add``,
``agent knowledge add``, ``agent knowledge azure-ai-search add``):

An environment is entitled to attach tools/knowledge iff
  P1: a Copilot Studio currency (MCSMessages/MCSSessions/VAConversations) has a
      positive allocation, OR
  P2: it is covered by an Enabled pay-as-you-go billing policy.

A 404 on allocations means "no allocation" (P1 false, not an error). Any other
non-200/404 on allocations, or any non-200 on a policy's /environments lookup,
is undeterminable and raises ClientError. The attaching commands must NOT make
the add/associate call when not entitled. Agent create/update never touch the
licensing endpoints.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

import copilot_cli.capacity as capacity
import copilot_cli.commands.agent as agent
from copilot_cli.capacity import (
    COPILOT_STUDIO_CURRENCIES,
    CapacityError,
    environment_supports_tools_and_knowledge,
    resolve_environment_id,
)
from copilot_cli.client import ClientError


ENV_ID = "37035972-7593-e57b-a483-ed6ea9938316"
OTHER_ENV_ID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# httpx seam: a router keyed by URL substring, monkeypatched onto httpx.Client.get
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=None
            )

    def json(self) -> Any:
        return self._payload


def _install_http_router(monkeypatch, *, allocations, billing_policies=None,
                         policy_environments=None):
    """Route httpx.Client.get by URL and record which URLs were hit.

    allocations: (status_code, payload) for the allocations endpoint.
    billing_policies: (status_code, payload) for the billingPolicies list.
    policy_environments: dict {billing_policy_id: (status_code, payload)} for
        each policy's /environments lookup.
    """
    hits: list[str] = []
    policy_environments = policy_environments or {}

    # Avoid real token acquisition.
    monkeypatch.setattr(capacity, "get_access_token", lambda resource: "fake-token")

    def fake_get(self, url, headers=None, timeout=None):
        hits.append(url)
        if "/allocations" in url:
            status, payload = allocations
            return _FakeResponse(status, payload)
        if url.rstrip("&?").endswith("api-version=2022-03-01-preview") and (
            "/billingPolicies?" in url
        ):
            if billing_policies is None:
                raise AssertionError(f"unexpected billingPolicies list call: {url}")
            status, payload = billing_policies
            return _FakeResponse(status, payload)
        if "/billingPolicies/" in url and "/environments" in url:
            # Extract the policy id between /billingPolicies/ and /environments
            policy_id = url.split("/billingPolicies/", 1)[1].split("/environments", 1)[0]
            if policy_id not in policy_environments:
                raise AssertionError(f"unexpected policy environments call: {url}")
            status, payload = policy_environments[policy_id]
            return _FakeResponse(status, payload)
        raise AssertionError(f"unexpected GET url: {url}")

    monkeypatch.setattr(httpx.Client, "get", fake_get, raising=True)
    return hits


# Canonical fixtures mirroring live values.
ALLOC_404 = (404, {"status": 404, "error": {"code": "EnvironmentAllocationNotFound"}})
ALLOC_ZERO = (
    200,
    {"environmentId": ENV_ID, "currencyAllocations": [
        {"currencyType": "MCSMessages", "allocated": 0}
    ]},
)
ALLOC_ENTITLED = (
    200,
    {"environmentId": ENV_ID, "currencyAllocations": [
        {"currencyType": "MCSMessages", "allocated": 25000}
    ]},
)
ALLOC_NON_CS_CURRENCY = (
    200,
    {"environmentId": ENV_ID, "currencyAllocations": [
        {"currencyType": "PowerAppsPremium", "allocated": 99999}
    ]},
)
BILLING_EMPTY = (200, {"value": []})


# ---------------------------------------------------------------------------
# Unit-level: environment_supports_tools_and_knowledge
# ---------------------------------------------------------------------------


def test_currency_constant_is_exact():
    assert COPILOT_STUDIO_CURRENCIES == ("MCSMessages", "MCSSessions", "VAConversations")


def test_not_entitled_allocations_404_no_policy(monkeypatch):
    """Case 1 (unit): 404 allocations + empty billing policies -> not entitled."""
    _install_http_router(monkeypatch, allocations=ALLOC_404,
                         billing_policies=BILLING_EMPTY)
    assert environment_supports_tools_and_knowledge(ENV_ID) is False


def test_not_entitled_allocations_zero_no_policy(monkeypatch):
    """Case 2 (unit): MCSMessages allocated 0 + no policy -> not entitled."""
    _install_http_router(monkeypatch, allocations=ALLOC_ZERO,
                         billing_policies=BILLING_EMPTY)
    assert environment_supports_tools_and_knowledge(ENV_ID) is False


def test_entitled_via_p1(monkeypatch):
    """Case 3 (unit): MCSMessages allocated 25000 -> entitled; billing not consulted."""
    hits = _install_http_router(monkeypatch, allocations=ALLOC_ENTITLED)
    assert environment_supports_tools_and_knowledge(ENV_ID) is True
    # P1 short-circuits: no billingPolicies call.
    assert not any("billingPolicies" in u for u in hits)


def test_entitled_via_p2_matching_policy(monkeypatch):
    """Case 4 (unit): allocations 404 + Enabled policy covering env -> entitled."""
    _install_http_router(
        monkeypatch,
        allocations=ALLOC_404,
        billing_policies=(200, {"value": [
            {"billingPolicyId": "pol-1", "status": "Enabled"}
        ]}),
        policy_environments={"pol-1": (200, {"value": [ENV_ID]})},
    )
    assert environment_supports_tools_and_knowledge(ENV_ID) is True


def test_not_entitled_p2_nonmatching_policy(monkeypatch):
    """Case 4 variant: Enabled policy whose env list does NOT include target."""
    _install_http_router(
        monkeypatch,
        allocations=ALLOC_404,
        billing_policies=(200, {"value": [
            {"billingPolicyId": "pol-1", "status": "Enabled"}
        ]}),
        policy_environments={"pol-1": (200, {"value": [OTHER_ENV_ID]})},
    )
    assert environment_supports_tools_and_knowledge(ENV_ID) is False


def test_entitled_via_p2_object_env_items_case_insensitive(monkeypatch):
    """P2 env items may be objects; match is case-insensitive."""
    _install_http_router(
        monkeypatch,
        allocations=ALLOC_ZERO,
        billing_policies=(200, {"value": [
            {"id": "pol-9", "status": "Enabled"}
        ]}),
        policy_environments={"pol-9": (200, {"value": [
            {"name": ENV_ID.upper()}
        ]})},
    )
    assert environment_supports_tools_and_knowledge(ENV_ID) is True


def test_disabled_policy_is_ignored(monkeypatch):
    """A policy that is not Enabled must not entitle, and its /environments
    endpoint must not be queried."""
    hits = _install_http_router(
        monkeypatch,
        allocations=ALLOC_404,
        billing_policies=(200, {"value": [
            {"billingPolicyId": "pol-x", "status": "Disabled"}
        ]}),
        policy_environments={},
    )
    assert environment_supports_tools_and_knowledge(ENV_ID) is False
    assert not any("/environments" in u and "billingPolicies/" in u for u in hits)


def test_non_copilot_currency_does_not_entitle(monkeypatch):
    """A non-Copilot-Studio currency with allocated>0 must not entitle via P1."""
    _install_http_router(monkeypatch, allocations=ALLOC_NON_CS_CURRENCY,
                         billing_policies=BILLING_EMPTY)
    assert environment_supports_tools_and_knowledge(ENV_ID) is False


def test_undeterminable_allocations_403_raises(monkeypatch):
    """Case 5: allocations 403 -> raises ClientError (not CapacityError-as-False)."""
    _install_http_router(monkeypatch, allocations=(403, {"error": "forbidden"}))
    with pytest.raises(ClientError) as excinfo:
        environment_supports_tools_and_knowledge(ENV_ID)
    assert "403" in str(excinfo.value)
    assert not isinstance(excinfo.value, CapacityError)


def test_undeterminable_allocations_500_raises(monkeypatch):
    """Case 5: allocations 500 -> raises ClientError."""
    _install_http_router(monkeypatch, allocations=(500, {"error": "server"}))
    with pytest.raises(ClientError) as excinfo:
        environment_supports_tools_and_knowledge(ENV_ID)
    assert "500" in str(excinfo.value)


def test_undeterminable_policy_environments_500_raises(monkeypatch):
    """A non-200 on a policy's /environments lookup is undeterminable -> raises."""
    with pytest.raises(ClientError):
        _install_http_router(
            monkeypatch,
            allocations=ALLOC_404,
            billing_policies=(200, {"value": [
                {"billingPolicyId": "pol-1", "status": "Enabled"}
            ]}),
            policy_environments={"pol-1": (500, {"error": "server"})},
        )
        environment_supports_tools_and_knowledge(ENV_ID)


# ---------------------------------------------------------------------------
# resolve_environment_id
# ---------------------------------------------------------------------------


class _FakeConfig:
    def __init__(self, environment_id=None, dataverse_url=None):
        self.environment_id = environment_id
        self.dataverse_url = dataverse_url


def test_resolve_environment_id_from_config(monkeypatch):
    monkeypatch.setattr(
        capacity, "get_config", lambda: _FakeConfig(environment_id=ENV_ID)
    )
    assert resolve_environment_id() == ENV_ID


def test_resolve_environment_id_via_dataverse_url(monkeypatch):
    monkeypatch.setattr(
        capacity,
        "get_config",
        lambda: _FakeConfig(dataverse_url="https://org.crm.dynamics.com/"),
    )

    class _FakeClient:
        def list_environments(self):
            return [
                {"name": OTHER_ENV_ID, "properties": {
                    "linkedEnvironmentMetadata": {"instanceUrl": "https://other.crm.dynamics.com"}
                }},
                {"name": ENV_ID, "properties": {
                    "linkedEnvironmentMetadata": {"instanceUrl": "https://ORG.crm.dynamics.com"}
                }},
            ]

    monkeypatch.setattr("copilot_cli.client.get_client", lambda: _FakeClient())
    assert resolve_environment_id() == ENV_ID


def test_resolve_environment_id_unresolvable_raises(monkeypatch):
    """Case 7: neither environment_id nor a matchable dataverse_url -> raises."""
    monkeypatch.setattr(
        capacity, "get_config", lambda: _FakeConfig(environment_id=None, dataverse_url=None)
    )
    with pytest.raises(ClientError) as excinfo:
        resolve_environment_id()
    assert "Could not determine the Power Platform environment id" in str(excinfo.value)


def test_resolve_environment_id_dataverse_url_no_match_raises(monkeypatch):
    monkeypatch.setattr(
        capacity,
        "get_config",
        lambda: _FakeConfig(dataverse_url="https://nomatch.crm.dynamics.com"),
    )

    class _FakeClient:
        def list_environments(self):
            return [
                {"name": OTHER_ENV_ID, "properties": {
                    "linkedEnvironmentMetadata": {"instanceUrl": "https://other.crm.dynamics.com"}
                }},
            ]

    monkeypatch.setattr("copilot_cli.client.get_client", lambda: _FakeClient())
    with pytest.raises(ClientError):
        resolve_environment_id()


# ---------------------------------------------------------------------------
# ensure_tools_and_knowledge_entitled message
# ---------------------------------------------------------------------------


def test_ensure_raises_capacity_error_with_message(monkeypatch):
    monkeypatch.setattr(
        capacity, "environment_supports_tools_and_knowledge", lambda env: False
    )
    monkeypatch.setattr(
        capacity, "_resolve_environment_display_name", lambda env: "My Walled Env"
    )
    with pytest.raises(CapacityError) as excinfo:
        capacity.ensure_tools_and_knowledge_entitled(ENV_ID, action="attach tools")

    msg = str(excinfo.value)
    assert "My Walled Env" in msg
    assert ENV_ID in msg
    assert "no Copilot Studio capacity (Copilot Credits) allocated" in msg
    assert "not covered by a pay-as-you-go billing policy" in msg
    assert "tools and knowledge cannot be attached" in msg
    assert "https://admin.powerplatform.microsoft.com" in msg
    assert "Allocate prepaid Copilot Studio capacity" in msg
    assert "Link the environment to a pay-as-you-go billing policy" in msg
    assert "Use an environment that already has Copilot Studio capacity" in msg


def test_ensure_does_not_raise_when_entitled(monkeypatch):
    monkeypatch.setattr(
        capacity, "environment_supports_tools_and_knowledge", lambda env: True
    )
    # Should not raise and should not need a display name lookup.
    capacity.ensure_tools_and_knowledge_entitled(ENV_ID, action="attach tools")


# ---------------------------------------------------------------------------
# End-to-end command enforcement via Typer CliRunner
# ---------------------------------------------------------------------------

runner = CliRunner()


class _RecordingClient:
    """Fake DataverseClient that records whether a mutation was invoked."""

    def __init__(self):
        self.add_tool_called = False
        self.associate_called = False
        self.azure_search_called = False
        self.create_bot_called = False
        self.update_bot_called = False
        self.create_file_component_called = False
        self.delete_called = False
        self.upload_single_called = False
        self.upload_chunked_called = False

    def add_tool(self, **kwargs):
        self.add_tool_called = True
        return "comp-123"

    def associate_knowledge_with_agent(self, agent_id, component_id):
        self.associate_called = True
        return {"ok": True}

    def add_azure_ai_search_knowledge_source(self, **kwargs):
        self.azure_search_called = True
        return "comp-456"

    # ---- knowledge upload surface ----
    def list_knowledge_sources(self, agent_id, source_type=None):
        # By default no existing source; force-delete tests override this.
        return []

    def delete(self, path):
        self.delete_called = True
        return None

    def create_file_knowledge_component(self, **kwargs):
        self.create_file_component_called = True
        return "comp-file-789"

    def upload_file_single(self, *args, **kwargs):
        self.upload_single_called = True
        return {"ok": True}

    def upload_file_chunked(self, *args, **kwargs):
        self.upload_chunked_called = True
        return {"ok": True}

    # Minimal surface for create/update no-op paths (not used by attach tests).
    def get_bot(self, agent_id):
        return {"name": "Existing Agent"}

    def create_bot(self, **kwargs):
        self.create_bot_called = True
        return {"botid": "bot-1", "name": kwargs.get("name", "")}

    def update_bot(self, *args, **kwargs):
        self.update_bot_called = True
        return {"ok": True}


def _wire_command_test(monkeypatch, *, allocations, billing_policies=None,
                       policy_environments=None):
    """Patch get_client (recording), env-id resolution, and the http router."""
    client = _RecordingClient()
    monkeypatch.setattr(agent, "get_client", lambda: client)
    # Fixed env id so command tests don't depend on a real profile/config.
    monkeypatch.setattr(capacity, "resolve_environment_id", lambda: ENV_ID)
    # Display-name lookup must not hit the network in not-entitled paths.
    monkeypatch.setattr(
        capacity, "_resolve_environment_display_name", lambda env: "Test Env"
    )
    hits = _install_http_router(
        monkeypatch,
        allocations=allocations,
        billing_policies=billing_policies,
        policy_environments=policy_environments,
    )
    return client, hits


def test_command_tool_add_blocked_when_not_entitled(monkeypatch):
    """Case 1: `agent tool add` exits non-zero and never calls add_tool."""
    client, _ = _wire_command_test(
        monkeypatch, allocations=ALLOC_404, billing_policies=BILLING_EMPTY
    )
    result = runner.invoke(
        agent.app,
        ["tool", "add", "--agentId", "agent-1", "--toolType", "http",
         "--id", "tool-1"],
    )
    assert result.exit_code != 0
    assert client.add_tool_called is False
    assert "Copilot Studio capacity" in result.output


def test_command_knowledge_add_blocked_when_not_entitled(monkeypatch):
    """Case 1: `agent knowledge add` exits non-zero and never associates."""
    client, _ = _wire_command_test(
        monkeypatch, allocations=ALLOC_404, billing_policies=BILLING_EMPTY
    )
    result = runner.invoke(
        agent.app,
        ["knowledge", "add", "agent-1", "--component", "comp-1"],
    )
    assert result.exit_code != 0
    assert client.associate_called is False
    assert "Copilot Studio capacity" in result.output


def test_command_azure_search_add_blocked_when_not_entitled(monkeypatch):
    """Case 1: azure-ai-search add exits non-zero and never calls the mutation."""
    client, _ = _wire_command_test(
        monkeypatch, allocations=ALLOC_ZERO, billing_policies=BILLING_EMPTY
    )
    result = runner.invoke(
        agent.app,
        ["knowledge", "azure-ai-search", "add", "agent-1",
         "--name", "Docs", "--endpoint", "https://s.search.windows.net",
         "--index", "idx", "--api-key", "k"],
    )
    assert result.exit_code != 0
    assert client.azure_search_called is False


def test_command_knowledge_upload_blocked_when_not_entitled(monkeypatch, tmp_path):
    """Case 1: `agent knowledge upload` exits non-zero and performs NO mutation
    (no create, no delete, no upload) when the environment is not entitled.

    A real file is supplied so the os.path.exists guard passes and execution
    reaches the capacity gate; otherwise the command would exit on the missing
    file before the gate (a false pass).
    """
    upload_file = tmp_path / "guide.docx"
    upload_file.write_bytes(b"fake docx bytes")

    client, _ = _wire_command_test(
        monkeypatch, allocations=ALLOC_404, billing_policies=BILLING_EMPTY
    )
    result = runner.invoke(
        agent.app,
        ["knowledge", "upload", "agent-1", "--file", str(upload_file),
         "--name", "Style Guide"],
    )
    assert result.exit_code != 0
    assert client.create_file_component_called is False
    assert client.delete_called is False
    assert client.upload_single_called is False
    assert client.upload_chunked_called is False
    assert "Copilot Studio capacity" in result.output


def test_command_knowledge_upload_force_delete_blocked_when_not_entitled(
    monkeypatch, tmp_path
):
    """The --force delete of an existing source must NOT run when not entitled.

    An existing same-named source is present, so without the gate `--force`
    would call client.delete() before failing. The gate must prevent it.
    """
    upload_file = tmp_path / "manual.pdf"
    upload_file.write_bytes(b"fake pdf bytes")

    client, _ = _wire_command_test(
        monkeypatch, allocations=ALLOC_404, billing_policies=BILLING_EMPTY
    )
    # An existing source with the same name would be force-deleted if the gate
    # did not run first.
    monkeypatch.setattr(
        client,
        "list_knowledge_sources",
        lambda agent_id, source_type=None: [
            {"name": "Style Guide", "botcomponentid": "existing-1"}
        ],
    )
    result = runner.invoke(
        agent.app,
        ["knowledge", "upload", "agent-1", "--file", str(upload_file),
         "--name", "Style Guide", "--force"],
    )
    assert result.exit_code != 0
    assert client.delete_called is False
    assert client.create_file_component_called is False
    assert "Copilot Studio capacity" in result.output


def test_command_knowledge_upload_proceeds_when_entitled(monkeypatch, tmp_path):
    """Case 3 (knowledge upload): entitled via P1 -> reaches the create mutation."""
    upload_file = tmp_path / "guide.docx"
    upload_file.write_bytes(b"fake docx bytes")

    client, _ = _wire_command_test(monkeypatch, allocations=ALLOC_ENTITLED)
    result = runner.invoke(
        agent.app,
        ["knowledge", "upload", "agent-1", "--file", str(upload_file),
         "--name", "Style Guide"],
    )
    assert result.exit_code == 0, result.output
    assert client.create_file_component_called is True


def test_command_tool_add_proceeds_when_entitled(monkeypatch):
    """Case 3: entitled via P1 -> `agent tool add` reaches add_tool."""
    client, _ = _wire_command_test(monkeypatch, allocations=ALLOC_ENTITLED)
    result = runner.invoke(
        agent.app,
        ["tool", "add", "--agentId", "agent-1", "--toolType", "http",
         "--id", "tool-1"],
    )
    assert result.exit_code == 0, result.output
    assert client.add_tool_called is True


def test_command_knowledge_add_proceeds_when_entitled_p2(monkeypatch):
    """Case 4: entitled via P2 -> `agent knowledge add` reaches the mutation."""
    client, _ = _wire_command_test(
        monkeypatch,
        allocations=ALLOC_404,
        billing_policies=(200, {"value": [
            {"billingPolicyId": "pol-1", "status": "Enabled"}
        ]}),
        policy_environments={"pol-1": (200, {"value": [ENV_ID]})},
    )
    result = runner.invoke(
        agent.app,
        ["knowledge", "add", "agent-1", "--component", "comp-1"],
    )
    assert result.exit_code == 0, result.output
    assert client.associate_called is True


def test_command_tool_add_undeterminable_raises_nonzero_no_mutation(monkeypatch):
    """Case 5 (command): 403 allocations -> non-zero exit, add_tool not called."""
    client, _ = _wire_command_test(monkeypatch, allocations=(403, {"error": "forbidden"}))
    result = runner.invoke(
        agent.app,
        ["tool", "add", "--agentId", "agent-1", "--toolType", "http",
         "--id", "tool-1"],
    )
    assert result.exit_code != 0
    assert client.add_tool_called is False


def test_create_and_update_never_touch_licensing(monkeypatch):
    """Case 6: agent create/update never hit the licensing endpoints and never
    invoke the capacity functions."""
    client = _RecordingClient()
    monkeypatch.setattr(agent, "get_client", lambda: client)

    # If any licensing endpoint or capacity function is reached, fail loudly.
    def _boom_get(self, url, headers=None, timeout=None):
        raise AssertionError(f"licensing endpoint must not be called: {url}")

    monkeypatch.setattr(httpx.Client, "get", _boom_get, raising=True)

    def _boom_resolve():
        raise AssertionError("resolve_environment_id must not be called for create/update")

    def _boom_ensure(*args, **kwargs):
        raise AssertionError("ensure_tools_and_knowledge_entitled must not be called")

    monkeypatch.setattr(capacity, "resolve_environment_id", _boom_resolve)
    monkeypatch.setattr(
        capacity, "ensure_tools_and_knowledge_entitled", _boom_ensure
    )

    create_result = runner.invoke(
        agent.app, ["create", "--name", "New Agent"]
    )
    assert create_result.exit_code == 0, create_result.output
    assert client.create_bot_called is True

    update_result = runner.invoke(
        agent.app, ["update", "agent-1", "--name", "Renamed"]
    )
    assert update_result.exit_code == 0, update_result.output
    assert client.update_bot_called is True
