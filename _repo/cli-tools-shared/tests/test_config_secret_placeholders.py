from pathlib import Path
import subprocess

import pytest

import cli_tools_shared.config as config_module
from cli_tools_shared.config import BaseConfig, config_env_path_for_tool, get_profiles_base_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ConfigError


class ApiKeyConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.API_KEY]


class OAuthConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.OAUTH]


class UsernamePasswordConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.USERNAME_PASSWORD]


class UsernamePasswordConfigWithOptionalSecret(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.USERNAME_PASSWORD]
    ADDITIONAL_AUTH_FIELDS = ("OPTIONAL_TOKEN",)
    ADDITIONAL_SENSITIVE_AUTH_FIELDS = ("OPTIONAL_TOKEN",)
    OPTIONAL_SECRET_FIELDS = ("OPTIONAL_TOKEN",)


@pytest.fixture
def isolated_data_home(tmp_path, monkeypatch):
    data_home = tmp_path / "share"
    data_home.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    return data_home


def _tool_dir(tmp_path: Path, name: str = "exampletool") -> Path:
    tool_dir = tmp_path / name
    tool_dir.mkdir()
    return tool_dir


def _write_profile(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_load_resolves_secret_placeholder_for_auth_profile_fields(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(
        profile,
        "ACTIVE=true\nCLIENT_ID=secret://exampletool-client-id\nACCESS_TOKEN=\n",
    )

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        assert command == "get"
        assert secret_value is None
        if secret_name == "exampletool-client-id":
            return subprocess.CompletedProcess(
                [],
                0,
                stdout="client-id-123\n",
                stderr="",
            )
        assert secret_name == "exampletool-client-secret"
        return subprocess.CompletedProcess([], 1, stdout="", stderr="not found")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = OAuthConfig(tool_dir=tool_dir)

    assert config.client_id == "client-id-123"
    assert config.client_secret is None
    assert "CLIENT_ID=secret://exampletool-client-id" in profile.read_text()


def test_load_missing_secret_placeholder_raises_config_error(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(
        profile,
        "ACTIVE=true\nAPI_KEY=secret://exampletool-api-key\n",
    )

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        assert command == "get"
        return subprocess.CompletedProcess([], 1, stdout="", stderr="not found")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    with pytest.raises(ConfigError) as excinfo:
        ApiKeyConfig(tool_dir=tool_dir)

    message = str(excinfo.value)
    assert "exampletool-api-key" in message
    assert str(profile) in message


def test_load_missing_optional_secret_placeholder_treats_field_as_unconfigured(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(
        profile,
        "ACTIVE=true\n"
        "USERNAME=secret://exampletool-username\n"
        "PASSWORD=secret://exampletool-password\n"
        "OPTIONAL_TOKEN=secret://exampletool-optional-token\n",
    )

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        if command == "has":
            return subprocess.CompletedProcess(
                [],
                0 if secret_name in {"exampletool-username", "exampletool-password"} else 1,
                stdout="",
                stderr="",
            )
        if command == "get":
            values = {
                "exampletool-username": "alice",
                "exampletool-password": "secret-pass",
            }
            return subprocess.CompletedProcess(
                [],
                0 if secret_name in values else 1,
                stdout=f"{values.get(secret_name, '')}\n" if secret_name in values else "",
                stderr="",
            )
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = UsernamePasswordConfigWithOptionalSecret(tool_dir=tool_dir)

    assert config.username == "alice"
    assert config.password == "secret-pass"
    assert config._get("OPTIONAL_TOKEN") is None
    assert config.has_credentials() is True
    assert config.get_missing_credentials() == []


def test_empty_sensitive_auth_field_stays_empty_until_set(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, "ACTIVE=true\nAPI_KEY=\n")

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = ApiKeyConfig(tool_dir=tool_dir)

    assert "API_KEY=\n" in profile.read_text()
    assert config.api_key is None
    assert config.has_credentials() is False
    assert config.get_missing_credentials() == ["API_KEY"]


def test_load_resolves_secret_placeholder_for_root_config_env(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    root_env = config_env_path_for_tool(tool_dir.name)
    root_env.parent.mkdir(parents=True, exist_ok=True)
    root_env.write_text("BASE_URL=secret://exampletool-base-url\n")
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, "ACTIVE=true\nAPI_KEY=\n")

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        assert command == "get"
        assert secret_value is None
        if secret_name == "exampletool-base-url":
            return subprocess.CompletedProcess(
                [],
                0,
                stdout="https://api.example.test\n",
                stderr="",
            )
        assert secret_name == "exampletool-api-key"
        return subprocess.CompletedProcess([], 1, stdout="", stderr="not found")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = ApiKeyConfig(tool_dir=tool_dir)

    assert config.base_url == "https://api.example.test"
    assert "BASE_URL=secret://exampletool-base-url" in root_env.read_text()


def test_load_missing_root_config_secret_raises_config_error_with_env_path(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    root_env = config_env_path_for_tool(tool_dir.name)
    root_env.parent.mkdir(parents=True, exist_ok=True)
    root_env.write_text("BASE_URL=secret://exampletool-base-url\n")
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, "ACTIVE=true\nAPI_KEY=\n")

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        assert command == "get"
        return subprocess.CompletedProcess([], 1, stdout="", stderr="not found")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    with pytest.raises(ConfigError) as excinfo:
        ApiKeyConfig(tool_dir=tool_dir)

    message = str(excinfo.value)
    assert "exampletool-base-url" in message
    assert str(root_env) in message
    assert "not found" not in message


def test_set_sensitive_field_preserves_existing_placeholder_and_updates_secret(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(
        profile,
        "ACTIVE=true\n"
        "USERNAME=secret://exampletool-username\n"
        "PASSWORD=secret://saved-password\n",
    )
    calls = []

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        calls.append((command, secret_name, secret_value))
        if command == "get":
            values = {
                "saved-password": "old-password",
                "exampletool-username": "alice",
            }
            return subprocess.CompletedProcess([], 0, stdout=values[secret_name], stderr="")
        if command == "set":
            assert (secret_name, secret_value) == ("saved-password", "new-password")
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = UsernamePasswordConfig(tool_dir=tool_dir)
    config._set("PASSWORD", "new-password")

    assert ("set", "saved-password", "new-password") in calls
    assert "USERNAME=secret://exampletool-username" in profile.read_text()
    assert "PASSWORD='secret://saved-password'" in profile.read_text()
    assert config.password == "new-password"


@pytest.mark.parametrize(
    ("profile_name", "active", "expected_secret_name"),
    [
        ("default", True, "exampletool-api-key"),
        ("staging", False, "exampletool-staging-api-key"),
    ],
)
def test_set_sensitive_field_uses_deterministic_secret_names(
    tmp_path,
    monkeypatch,
    isolated_data_home,
    profile_name,
    active,
    expected_secret_name,
):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / profile_name / ".env"
    _write_profile(
        profile,
        f"ACTIVE={'true' if active else 'false'}\nAPI_KEY=\n",
    )
    calls = []

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        calls.append((command, secret_name, secret_value))
        if command == "get":
            return subprocess.CompletedProcess([], 1, stdout="", stderr="not found")
        if command == "set":
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = ApiKeyConfig(
        tool_dir=tool_dir,
        profile=None if profile_name == "default" else profile_name,
    )
    config.save_api_key("new-api-key")

    assert calls == [("set", expected_secret_name, "new-api-key")]
    assert f"API_KEY='secret://{expected_secret_name}'" in profile.read_text()
    assert config.api_key == "new-api-key"


def test_set_non_sensitive_auth_field_keeps_plaintext_in_profile_env(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(
        profile,
        "ACTIVE=true\nCLIENT_ID=old-client\nCLIENT_SECRET=\nACCESS_TOKEN=\n",
    )
    calls = []

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        calls.append((command, secret_name, secret_value))
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = OAuthConfig(tool_dir=tool_dir)
    config._set("CLIENT_ID", "new-client")

    assert calls == []
    assert "CLIENT_ID='new-client'" in profile.read_text()
    assert "CLIENT_SECRET=\n" in profile.read_text()
    assert config.client_id == "new-client"


def test_clear_sensitive_field_deletes_secret_store_entry(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, "ACTIVE=true\nAPI_KEY=secret://exampletool-api-key\n")
    calls = []

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        calls.append((command, secret_name, secret_value))
        if command == "get":
            return subprocess.CompletedProcess([], 0, stdout="saved-api-key\n", stderr="")
        if command == "has":
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if command == "delete":
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = ApiKeyConfig(tool_dir=tool_dir)
    config._clear("API_KEY")

    assert ("delete", "exampletool-api-key", None) in calls
    assert "API_KEY=''" in profile.read_text()
    assert config.api_key is None


def _detached_api_key_config(tool_dir: Path, env_path: Path) -> ApiKeyConfig:
    config = object.__new__(ApiKeyConfig)
    config._tool_name = tool_dir.name
    config.env_file_path = env_path
    config.config_env_file_path = config_env_path_for_tool(tool_dir.name)
    return config


def test_clear_sensitive_field_with_raw_value_does_not_touch_canonical_secret(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, "ACTIVE=true\nAPI_KEY=raw-api-key\n")
    monkeypatch.setenv("API_KEY", "raw-api-key")
    calls = []

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        calls.append((command, secret_name, secret_value))
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = _detached_api_key_config(tool_dir, profile)
    config._clear("API_KEY")

    assert calls == []
    assert "API_KEY=''" in profile.read_text()
    assert config.api_key is None


def test_clear_sensitive_field_with_empty_value_does_not_touch_canonical_secret(
    tmp_path,
    monkeypatch,
    isolated_data_home,
):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, "ACTIVE=true\nAPI_KEY=\n")
    monkeypatch.setenv("API_KEY", "stale-api-key")
    calls = []

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        calls.append((command, secret_name, secret_value))
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = _detached_api_key_config(tool_dir, profile)
    config._clear("API_KEY")

    assert calls == []
    assert "API_KEY=''" in profile.read_text()
    assert config.api_key is None
