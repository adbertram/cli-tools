"""A server that never answers must not be reported as a credential rejection.

Regression for the reported `n8n data-tables rows <table> --limit 1000` failure:
the session login POST hit its 30s read timeout while the n8n server was
heap-exhausted and restarting, and the CLI surfaced that as
`Login failed: ...`, which reads as "the server rejected my credentials". The
server had not answered at all, so no credential verdict existed.

The transport and credential verdicts must stay separate, and the command must
still fail closed: non-zero exit and nothing on stdout, so a monitor that checks
the exit status cannot continue with stale or missing data.
"""
import json
from unittest.mock import Mock

import pytest
import requests
from typer.testing import CliRunner

import n8n_cli.commands.data_tables as data_tables_module
import n8n_cli.n8n_api as n8n_api_module
from n8n_cli.n8n_api import N8nApiClient


TABLE_ID = "5fu3SRNtZ0wvlOeI"
ROWS_ARGS = ["rows", TABLE_ID, "--limit", "1000"]

READ_TIMEOUT_MESSAGE = (
    "HTTPConnectionPool(host='fixture.invalid', port=5678): "
    "Read timed out. (read timeout=30)"
)


@pytest.fixture
def client(monkeypatch):
    """A real client pointed at a fixture host, wired into the rows command."""
    monkeypatch.setenv("EMAIL", "fixture@example.invalid")
    monkeypatch.setenv("PASSWORD", "fixture-only")
    value = N8nApiClient(
        base_url="http://fixture.invalid:5678/api/v1", api_key="fixture-only"
    )
    monkeypatch.setattr(data_tables_module, "get_n8n_api_client", lambda: value)
    return value


def _invoke(args=None):
    return CliRunner().invoke(data_tables_module.app, args or ROWS_ARGS)


def _raising(error):
    def _fail(*args, **kwargs):
        raise error
    return _fail


def _http_error_response(status, text=""):
    response = Mock(status_code=status, text=text)
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        response=response
    )
    return response


def test_login_read_timeout_names_the_timeout_not_a_credential_rejection(
    client, monkeypatch
):
    monkeypatch.setattr(
        n8n_api_module.requests,
        "post",
        _raising(requests.exceptions.ReadTimeout(READ_TIMEOUT_MESSAGE)),
    )

    result = _invoke()

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Login failed" not in result.stderr
    assert "Timed out after 30s" in result.stderr
    assert "http://fixture.invalid:5678/rest/login" in result.stderr
    assert "No credentials were rejected" in result.stderr
    assert "fixture-only" not in result.output


def test_unreachable_server_is_reported_as_a_connection_failure(client, monkeypatch):
    monkeypatch.setattr(
        n8n_api_module.requests,
        "post",
        _raising(requests.exceptions.ConnectionError("Connection refused")),
    )

    result = _invoke()

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Login failed" not in result.stderr
    assert "Could not reach the n8n server" in result.stderr
    assert "No credentials were rejected" in result.stderr


def test_rejected_credentials_are_still_reported_as_a_login_failure(
    client, monkeypatch
):
    monkeypatch.setattr(
        n8n_api_module.requests,
        "post",
        lambda *args, **kwargs: _http_error_response(401, '{"message":"unauthorized"}'),
    )

    result = _invoke()

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Login failed" in result.stderr
    assert "HTTP 401" in result.stderr
    assert "n8n auth login" in result.stderr


def test_login_server_error_is_not_reported_as_a_credential_rejection(
    client, monkeypatch
):
    monkeypatch.setattr(
        n8n_api_module.requests,
        "post",
        lambda *args, **kwargs: _http_error_response(502, "Bad gateway"),
    )

    result = _invoke()

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Login failed" not in result.stderr
    assert "HTTP 502" in result.stderr
    assert "not a credential rejection" in result.stderr


def test_rest_read_timeout_names_the_timeout(client, monkeypatch):
    """A timeout after a successful login is a transport failure too."""
    session = Mock(status_code=200, text="")
    session.cookies.get.return_value = "fixture-cookie"
    monkeypatch.setattr(n8n_api_module.requests, "post", lambda *args, **kwargs: session)
    monkeypatch.setattr(
        n8n_api_module.requests,
        "request",
        _raising(requests.exceptions.ReadTimeout(READ_TIMEOUT_MESSAGE)),
    )

    result = _invoke()

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Login failed" not in result.stderr
    assert "timed out after 30s" in result.stderr
    assert "/rest/projects" in result.stderr


def test_successful_read_still_prints_rows_and_exits_zero(client, monkeypatch):
    """Guard the fixture chain: the failing tests above fail on the real path."""
    session = Mock(status_code=200, text="")
    session.cookies.get.return_value = "fixture-cookie"
    monkeypatch.setattr(n8n_api_module.requests, "post", lambda *args, **kwargs: session)

    responses = {
        "/rest/projects": {"data": [{"id": "project-1", "name": "Fixture"}]},
        f"/rest/projects/project-1/data-tables/{TABLE_ID}/rows": {
            "data": {"data": [{"id": 1, "status": "ok"}]}
        },
    }

    def _request(method, url, **kwargs):
        for suffix, payload in responses.items():
            if url.endswith(suffix):
                response = Mock(status_code=200, ok=True)
                response.json.return_value = payload
                return response
        raise AssertionError(f"unexpected fixture URL: {url}")

    monkeypatch.setattr(n8n_api_module.requests, "request", _request)

    result = _invoke()

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == [{"id": 1, "status": "ok"}]
