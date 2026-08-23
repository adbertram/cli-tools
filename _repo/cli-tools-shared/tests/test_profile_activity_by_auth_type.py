from functools import cache
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.config import BaseConfig, ConfigError, get_profile_auth_settings, get_profiles_base_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.profiles import ProfileStore, delete_profile, list_profiles, select_profile


class MultiAuthTypeConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ["AUTH_METHOD"]
    CUSTOM_ALL_FIELDS = ["AUTH_METHOD", "TENANT_ID"]
    PROFILE_AUTH_TYPE_FIELD = "AUTH_METHOD"
    PROFILE_AUTH_TYPES = {
        "az_cli": [],
        "device_code": [("TENANT_ID", "Tenant ID", False)],
    }


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


def _write_profile(path: Path, *, active: bool, auth_method: str, tenant_id: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"ACTIVE={'true' if active else 'false'}",
                f"AUTH_METHOD={auth_method}",
                f"TENANT_ID={tenant_id}",
            ]
        )
        + "\n"
    )


def _profile_store(tool_dir: Path) -> ProfileStore:
    return ProfileStore(
        tool_dir.name,
        tool_dir=tool_dir,
        profile_auth_settings=get_profile_auth_settings(MultiAuthTypeConfig),
    )


def _build_auth_app(tool_dir: Path):
    def get_config(profile=None, profile_auth_type=None) -> MultiAuthTypeConfig:
        return MultiAuthTypeConfig(
            tool_dir=tool_dir,
            profile=profile,
            profile_auth_type=profile_auth_type,
        )

    return create_auth_app(get_config, tool_name=tool_dir.name), get_config


def test_select_profile_only_changes_same_auth_type(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profiles_base = get_profiles_base_dir(tool_dir.name)

    _write_profile(profiles_base / "az-primary" / ".env", active=True, auth_method="az_cli")
    _write_profile(profiles_base / "az-secondary" / ".env", active=False, auth_method="az_cli")
    _write_profile(
        profiles_base / "device-primary" / ".env",
        active=True,
        auth_method="device_code",
        tenant_id="tenant-a",
    )

    store = _profile_store(tool_dir)
    select_profile(store, "az-secondary")

    profiles = {profile["name"]: profile for profile in list_profiles(store)}
    assert profiles["az-primary"]["active"] is False
    assert profiles["az-secondary"]["active"] is True
    assert profiles["az-primary"]["auth_type"] == "az_cli"
    assert profiles["az-secondary"]["auth_type"] == "az_cli"
    assert profiles["device-primary"]["active"] is True
    assert profiles["device-primary"]["auth_type"] == "device_code"


def test_auth_status_returns_only_active_profiles(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profiles_base = get_profiles_base_dir(tool_dir.name)

    _write_profile(profiles_base / "az-primary" / ".env", active=True, auth_method="az_cli")
    _write_profile(profiles_base / "az-secondary" / ".env", active=False, auth_method="az_cli")
    _write_profile(
        profiles_base / "device-primary" / ".env",
        active=True,
        auth_method="device_code",
        tenant_id="tenant-a",
    )

    app, _get_config = _build_auth_app(tool_dir)
    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert '"name": "az-primary"' in result.stdout
    assert '"name": "device-primary"' in result.stdout
    assert '"name": "az-secondary"' not in result.stdout
    assert '"auth_type": "az_cli"' in result.stdout
    assert '"auth_type": "device_code"' in result.stdout
    assert '"active": true' in result.stdout
    assert "is_default" not in result.stdout


def test_profile_commands_preserve_auth_type_with_cached_get_config(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profiles_base = get_profiles_base_dir(tool_dir.name)

    _write_profile(profiles_base / "device-primary" / ".env", active=True, auth_method="device_code")

    @cache
    def get_config(profile=None, profile_auth_type=None) -> MultiAuthTypeConfig:
        return MultiAuthTypeConfig(
            tool_dir=tool_dir,
            profile=profile,
            profile_auth_type=profile_auth_type,
        )

    app = create_auth_app(get_config, tool_name=tool_dir.name)
    result = CliRunner().invoke(app, ["profiles", "list"])

    assert result.exit_code == 0, result.output
    assert '"auth_type": "device_code"' in result.stdout


def test_delete_profile_refuses_only_active_profile_for_auth_type(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profiles_base = get_profiles_base_dir(tool_dir.name)

    _write_profile(profiles_base / "az-primary" / ".env", active=True, auth_method="az_cli")
    _write_profile(
        profiles_base / "device-primary" / ".env",
        active=True,
        auth_method="device_code",
        tenant_id="tenant-a",
    )

    with pytest.raises(
        ConfigError,
        match="Cannot delete active profile 'device-primary'. Select another device_code profile first.",
    ):
        delete_profile(_profile_store(tool_dir), "device-primary")


def test_base_config_requires_active_profile_for_requested_auth_type(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profiles_base = get_profiles_base_dir(tool_dir.name)

    _write_profile(profiles_base / "az-primary" / ".env", active=True, auth_method="az_cli")
    _write_profile(
        profiles_base / "device-primary" / ".env",
        active=False,
        auth_method="device_code",
        tenant_id="tenant-a",
    )

    with pytest.raises(
        ConfigError,
        match="No active profile found for auth type 'device_code'",
    ):
        MultiAuthTypeConfig(tool_dir=tool_dir, profile_auth_type="device_code")
