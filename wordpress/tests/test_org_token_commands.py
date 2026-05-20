import json

import pytest
from typer.testing import CliRunner

from wordpress_cli.config import _configs, get_config
from wordpress_cli.main import app


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
        "https://public-api.wordpress.com/oauth2/authorize?client_id=client-123&redirect_uri=https%3A%2F%2Flocalhost.example%2Fcallback&response_type=code&blog=example.com"
    ]
    assert "raw-token-value" not in result.stdout
    assert "raw-token-value" not in result.stderr
    assert "WordPress.com access token saved for example.com" in result.stderr

    config = get_config()
    assert config.wpcom_access_token == "raw-token-value"
    assert config.wpcom_token_type == "bearer"
    assert config.wpcom_scope == "global"
