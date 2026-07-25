"""Tests for the configurable connector-definition write timeout.

Custom connector create (POST) and update (PATCH) compile the OpenAPI spec and
any attached .csx policy script server-side, which Power Platform can take well
over a minute to apply. The write keeps applying even after a client read
timeout, so a short timeout misreports a slow-but-successful apply as a failure.
These tests pin the resolution rules and prove both the create POST and the
update PATCH use the resolved timeout (default 300s), not the old 60s value.
"""

import pytest

from copilot_cli.client import (
    CONNECTOR_WRITE_TIMEOUT_ENV,
    DEFAULT_CONNECTOR_WRITE_TIMEOUT,
    ClientError,
    DataverseClient,
    _resolve_connector_write_timeout,
)


# ---------------------------------------------------------------------------
# _resolve_connector_write_timeout: precedence and validation
# ---------------------------------------------------------------------------


def test_resolve_timeout_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv(CONNECTOR_WRITE_TIMEOUT_ENV, raising=False)
    assert _resolve_connector_write_timeout() == DEFAULT_CONNECTOR_WRITE_TIMEOUT


def test_resolve_timeout_uses_env_override(monkeypatch):
    monkeypatch.setenv(CONNECTOR_WRITE_TIMEOUT_ENV, "450")
    assert _resolve_connector_write_timeout() == 450.0


def test_resolve_timeout_blank_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv(CONNECTOR_WRITE_TIMEOUT_ENV, "   ")
    assert _resolve_connector_write_timeout() == DEFAULT_CONNECTOR_WRITE_TIMEOUT


def test_resolve_timeout_explicit_override_wins_over_env(monkeypatch):
    monkeypatch.setenv(CONNECTOR_WRITE_TIMEOUT_ENV, "450")
    assert _resolve_connector_write_timeout(123.0) == 123.0


def test_resolve_timeout_invalid_env_raises(monkeypatch):
    monkeypatch.setenv(CONNECTOR_WRITE_TIMEOUT_ENV, "not-a-number")
    with pytest.raises(ClientError) as exc_info:
        _resolve_connector_write_timeout()
    assert CONNECTOR_WRITE_TIMEOUT_ENV in str(exc_info.value)


def test_resolve_timeout_nonpositive_env_raises(monkeypatch):
    monkeypatch.setenv(CONNECTOR_WRITE_TIMEOUT_ENV, "0")
    with pytest.raises(ClientError):
        _resolve_connector_write_timeout()


def test_resolve_timeout_nonpositive_override_raises():
    with pytest.raises(ClientError):
        _resolve_connector_write_timeout(-5.0)


# ---------------------------------------------------------------------------
# Fake HTTP client that records the timeout used on each verb
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, *, status_code=204, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _RecordingHttpClient:
    """Captures the timeout passed to get/post/patch and returns canned responses."""

    def __init__(self, existing_connector=None):
        self._existing_connector = existing_connector or {}
        self.calls = []  # list of (method, timeout)

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(("get", timeout))
        return _FakeResponse(status_code=200, payload=self._existing_connector)

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("post", timeout))
        return _FakeResponse(status_code=200, payload={"name": "shared_new-connector"})

    def patch(self, url, headers=None, params=None, json=None, timeout=None):
        self.calls.append(("patch", timeout))
        return _FakeResponse(status_code=204, payload={})

    def timeout_for(self, method):
        for recorded_method, timeout in self.calls:
            if recorded_method == method:
                return timeout
        raise AssertionError(f"no {method} call recorded; calls={self.calls}")


# ---------------------------------------------------------------------------
# update_custom_connector: the PATCH must use the resolved write timeout
# ---------------------------------------------------------------------------


def _run_update(monkeypatch, *, timeout=None):
    client = DataverseClient.__new__(DataverseClient)
    http = _RecordingHttpClient(
        {"name": "shared_test-connector", "properties": {"displayName": "Test"}}
    )
    client._http_client = http
    monkeypatch.setattr(
        "copilot_cli.client.get_access_token", lambda resource: "fake-token"
    )
    client.update_custom_connector(
        connector_id="shared_test-connector",
        description="Updated",
        environment_id="env-123",
        timeout=timeout,
    )
    return http


def test_update_patch_uses_default_write_timeout(monkeypatch):
    monkeypatch.delenv(CONNECTOR_WRITE_TIMEOUT_ENV, raising=False)
    http = _run_update(monkeypatch)
    # Regression guard: the PATCH used to hard-code 60s, which timed out on
    # connector-with-script writes even though the server completed them.
    assert http.timeout_for("patch") == DEFAULT_CONNECTOR_WRITE_TIMEOUT
    assert http.timeout_for("patch") != 60.0
    # The preflight GET stays on its own short timeout (fast read, not the write).
    assert http.timeout_for("get") == 30.0


def test_update_patch_honors_env_override(monkeypatch):
    monkeypatch.setenv(CONNECTOR_WRITE_TIMEOUT_ENV, "420")
    http = _run_update(monkeypatch)
    assert http.timeout_for("patch") == 420.0


def test_update_patch_honors_explicit_timeout(monkeypatch):
    monkeypatch.setenv(CONNECTOR_WRITE_TIMEOUT_ENV, "420")
    http = _run_update(monkeypatch, timeout=90.0)
    assert http.timeout_for("patch") == 90.0


# ---------------------------------------------------------------------------
# create_custom_connector: the POST must use the resolved write timeout
# ---------------------------------------------------------------------------


def _run_create(monkeypatch, *, timeout=None):
    client = DataverseClient.__new__(DataverseClient)
    http = _RecordingHttpClient()
    client._http_client = http
    monkeypatch.setattr(
        "copilot_cli.client.get_access_token", lambda resource: "fake-token"
    )
    monkeypatch.setattr(client, "_list_custom_connectors_from_powerapps", lambda env: [])
    monkeypatch.setattr(
        client, "_generate_api_properties", lambda *args, **kwargs: {"properties": {}}
    )
    client.create_custom_connector(
        name="My API",
        openapi_definition={
            "host": "api.example.com",
            "basePath": "/v1",
            "schemes": ["https"],
        },
        environment_id="env-123",
        timeout=timeout,
    )
    return http


def test_create_post_uses_default_write_timeout(monkeypatch):
    monkeypatch.delenv(CONNECTOR_WRITE_TIMEOUT_ENV, raising=False)
    http = _run_create(monkeypatch)
    assert http.timeout_for("post") == DEFAULT_CONNECTOR_WRITE_TIMEOUT


def test_create_post_honors_env_override(monkeypatch):
    monkeypatch.setenv(CONNECTOR_WRITE_TIMEOUT_ENV, "360")
    http = _run_create(monkeypatch)
    assert http.timeout_for("post") == 360.0


def test_create_post_honors_explicit_timeout(monkeypatch):
    monkeypatch.delenv(CONNECTOR_WRITE_TIMEOUT_ENV, raising=False)
    http = _run_create(monkeypatch, timeout=200.0)
    assert http.timeout_for("post") == 200.0
