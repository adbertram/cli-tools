import pytest
from google.oauth2.credentials import Credentials
from typer.testing import CliRunner

from google_cli.client import ClientError, GoogleClient, SCOPES
from google_cli.config import reset_config
from google_cli.main import app


class ConfigWithToken:
    def __init__(self, token_path):
        self.token_path = str(token_path)
        self.credentials_path = str(token_path)

    def get_missing_credentials(self):
        return []


def test_client_rejects_stored_token_missing_required_scopes(tmp_path):
    token_path = tmp_path / "token.json"
    creds = Credentials(
        token="access-token",
        refresh_token="refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=SCOPES[:-1],
    )
    token_path.write_text(creds.to_json())

    with pytest.raises(ClientError, match="missing required OAuth scopes"):
        GoogleClient(ConfigWithToken(token_path))


def test_auth_login_force_reuses_saved_oauth_client_credentials(tmp_path, monkeypatch):
    data_home = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    for name in ("CLIENT_ID", "CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    reset_config()

    profile_dir = data_home / "cli-tools" / "google" / "authentication_profiles" / "adbertram"
    profile_dir.mkdir(parents=True)
    (profile_dir / ".env").write_text(
        "ACTIVE=true\n"
        "CLIENT_ID=secret://google-adbertram-client-id\n"
        "CLIENT_SECRET=secret://google-adbertram-client-secret\n"
    )

    def fake_secret_manager(command, secret_name, *, secret_value=None):
        import subprocess

        values = {
            "google-adbertram-client-id": "profile-client",
            "google-adbertram-client-secret": "profile-secret",
        }
        assert secret_name in values
        if command == "get":
            return subprocess.CompletedProcess(
                [], 0, stdout=f"{values[secret_name]}\n", stderr=""
            )
        if command == "has":
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        raise AssertionError(f"unexpected secret-manager command: {command}")

    monkeypatch.setattr("cli_tools_shared.config._run_secret_manager", fake_secret_manager)

    class FakeCredentials:
        def to_json(self):
            return Credentials(
                token="access-token",
                refresh_token="refresh-token",
                token_uri="https://oauth2.googleapis.com/token",
                client_id="profile-client",
                client_secret="profile-secret",
                scopes=SCOPES,
            ).to_json()

    class FakeFlow:
        def run_local_server(self, port=0):
            return FakeCredentials()

    captured = {}

    def fake_from_client_config(client_config, scopes):
        captured["client_config"] = client_config
        captured["scopes"] = scopes
        return FakeFlow()

    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
        fake_from_client_config,
    )

    result = CliRunner().invoke(
        app,
        ["auth", "login", "--force", "--profile", "adbertram"],
        input="",
    )

    assert result.exit_code == 0, result.output
    assert "Enter OAuth Client ID" not in result.output
    assert captured["client_config"]["installed"]["client_id"] == "profile-client"
    assert captured["client_config"]["installed"]["client_secret"] == "profile-secret"
    assert "https://www.googleapis.com/auth/contacts.readonly" in captured["scopes"]
    assert (profile_dir / "token.json").exists()
    assert not (profile_dir / "credentials.json").exists()


def test_auth_login_stores_prompted_oauth_client_credentials_as_secret_refs(
    tmp_path, monkeypatch
):
    data_home = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    for name in ("CLIENT_ID", "CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    reset_config()

    profile_dir = data_home / "cli-tools" / "google" / "authentication_profiles" / "adbertram"
    profile_dir.mkdir(parents=True)
    (profile_dir / ".env").write_text(
        "ACTIVE=true\n"
        "CLIENT_ID=\n"
        "CLIENT_SECRET=\n"
    )

    secret_store = {}

    def fake_secret_manager(command, secret_name, *, secret_value=None):
        import subprocess

        if command == "set":
            secret_store[secret_name] = secret_value
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if command == "get":
            if secret_name in secret_store:
                return subprocess.CompletedProcess(
                    [], 0, stdout=f"{secret_store[secret_name]}\n", stderr=""
                )
            return subprocess.CompletedProcess([], 1, stdout="", stderr="not found")
        if command == "has":
            return subprocess.CompletedProcess(
                [], 0 if secret_name in secret_store else 1, stdout="", stderr=""
            )
        raise AssertionError(f"unexpected secret-manager command: {command}")

    monkeypatch.setattr("cli_tools_shared.config._run_secret_manager", fake_secret_manager)

    class FakeCredentials:
        def to_json(self):
            return Credentials(
                token="access-token",
                refresh_token="refresh-token",
                token_uri="https://oauth2.googleapis.com/token",
                client_id="prompt-client",
                client_secret="prompt-secret",
                scopes=SCOPES,
            ).to_json()

    class FakeFlow:
        def run_local_server(self, port=0):
            return FakeCredentials()

    captured = {}

    def fake_from_client_config(client_config, scopes):
        captured["client_config"] = client_config
        captured["scopes"] = scopes
        return FakeFlow()

    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
        fake_from_client_config,
    )

    result = CliRunner().invoke(
        app,
        ["auth", "login", "--force", "--profile", "adbertram"],
        input="prompt-client\nprompt-secret\n",
    )

    assert result.exit_code == 0, result.output
    assert secret_store == {
        "google-adbertram-client-id": "prompt-client",
        "google-adbertram-client-secret": "prompt-secret",
    }
    content = (profile_dir / ".env").read_text()
    assert "CLIENT_ID='secret://google-adbertram-client-id'" in content
    assert "CLIENT_SECRET='secret://google-adbertram-client-secret'" in content
    assert "prompt-client" not in content
    assert "prompt-secret" not in content
    assert captured["client_config"]["installed"]["client_id"] == "prompt-client"
    assert captured["client_config"]["installed"]["client_secret"] == "prompt-secret"
    assert "https://www.googleapis.com/auth/contacts.readonly" in captured["scopes"]
    assert not (profile_dir / "credentials.json").exists()
