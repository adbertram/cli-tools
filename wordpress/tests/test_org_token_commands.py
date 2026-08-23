import json

import pytest
import requests
from typer.testing import CliRunner

from cli_tools_shared.exceptions import ClientError
from wordpress_cli.config import _configs, get_config
from wordpress_cli.main import app
from wordpress_cli.wpcom import _request_wpcom_token


class DummyResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def isolated_profile_env(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _configs.clear()
    yield
    _configs.clear()


def test_save_credential_reports_exact_missing_fields(runner):
    result = runner.invoke(app, ["org", "token", "save-credential", "--client-id", "client-123"])

    assert result.exit_code == 1, result.output
    assert (
        "Missing WordPress.com credentials: WPCOM_CLIENT_SECRET, WPCOM_SITE, "
        "WPCOM_REDIRECT_URI."
    ) in result.stderr
    assert "wordpress org token save-credential --client-id ..." in result.stderr

    config = get_config()
    assert config.wpcom_client_id == "client-123"
    assert config.wpcom_client_secret is None


def test_org_token_requests_and_saves_token_without_printing_raw_token(runner, monkeypatch):
    opened_urls = []

    def fake_open(url):
        opened_urls.append(url)
        return True

    def fake_request(data):
        assert data == {
            "client_id": "client-123",
            "client_secret": "secret-456",
            "grant_type": "authorization_code",
            "code": "auth-code-123",
            "redirect_uri": "https://localhost.example/callback",
        }
        return DummyResponse(
            200,
            {
                "access_token": "raw-token-value",
                "token_type": "bearer",
                "scope": "global",
            },
        )

    monkeypatch.setattr("wordpress_cli.wpcom.webbrowser.open", fake_open)
    monkeypatch.setattr("wordpress_cli.wpcom._request_wpcom_token", fake_request)

    result = runner.invoke(
        app,
        [
            "org",
            "token",
            "--client-id",
            "client-123",
            "--client-secret",
            "secret-456",
            "--site",
            "example.com",
            "--redirect-uri",
            "https://localhost.example/callback",
        ],
        input="https://localhost.example/callback?code=auth-code-123\n",
    )

    assert result.exit_code == 0, result.output
    stdout = json.loads(result.stdout)
    assert stdout == {
        "site": "example.com",
        "token_saved": True,
        "token_type": "bearer",
        "scope": "global",
    }
    assert opened_urls == [
        "https://public-api.wordpress.com/oauth2/authorize?client_id=client-123&redirect_uri=https%3A%2F%2Flocalhost.example%2Fcallback&response_type=code&scope=global"
    ]
    assert "raw-token-value" not in result.stdout
    assert "raw-token-value" not in result.stderr
    assert "WordPress.com access token saved for example.com" in result.stderr

    config = get_config()
    assert config.wpcom_access_token == "raw-token-value"
    assert config.wpcom_token_type == "bearer"
    assert config.wpcom_scope == "global"


def test_wpcom_token_request_retries_transient_connection_error(monkeypatch):
    attempts = []
    sleeps = []

    def fake_request(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise requests.exceptions.ConnectionError("temporary DNS failure")
        return DummyResponse(200, {"access_token": "raw-token-value"})

    monkeypatch.setattr("wordpress_cli.wpcom.requests.request", fake_request)
    monkeypatch.setattr("wordpress_cli.wpcom.time.sleep", sleeps.append)

    response = _request_wpcom_token({"code": "auth-code", "client_secret": "secret-value"})

    assert response.status_code == 200
    assert len(attempts) == 2
    assert sleeps == [1.0]
    assert attempts[0]["method"] == "POST"
    assert attempts[0]["url"] == "https://public-api.wordpress.com/oauth2/token"


def test_wpcom_token_request_reports_exhausted_pre_response_network_failure(monkeypatch):
    attempts = []
    sleeps = []

    def fake_request(**kwargs):
        attempts.append(kwargs)
        raise requests.exceptions.ConnectionError("temporary DNS failure secret-value")

    monkeypatch.setattr("wordpress_cli.wpcom.requests.request", fake_request)
    monkeypatch.setattr("wordpress_cli.wpcom.time.sleep", sleeps.append)

    with pytest.raises(ClientError) as excinfo:
        _request_wpcom_token({"code": "auth-code", "client_secret": "secret-value"})

    message = str(excinfo.value)
    assert "failed before receiving a response after 3 attempts" in message
    assert "secret-value" not in message
    assert len(attempts) == 3
    assert sleeps == [1.0, 2.0]


def test_org_token_status_reports_upgrade_readiness_without_secrets(runner):
    config = get_config()
    config.save_wpcom_credentials(
        client_id="client-123",
        client_secret="secret-456",
        site="example.com",
        redirect_uri="https://localhost.example/callback",
    )

    result = runner.invoke(app, ["org", "token", "status"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "site": "example.com",
        "credentials_saved": True,
        "token_saved": False,
        "ready": False,
        "missing_fields": [],
        "setup_command": "wordpress org token save-credential --client-id ... --client-secret ... --site ... --redirect-uri ...",
        "token_command": "wordpress org token",
    }
    assert "secret-456" not in result.stdout


def test_org_token_status_reports_missing_fields(runner):
    config = get_config()
    config.save_wpcom_credentials(site="example.com")

    result = runner.invoke(app, ["org", "token", "status"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["credentials_saved"] is False
    assert payload["token_saved"] is False
    assert payload["ready"] is False
    assert payload["missing_fields"] == [
        "WPCOM_CLIENT_ID",
        "WPCOM_CLIENT_SECRET",
        "WPCOM_REDIRECT_URI",
    ]
