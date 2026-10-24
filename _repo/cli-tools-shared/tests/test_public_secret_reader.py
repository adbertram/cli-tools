import subprocess

import pytest

import cli_tools_shared
import cli_tools_shared.config as config_module
from cli_tools_shared.exceptions import ConfigError


def test_read_cli_tool_secret_uses_central_secret_manager(monkeypatch):
    calls = []

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        calls.append((command, secret_name, secret_value))
        return subprocess.CompletedProcess([], 0, stdout="stored-value\n", stderr="")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    assert config_module.read_cli_tool_secret("example-secret") == "stored-value"
    assert calls == [("get", "example-secret", None)]


def test_read_cli_tool_secret_returns_none_for_missing_secret(monkeypatch):
    def fake_run(command: str, secret_name: str, *, secret_value=None):
        assert command == "get"
        assert secret_name == "missing-secret"
        assert secret_value is None
        return subprocess.CompletedProcess([], 44, stdout="", stderr="not found")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    assert config_module.read_cli_tool_secret("missing-secret") is None


def test_read_cli_tool_secret_raises_for_secret_manager_error(monkeypatch):
    def fake_run(command: str, secret_name: str, *, secret_value=None):
        assert command == "get"
        assert secret_name == "example-secret"
        assert secret_value is None
        return subprocess.CompletedProcess(
            [], 1, stdout="", stderr="Permission denied: /repo/secrets.log"
        )

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    with pytest.raises(ConfigError) as excinfo:
        config_module.read_cli_tool_secret("example-secret")

    message = str(excinfo.value)
    assert "example-secret" in message
    assert "Permission denied" in message
    assert "Missing secret" not in message


def test_package_exports_central_secret_reader_only():
    assert cli_tools_shared.read_cli_tool_secret is config_module.read_cli_tool_secret
    assert "read_cli_tool_secret" in cli_tools_shared.__all__
    assert not hasattr(cli_tools_shared, "get_secret")
