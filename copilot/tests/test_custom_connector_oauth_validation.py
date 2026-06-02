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
