import subprocess
from pathlib import Path

import cli_tools_shared.config as config_module
from snagit_cli.config import Config


def test_save_api_key_routes_through_central_secret_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_TOOL_DIR_SNAGIT_CLI", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    calls = []

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        calls.append((command, secret_name, secret_value))
        if command == "set":
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if command == "get":
            return subprocess.CompletedProcess([], 1, stdout="", stderr="missing")
        raise AssertionError(f"Unexpected secret-manager command: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = Config()
    config.save_api_key("snagit-secret")

    assert calls == [("set", "snagit-api-key", "snagit-secret")]
    assert "SNAGIT_API_KEY='secret://snagit-api-key'" in config.env_file_path.read_text()
    assert config.api_key == "snagit-secret"


def test_save_tokens_routes_sensitive_tokens_through_central_secret_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("CLI_TOOL_DIR_SNAGIT_CLI", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    calls = []

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        calls.append((command, secret_name, secret_value))
        if command == "set":
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if command == "get":
            return subprocess.CompletedProcess([], 1, stdout="", stderr="missing")
        raise AssertionError(f"Unexpected secret-manager command: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = Config()
    config.save_tokens("access-secret", "refresh-secret", "999")

    assert calls == [
        ("set", "snagit-access-token", "access-secret"),
        ("set", "snagit-refresh-token", "refresh-secret"),
    ]
    content = config.env_file_path.read_text()
    assert "SNAGIT_ACCESS_TOKEN='secret://snagit-access-token'" in content
    assert "SNAGIT_REFRESH_TOKEN='secret://snagit-refresh-token'" in content
    assert "SNAGIT_TOKEN_EXPIRES_AT='999'" in content
    assert config.access_token == "access-secret"
    assert config.refresh_token == "refresh-secret"
