import subprocess

import pytest

import cli_tools_shared.config as config_module


@pytest.fixture(autouse=True)
def isolated_user_data_and_in_memory_secret_manager(tmp_path, monkeypatch):
    home = tmp_path / "home"
    data_home = tmp_path / "data-home"
    config_home = tmp_path / "config-home"
    cache_home = tmp_path / "cache-home"
    state_home = tmp_path / "state-home"
    for path in (home, data_home, config_home, cache_home, state_home):
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.delenv("CLI_TOOL_DATA_HOME", raising=False)

    secrets = {}

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        if command == "get":
            if secret_name not in secrets:
                return subprocess.CompletedProcess([], 1, stdout="", stderr="missing")
            return subprocess.CompletedProcess([], 0, stdout=secrets[secret_name], stderr="")
        if command == "set":
            secrets[secret_name] = secret_value or ""
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if command == "has":
            return subprocess.CompletedProcess(
                [],
                0 if secret_name in secrets else 1,
                stdout="",
                stderr="",
            )
        if command == "delete":
            if secret_name in secrets:
                del secrets[secret_name]
                return subprocess.CompletedProcess([], 0, stdout="", stderr="")
            return subprocess.CompletedProcess([], 1, stdout="", stderr="missing")
        raise AssertionError(f"Unsupported secret-manager command in test: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)
    return secrets
