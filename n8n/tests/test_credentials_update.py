"""Credential update input contract; all API traffic uses a fixture client."""

import json

import pytest
from typer.testing import CliRunner

from n8n_cli.commands import credentials
from n8n_cli.n8n_api import N8nApiError


@pytest.fixture
def api(monkeypatch):
    class FixtureApi:
        updated = None

        def get_credential_schema(self, cred_type):
            return {"required": ["value"]}

        def update_credential(self, credential_id, **fields):
            self.updated = (credential_id, fields)
            return {"id": credential_id, "name": fields.get("name", "Existing Name"), "type": "fixtureType"}

    instance = FixtureApi()
    monkeypatch.setattr(credentials, "get_n8n_api_client", lambda: instance)
    return instance


def test_should_update_data_from_stdin_without_echoing_payload(api):
    result = CliRunner().invoke(
        credentials.app,
        ["update", "fixture-cred-id", "--data-stdin", "--name", "Fixture Renamed"],
        input='{"value":"fixture-only-value","nested":{"enabled":true}}\n',
    )
    assert result.exit_code == 0, result.stderr
    assert api.updated == (
        "fixture-cred-id",
        {"data": {"value": "fixture-only-value", "nested": {"enabled": True}}, "name": "Fixture Renamed"},
    )
    assert json.loads(result.stdout)["id"] == "fixture-cred-id"
    assert "fixture-only-value" not in result.output


def test_should_update_data_only_when_name_omitted(api):
    result = CliRunner().invoke(
        credentials.app, ["update", "fixture-cred-id", '{"value":"fixture-only-value"}']
    )
    assert result.exit_code == 0, result.stderr
    assert api.updated == ("fixture-cred-id", {"data": {"value": "fixture-only-value"}})


def test_should_not_validate_update_data_against_schema(api, monkeypatch):
    """Conditional required/prohibited fields are the server's contract, not the CLI's."""
    def fail_schema(cred_type):
        pytest.fail("update must not pre-validate against the credential schema")

    monkeypatch.setattr(api, "get_credential_schema", fail_schema)
    result = CliRunner().invoke(credentials.app, ["update", "fixture-cred-id", "{}"])
    assert result.exit_code == 0, result.stderr
    assert api.updated == ("fixture-cred-id", {"data": {}})


def test_should_surface_server_validation_error_verbatim(api, monkeypatch):
    def reject(credential_id, **fields):
        raise N8nApiError(
            'API request failed: request.body.data is not allowed to have the additional property "bogusField"'
        )

    monkeypatch.setattr(api, "update_credential", reject)
    result = CliRunner().invoke(credentials.app, ["update", "fixture-cred-id", '{"bogusField":"x"}'])
    assert result.exit_code == 1
    assert 'is not allowed to have the additional property "bogusField"' in result.stderr


def test_should_reject_interactive_update_stdin_before_reading(api, monkeypatch):
    class Terminal:
        def isatty(self):
            return True

        def read(self):
            pytest.fail("Interactive input must not be read")

    monkeypatch.setattr(credentials.sys, "stdin", Terminal())
    with pytest.raises(credentials.typer.Exit) as exc:
        credentials.credentials_update("fixture-cred-id", data=None, name=None, data_stdin=True)
    assert exc.value.exit_code == 1
    assert api.updated is None


@pytest.mark.parametrize("args", [[], ["{}", "--data-stdin"]])
def test_should_reject_missing_or_conflicting_update_inputs(api, args):
    result = CliRunner().invoke(credentials.app, ["update", "fixture-cred-id", *args])
    assert result.exit_code == 1
    assert "Provide exactly one of DATA or --data-stdin" in result.stderr
    assert api.updated is None


@pytest.mark.parametrize("payload,message", [
    ("", "Invalid JSON data"),
    ('{"value":"fixture-only-value",}', "Invalid JSON data"),
    ('["fixture-only-value"]', "Credential data must be a JSON object"),
])
def test_should_reject_invalid_update_stdin_without_echo(api, payload, message):
    result = CliRunner().invoke(credentials.app, ["update", "fixture-cred-id", "--data-stdin"], input=payload)
    assert result.exit_code == 1
    assert message in result.stderr
    assert "fixture-only-value" not in result.output
    assert result.stdout == ""
    assert api.updated is None
