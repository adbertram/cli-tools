import json

import pytest
from typer.testing import CliRunner

from copilot_cli.client import (
    ClientError,
    DataverseClient,
    VALID_OAUTH_IDENTITY_PROVIDERS,
    _validate_oauth_identity_provider,
)
from copilot_cli.commands import connections as connection_commands
from copilot_cli.commands import custom_connector


def make_openapi_spec(
    *,
    flow: str = "accessCode",
    authorization_url: str | None = "https://example.com/authorize",
    token_url: str | None = "https://example.com/token",
    refresh_url: str | None = "https://example.com/token",
    use_x_ms_refresh_url: bool = False,
) -> dict:
    oauth_definition = {
        "type": "oauth2",
        "flow": flow,
        "scopes": {
            "read": "Read access",
        },
    }
    if authorization_url is not None:
        oauth_definition["authorizationUrl"] = authorization_url
    if token_url is not None:
        oauth_definition["tokenUrl"] = token_url
    if refresh_url is not None:
        refresh_key = "x-ms-refresh-url" if use_x_ms_refresh_url else "refreshUrl"
        oauth_definition[refresh_key] = refresh_url

    return {
        "swagger": "2.0",
        "info": {
            "title": "Test API",
            "version": "1.0.0",
        },
        "host": "api.example.com",
        "basePath": "/v1",
        "schemes": ["https"],
        "securityDefinitions": {
            "oauth2": oauth_definition,
        },
        "paths": {
            "/ping": {
                "get": {
                    "operationId": "Ping",
                    "responses": {
                        "200": {
                            "description": "ok",
                        }
                    },
                }
            }
        },
    }


def test_validate_openapi_definition_requires_refresh_url_for_access_code():
    spec = make_openapi_spec(refresh_url=None)

    is_valid, error = custom_connector.validate_openapi_definition(spec)

    assert is_valid is False
    assert "refreshUrl (or x-ms-refresh-url)" in error


def test_validate_openapi_definition_accepts_x_ms_refresh_url():
    spec = make_openapi_spec(refresh_url="https://example.com/token", use_x_ms_refresh_url=True)

    is_valid, error = custom_connector.validate_openapi_definition(spec)

    assert is_valid is True
    assert error == ""


def test_validate_openapi_definition_does_not_require_refresh_url_for_application_flow():
    spec = make_openapi_spec(
        flow="application",
        authorization_url=None,
        refresh_url=None,
    )

    is_valid, error = custom_connector.validate_openapi_definition(spec)

    assert is_valid is True
    assert error == ""


def test_generate_api_properties_uses_explicit_refresh_url():
    client = DataverseClient.__new__(DataverseClient)
    spec = make_openapi_spec(refresh_url="https://example.com/refresh")

    properties = DataverseClient._generate_api_properties(
        client,
        spec,
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
    )

    oauth_settings = properties["properties"]["connectionParameters"]["token"]["oAuthSettings"]
    assert oauth_settings["customParameters"]["refreshUrl"]["value"] == "https://example.com/refresh"


def test_custom_connector_create_fails_without_oauth_client_id(tmp_path):
    swagger_file = tmp_path / "oauth.json"
    swagger_file.write_text(json.dumps(make_openapi_spec()))
    runner = CliRunner()

    result = runner.invoke(
        custom_connector.app,
        [
            "create",
            "--name",
            "My API",
            "--swagger-file",
            str(swagger_file),
            "--oauth-client-secret",
            "secret",
        ],
    )

    assert result.exit_code == 1
    assert "You must provide --oauth-client-id and --oauth-client-secret." in result.output


def test_custom_connector_create_fails_without_oauth_client_secret(tmp_path):
    swagger_file = tmp_path / "oauth.json"
    swagger_file.write_text(json.dumps(make_openapi_spec()))
    runner = CliRunner()

    result = runner.invoke(
        custom_connector.app,
        [
            "create",
            "--name",
            "My API",
            "--swagger-file",
            str(swagger_file),
            "--oauth-client-id",
            "client-id",
        ],
    )

    assert result.exit_code == 1
    assert "You must provide --oauth-client-id and --oauth-client-secret." in result.output


def test_generate_api_properties_defaults_identity_provider_to_oauth2():
    client = DataverseClient.__new__(DataverseClient)
    spec = make_openapi_spec()

    properties = DataverseClient._generate_api_properties(
        client,
        spec,
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
    )

    oauth_settings = properties["properties"]["connectionParameters"]["token"]["oAuthSettings"]
    assert oauth_settings["identityProvider"] == "oauth2"


def test_generate_api_properties_uses_explicit_identity_provider():
    client = DataverseClient.__new__(DataverseClient)
    spec = make_openapi_spec(
        authorization_url="https://accounts.google.com/o/oauth2/auth",
        token_url="https://oauth2.googleapis.com/token",
        refresh_url="https://oauth2.googleapis.com/token",
    )

    properties = DataverseClient._generate_api_properties(
        client,
        spec,
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
        oauth_identity_provider="google",
    )

    oauth_settings = properties["properties"]["connectionParameters"]["token"]["oAuthSettings"]
    assert oauth_settings["identityProvider"] == "google"


def test_generate_api_properties_does_not_auto_add_offline_access_for_azure_ad():
    """The Azure AD URL-sniff hack has been removed. Swagger authors must
    declare offline_access explicitly if they need it."""
    client = DataverseClient.__new__(DataverseClient)
    spec = make_openapi_spec(
        authorization_url="https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token",
        refresh_url="https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token",
    )

    properties = DataverseClient._generate_api_properties(
        client,
        spec,
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
        oauth_identity_provider="aad",
    )

    oauth_settings = properties["properties"]["connectionParameters"]["token"]["oAuthSettings"]
    assert oauth_settings["scopes"] == ["read"]
    assert "offline_access" not in oauth_settings["scopes"]


def test_validate_oauth_identity_provider_rejects_invalid_value():
    with pytest.raises(ClientError) as exc_info:
        _validate_oauth_identity_provider("linkedin")

    message = str(exc_info.value)
    assert "linkedin" in message
    for valid in sorted(VALID_OAUTH_IDENTITY_PROVIDERS):
        assert valid in message


def test_validate_oauth_identity_provider_accepts_none_and_valid_values():
    _validate_oauth_identity_provider(None)
    for valid in VALID_OAUTH_IDENTITY_PROVIDERS:
        _validate_oauth_identity_provider(valid)


def test_custom_connector_create_command_accepts_identity_provider_flag(tmp_path, monkeypatch):
    """CLI smoke test: --oauth-identity-provider is accepted and threaded through."""
    swagger_file = tmp_path / "oauth.json"
    swagger_file.write_text(json.dumps(make_openapi_spec()))

    captured = {}

    class FakeClient:
        def create_custom_connector(self, **kwargs):
            captured.update(kwargs)
            return {
                "connector_id": "shared_test-123",
                "environment_id": "env-123",
            }

        def register_connector_in_dataverse(self, **_kwargs):
            return "connector-row-123"

    monkeypatch.setattr(custom_connector, "get_client", lambda: FakeClient())

    runner = CliRunner()
    result = runner.invoke(
        custom_connector.app,
        [
            "create",
            "--name", "My API",
            "--swagger-file", str(swagger_file),
            "--oauth-client-id", "client-id",
            "--oauth-client-secret", "secret",
            "--oauth-identity-provider", "google",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured.get("oauth_identity_provider") == "google"


def test_create_custom_connector_rejects_invalid_identity_provider():
    client = DataverseClient.__new__(DataverseClient)
    with pytest.raises(ClientError) as exc_info:
        client.create_custom_connector(
            name="My API",
            openapi_definition=make_openapi_spec(),
            oauth_client_id="client-id",
            oauth_client_secret="secret",
            oauth_identity_provider="bogus",
        )
    assert "bogus" in str(exc_info.value)


def test_get_oauth_configuration_issues_reports_missing_refresh_url():
    connector = {
        "properties": {
            "connectionParameters": {
                "token": {
                    "type": "oauthSetting",
                    "oAuthSettings": {
                        "clientId": "client-id",
                        "customParameters": {
                            "authorizationUrl": {"value": "https://example.com/authorize"},
                            "tokenUrl": {"value": "https://example.com/token"},
                        },
                    },
                }
            },
            "swagger": make_openapi_spec(refresh_url=None),
        }
    }

    issues = connection_commands._get_oauth_configuration_issues(connector)

    assert issues == ["refresh URL"]


# ---------------------------------------------------------------------------
# Bug 1: OAuth detection must read connectionParameters from the Power Apps
# apihub representation, not the Dataverse connector entity (which never
# carries connectionParameters / connectionParameterSets).
# ---------------------------------------------------------------------------


def _dataverse_connector_without_auth() -> dict:
    """A connector record as returned by _get_connector_from_dataverse.

    The Dataverse entity carries swagger but never connectionParameters.
    """
    return {
        "name": "shared_test-connector",
        "properties": {
            "displayName": "Test Connector",
            "description": "",
            "publisher": "",
            "tier": "Standard",
            "environment": True,
            "swagger": make_openapi_spec(),
        },
        "_dataverse": {"connectorid": "dv-row-123"},
        "_source": "dataverse",
    }


def _apihub_connector_with_oauth() -> dict:
    """A connector record as returned by _get_connector_from_powerapps.

    The apihub representation carries the OAuth connectionParameters block.
    """
    return {
        "name": "shared_test-connector",
        "properties": {
            "displayName": "Test Connector",
            "connectionParameters": {
                "token": {
                    "type": "oauthSetting",
                    "oAuthSettings": {
                        "identityProvider": "aad",
                        "clientId": "12d53a00-9654-4398-9855-a8517fb732c4",
                        "scopes": ["mcp.tools", "offline_access"],
                        "customParameters": {
                            "authorizationUrl": {"value": "https://example.com/authorize"},
                            "tokenUrl": {"value": "https://example.com/token"},
                            "refreshUrl": {"value": "https://example.com/token"},
                        },
                    },
                }
            },
        },
        "_source": "powerapps",
    }


def test_merge_apihub_auth_copies_connection_parameters_into_dataverse_record(monkeypatch):
    client = DataverseClient.__new__(DataverseClient)
    connector = _dataverse_connector_without_auth()

    monkeypatch.setattr(
        client,
        "_get_connector_from_powerapps",
        lambda connector_id, environment_id: _apihub_connector_with_oauth(),
    )

    client._merge_apihub_auth_into_connector(connector, "shared_test-connector", "env-123")

    token_def = connector["properties"]["connectionParameters"]["token"]
    assert token_def["type"] == "oauthSetting"
    assert token_def["oAuthSettings"]["clientId"] == "12d53a00-9654-4398-9855-a8517fb732c4"


def test_merge_apihub_auth_leaves_record_untouched_when_apihub_unavailable(monkeypatch):
    client = DataverseClient.__new__(DataverseClient)
    connector = _dataverse_connector_without_auth()

    def _raise(connector_id, environment_id):
        raise ClientError("apihub unavailable")

    monkeypatch.setattr(client, "_get_connector_from_powerapps", _raise)

    client._merge_apihub_auth_into_connector(connector, "shared_test-connector", "env-123")

    assert "connectionParameters" not in connector["properties"]


def test_merge_apihub_auth_does_not_refetch_when_already_present(monkeypatch):
    client = DataverseClient.__new__(DataverseClient)
    connector = _apihub_connector_with_oauth()  # already has connectionParameters
    calls = {"count": 0}

    def _count(connector_id, environment_id):
        calls["count"] += 1
        return _apihub_connector_with_oauth()

    monkeypatch.setattr(client, "_get_connector_from_powerapps", _count)

    client._merge_apihub_auth_into_connector(connector, "shared_test-connector", "env-123")

    assert calls["count"] == 0


def test_get_connector_merges_apihub_oauth_so_detection_returns_true(monkeypatch):
    """End-to-end of Bug 1: get_connector returns a Dataverse record whose
    OAuth connectionParameters were merged from the apihub, so OAuth detection
    (the single-auth token check used by `connections auth`) returns true."""
    client = DataverseClient.__new__(DataverseClient)

    monkeypatch.setattr(
        client,
        "_get_connector_from_dataverse",
        lambda connector_id: _dataverse_connector_without_auth(),
    )
    monkeypatch.setattr(
        client,
        "_get_connector_from_powerapps",
        lambda connector_id, environment_id: _apihub_connector_with_oauth(),
    )

    connector = client.get_connector("shared_test-connector", environment_id="env-123")

    # The single-auth OAuth detection used by `connections auth` (connections.py)
    conn_params = connector.get("properties", {}).get("connectionParameters", {})
    token_def = conn_params.get("token") or conn_params.get("Token", {})
    is_oauth = isinstance(token_def, dict) and token_def.get("type") == "oauthSetting"
    assert is_oauth is True

    # And the configuration-issue detector finds a fully configured connector.
    assert connection_commands._get_oauth_configuration_issues(connector) == []


# ---------------------------------------------------------------------------
# Bug 2: an OAuth-credential-only update must send a FULL payload (the apihub
# rejects a connectionParameters-only PATCH with HTTP 500), and must carry
# forward existing custom-code config when present (and omit it when absent)
# without ever uploading a new script.
# ---------------------------------------------------------------------------


class _FakePatchResponse:
    status_code = 204

    def raise_for_status(self):
        return None

    def json(self):
        return {}


class _FakeGetResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeHttpClient:
    """Captures the PATCH payload and returns a canned existing connector."""

    def __init__(self, existing_connector: dict):
        self._existing_connector = existing_connector
        self.patch_payload = None

    def get(self, url, headers=None, params=None, timeout=None):
        return _FakeGetResponse(self._existing_connector)

    def patch(self, url, headers=None, params=None, json=None, timeout=None):
        self.patch_payload = json
        return _FakePatchResponse()


def _existing_connector_for_update(*, with_script: bool) -> dict:
    props = {
        "displayName": "Test Connector",
        "iconBrandColor": "#007ee5",
        "swagger": make_openapi_spec(),
        "backendService": {"serviceUrl": "https://api.example.com/v1"},
        "connectionParameters": {
            "token": {
                "type": "oauthSetting",
                "oAuthSettings": {
                    "identityProvider": "aad",
                    "clientId": "old-client-id",
                    "scopes": ["read"],
                    "customParameters": {
                        "tokenUrl": {"value": "https://example.com/token"},
                    },
                },
            }
        },
    }
    if with_script:
        props["scriptDefinitionUrl"] = "https://blob.example.com/script.csx"
        props["scriptOperations"] = ["Ping"]
    return {"name": "shared_test-connector", "properties": props}


def _run_credential_only_update(monkeypatch, *, with_script: bool):
    client = DataverseClient.__new__(DataverseClient)
    fake_http = _FakeHttpClient(_existing_connector_for_update(with_script=with_script))
    client._http_client = fake_http

    monkeypatch.setattr(
        "copilot_cli.client.get_access_token",
        lambda resource: "fake-token",
    )

    result = client.update_custom_connector(
        connector_id="shared_test-connector",
        oauth_client_id="new-client-id",
        oauth_client_secret="new-secret",
        environment_id="env-123",
    )
    return fake_http.patch_payload, result


def test_credential_only_update_sends_full_payload(monkeypatch):
    payload, result = _run_credential_only_update(monkeypatch, with_script=False)

    assert payload is not None, "PATCH was never issued"
    props = payload["properties"]

    # The apihub rejects connectionParameters-only payloads with HTTP 500, so the
    # payload must include the full property set.
    assert "OpenApiDefinition" in props
    assert "backendService" in props
    assert "connectionParameters" in props
    assert props["backendService"]["serviceUrl"] == "https://api.example.com/v1"

    # NOT connectionParameters alone.
    assert set(props.keys()) != {"connectionParameters"}

    # The credential update was applied onto the OAuth settings.
    oauth_settings = props["connectionParameters"]["token"]["oAuthSettings"]
    assert oauth_settings["clientId"] == "new-client-id"
    assert oauth_settings["clientSecret"] == "new-secret"

    assert result["connector_id"] == "shared_test-connector"


def test_credential_only_update_carries_forward_existing_custom_code(monkeypatch):
    payload, _ = _run_credential_only_update(monkeypatch, with_script=True)

    props = payload["properties"]
    # Existing custom code must be re-sent (the apihub PATCH drops scriptOperations
    # if omitted), but no new script is uploaded in this path.
    assert props["scriptDefinitionUrl"] == "https://blob.example.com/script.csx"
    assert props["scriptOperations"] == ["Ping"]


def test_credential_only_update_omits_custom_code_when_absent(monkeypatch):
    payload, _ = _run_credential_only_update(monkeypatch, with_script=False)

    props = payload["properties"]
    # The connector has no custom code, so the payload must not invent any.
    assert "scriptDefinitionUrl" not in props
    assert "scriptOperations" not in props
