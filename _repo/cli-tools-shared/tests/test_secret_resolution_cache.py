"""Per-process memo of resolved profile secrets.

One CLI invocation builds its config more than once (the command credential
check, then the API client). The secret manager must run once per secret per
process, a missing secret must fail every time, and any write or delete of a
secret in the same process must drop the memoized value.

The autouse fixture in ``conftest.py`` swaps ``_run_secret_manager`` for an
in-memory store and resets the memo for each test.
"""

from pathlib import Path
import subprocess
import threading

import pytest

import cli_tools_shared.config as config_module
from cli_tools_shared.config import BaseConfig, get_profiles_base_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ConfigError
from cli_tools_shared.profiles import ProfileStore, rename_profile


class ApiKeyConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.API_KEY]


@pytest.fixture
def store(isolated_user_data_and_in_memory_secret_manager, monkeypatch):
    """Return (secrets dict, calls list) with every secret-manager call recorded."""
    secrets = isolated_user_data_and_in_memory_secret_manager
    in_memory_run = config_module._run_secret_manager
    calls: list[tuple[str, str]] = []

    def counting_run(command, secret_name, *, secret_value=None):
        calls.append((command, secret_name))
        return in_memory_run(command, secret_name, secret_value=secret_value)

    monkeypatch.setattr(config_module, "_run_secret_manager", counting_run)
    return secrets, calls


def _profile(tmp_path: Path, body: str) -> Path:
    tool_dir = tmp_path / "exampletool"
    tool_dir.mkdir()
    env = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text(body)
    return tool_dir


def _gets(calls, secret_name):
    return [call for call in calls if call == ("get", secret_name)]


def test_second_config_in_one_process_does_not_rerun_secret_manager(tmp_path, store):
    secrets, calls = store
    secrets["exampletool-api-key"] = "key-1"
    tool_dir = _profile(tmp_path, "ACTIVE=true\nAPI_KEY=secret://exampletool-api-key\n")

    assert ApiKeyConfig(tool_dir=tool_dir).api_key == "key-1"
    assert ApiKeyConfig(tool_dir=tool_dir).api_key == "key-1"

    assert len(_gets(calls, "exampletool-api-key")) == 1


def test_missing_secret_is_not_cached(tmp_path, store):
    secrets, calls = store
    tool_dir = _profile(tmp_path, "ACTIVE=true\nAPI_KEY=secret://exampletool-api-key\n")

    for _ in range(2):
        with pytest.raises(ConfigError, match="Missing secret 'exampletool-api-key'"):
            ApiKeyConfig(tool_dir=tool_dir)
    assert len(_gets(calls, "exampletool-api-key")) == 2

    secrets["exampletool-api-key"] = "key-now-present"
    assert ApiKeyConfig(tool_dir=tool_dir).api_key == "key-now-present"
    assert len(_gets(calls, "exampletool-api-key")) == 3


def test_secret_manager_error_is_not_cached(tmp_path, store, monkeypatch):
    secrets, calls = store
    secrets["exampletool-api-key"] = "key-1"
    tool_dir = _profile(tmp_path, "ACTIVE=true\nAPI_KEY=secret://exampletool-api-key\n")
    working_run = config_module._run_secret_manager

    def failing_run(command, secret_name, *, secret_value=None):
        return subprocess.CompletedProcess([], 1, stdout="", stderr="keychain locked")

    monkeypatch.setattr(config_module, "_run_secret_manager", failing_run)
    with pytest.raises(ConfigError, match="keychain locked"):
        ApiKeyConfig(tool_dir=tool_dir)

    monkeypatch.setattr(config_module, "_run_secret_manager", working_run)
    assert ApiKeyConfig(tool_dir=tool_dir).api_key == "key-1"
    assert len(_gets(calls, "exampletool-api-key")) == 1


def test_set_in_same_process_evicts_cached_value(tmp_path, store):
    secrets, calls = store
    secrets["exampletool-api-key"] = "old-key"
    tool_dir = _profile(tmp_path, "ACTIVE=true\nAPI_KEY=secret://exampletool-api-key\n")

    config = ApiKeyConfig(tool_dir=tool_dir)
    assert config.api_key == "old-key"

    config._set("API_KEY", "rotated-key")

    assert ApiKeyConfig(tool_dir=tool_dir).api_key == "rotated-key"
    assert len(_gets(calls, "exampletool-api-key")) == 2


def test_delete_in_same_process_evicts_cached_value(tmp_path, store):
    secrets, _calls = store
    secrets["exampletool-api-key"] = "key-1"
    tool_dir = _profile(tmp_path, "ACTIVE=true\nAPI_KEY=secret://exampletool-api-key\n")
    env = get_profiles_base_dir(tool_dir.name) / "default" / ".env"

    assert ApiKeyConfig(tool_dir=tool_dir).api_key == "key-1"

    config_module._delete_secret_value("exampletool-api-key", env)

    with pytest.raises(ConfigError, match="Missing secret 'exampletool-api-key'"):
        ApiKeyConfig(tool_dir=tool_dir)


def test_profile_rename_evicts_old_secret_name(tmp_path, store):
    secrets, _calls = store
    tool_dir = tmp_path / "exampletool"
    tool_dir.mkdir()
    old_env = get_profiles_base_dir(tool_dir.name) / "staging" / ".env"
    old_env.parent.mkdir(parents=True)
    old_env.write_text("ACTIVE=true\nAPI_KEY=secret://exampletool-staging-api-key\n")
    secrets["exampletool-staging-api-key"] = "staging-key"

    assert ApiKeyConfig(tool_dir=tool_dir, profile="staging").api_key == "staging-key"

    def builder(field_name, new_env_path):
        config = object.__new__(ApiKeyConfig)
        config._tool_name = tool_dir.name
        return config._secret_name_for_field_in_profile(field_name, new_env_path)

    rename_profile(
        ProfileStore(tool_dir.name, tool_dir=tool_dir),
        "staging",
        "production",
        secret_name_for_field=builder,
    )

    with pytest.raises(ConfigError, match="Missing secret 'exampletool-staging-api-key'"):
        config_module._get_secret_value("exampletool-staging-api-key", old_env)
    assert ApiKeyConfig(tool_dir=tool_dir, profile="production").api_key == "staging-key"


def test_failed_set_keeps_the_memoized_value(tmp_path, store, monkeypatch):
    secrets, calls = store
    secrets["exampletool-api-key"] = "old-key"
    tool_dir = _profile(tmp_path, "ACTIVE=true\nAPI_KEY=secret://exampletool-api-key\n")
    env = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    assert ApiKeyConfig(tool_dir=tool_dir).api_key == "old-key"

    monkeypatch.setattr(
        config_module,
        "_run_secret_manager",
        lambda command, secret_name, *, secret_value=None: subprocess.CompletedProcess([], 1, stdout="", stderr="locked"),
    )
    with pytest.raises(ConfigError, match="Failed to store secret 'exampletool-api-key'"):
        config_module._set_secret_value("exampletool-api-key", "new-key", env)

    # Still served from the memo: the failed write changed nothing.
    assert config_module._get_secret_value("exampletool-api-key", env) == "old-key"


def test_read_in_flight_during_set_cannot_memoize_the_old_value_after_the_write(tmp_path, store, monkeypatch):
    """A read already talking to the secret manager when a rotation starts.

    The read returns the old value; the rotation must not finish (and evict)
    until that read has memoized it, otherwise the old value would be stored
    after the eviction and served for the rest of the process.
    """
    secrets, _calls = store
    secrets["exampletool-api-key"] = "OLD"
    profile_path = tmp_path / "profile" / ".env"
    real_run = config_module._run_secret_manager
    read_started = threading.Event()
    release_read = threading.Event()

    def slow_get(command, secret_name, *, secret_value=None):
        result = real_run(command, secret_name, secret_value=secret_value)
        if command == "get":
            read_started.set()
            assert release_read.wait(5)
        return result

    monkeypatch.setattr(config_module, "_run_secret_manager", slow_get)
    reader = threading.Thread(
        target=config_module._get_secret_value, args=("exampletool-api-key", profile_path)
    )
    writer = threading.Thread(
        target=config_module._set_secret_value, args=("exampletool-api-key", "NEW", profile_path)
    )
    reader.start()
    assert read_started.wait(5)
    writer.start()
    writer.join(0.3)  # without the lock the write and its eviction finish here
    release_read.set()
    reader.join(5)
    writer.join(5)

    monkeypatch.setattr(config_module, "_run_secret_manager", real_run)
    assert config_module._get_secret_value("exampletool-api-key", profile_path) == "NEW"
