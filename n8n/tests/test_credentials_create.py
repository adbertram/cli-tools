"""Credential input contracts; all API traffic uses a fixture client."""

import json
from unittest.mock import Mock

import pytest
import requests
from typer.testing import CliRunner

from n8n_cli.commands import credentials
from n8n_cli.n8n_api import N8nApiClient, N8nApiError


@pytest.fixture
def api(monkeypatch):
    class FixtureApi:
        created = None

        def get_credential_schema(self, cred_type):
            return {"required": ["value"]}

        def create_credential(self, name, cred_type, data):
            self.created = (name, cred_type, data)
            return {"id": "fixture-id", "name": name, "type": cred_type}

    instance = FixtureApi()
    monkeypatch.setattr(credentials, "get_n8n_api_client", lambda: instance)
    return instance


def test_should_create_from_stdin_without_echoing_payload(api):
    result = CliRunner().invoke(
        credentials.app, ["create", "fixtureType", "--data-stdin", "--name", "Fixture"],
        input='{"value":"fixture-only-value","nested":{"enabled":true}}\n',
    )
    assert result.exit_code == 0, result.stderr
    assert api.created == ("Fixture", "fixtureType", {"value": "fixture-only-value", "nested": {"enabled": True}})
    assert json.loads(result.stdout)["id"] == "fixture-id"
    assert "fixture-only-value" not in result.output


def test_should_preserve_positional_json(api):
    result = CliRunner().invoke(credentials.app, ["create", "fixtureType", '{"value":"fixture-only-value"}'])
    assert result.exit_code == 0, result.stderr
    assert api.created == ("Fixture Type", "fixtureType", {"value": "fixture-only-value"})


def test_should_reject_interactive_stdin_before_reading(api, monkeypatch):
    class Terminal:
        def isatty(self):
            return True

        def read(self):
            pytest.fail("Interactive input must not be read")

    monkeypatch.setattr(credentials.sys, "stdin", Terminal())
    with pytest.raises(credentials.typer.Exit) as exc:
        credentials.credentials_create("fixtureType", data=None, name=None, data_stdin=True)
    assert exc.value.exit_code == 1
    assert api.created is None


def test_should_not_replay_credential_post_after_lost_response(monkeypatch):
    client = object.__new__(N8nApiClient)
    client.base_url = "https://fixture.invalid/api/v1"
    client.session = Mock()
    client.session.request.side_effect = requests.Timeout("fixture-only lost response")
    monkeypatch.setattr("n8n_cli.n8n_api.time.sleep", lambda _: None)

    with pytest.raises(N8nApiError, match="fixture-only lost response"):
        client.create_credential("Fixture", "fixtureType", {"value": "fixture-only"})

    client.session.request.assert_called_once_with(
        "POST", "https://fixture.invalid/api/v1/credentials",
        json={"name": "Fixture", "type": "fixtureType", "data": {"value": "fixture-only"}},
    )


@pytest.mark.parametrize("args,message", [
    ([], "Provide exactly one of DATA or --data-stdin"),
    (["{}", "--data-stdin"], "Provide exactly one of DATA or --data-stdin"),
])
def test_should_reject_missing_or_conflicting_inputs(api, args, message):
    result = CliRunner().invoke(credentials.app, ["create", "fixtureType", *args])
    assert result.exit_code == 1
    assert message in result.stderr
    assert api.created is None


@pytest.mark.parametrize("payload,message", [
    ("", "Invalid JSON data"),
    ('{"value":"fixture-only-value",}', "Invalid JSON data"),
    ('["fixture-only-value"]', "Credential data must be a JSON object"),
    ('{}', "Required fields missing or empty: value"),
])
def test_should_reject_invalid_stdin_without_echo(api, payload, message):
    result = CliRunner().invoke(credentials.app, ["create", "fixtureType", "--data-stdin"], input=payload)
    assert result.exit_code == 1
    assert message in result.stderr
    assert "fixture-only-value" not in result.output
    assert result.stdout == ""
    assert api.created is None
