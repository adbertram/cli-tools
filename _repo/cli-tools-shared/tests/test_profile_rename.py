"""Tests for ``rename_profile`` and the ``auth profiles rename`` command.

State is isolated by the autouse fixture in ``conftest.py``, which points
``XDG_DATA_HOME`` at a temp dir and replaces ``_run_secret_manager`` with an
in-memory dict-backed store. ``secrets`` (the dict) is returned by that fixture
so tests can seed and assert raw secret values without touching the real
Keychain.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli_tools_shared.config import (
    BaseConfig,
    get_profiles_base_dir,
)
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ConfigError
from cli_tools_shared.profiles import ProfileStore, list_profiles, rename_profile
from cli_tools_shared.profiles_commands import create_profiles_app


class ApiKeyConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.API_KEY]


def _tool_dir(tmp_path: Path, name: str = "exampletool") -> Path:
    tool_dir = tmp_path / name
    tool_dir.mkdir()
    return tool_dir


def _write_profile(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _store(tool_dir: Path) -> ProfileStore:
    return ProfileStore(tool_dir.name, tool_dir=tool_dir)


def _config_secret_name(tool_dir: Path, profile: str, field: str) -> str:
    """Compute the profile-scoped secret name using the real config builder."""
    new_env_path = get_profiles_base_dir(tool_dir.name) / profile / ".env"
    config = object.__new__(ApiKeyConfig)
    config._tool_name = tool_dir.name
    return config._secret_name_for_field_in_profile(field, new_env_path)


def _secret_builder(tool_dir: Path):
    def _builder(field_name: str, new_env_path: Path) -> str:
        config = object.__new__(ApiKeyConfig)
        config._tool_name = tool_dir.name
        return config._secret_name_for_field_in_profile(field_name, new_env_path)

    return _builder


# ---------------------------------------------------------------------------
# rename_profile (function-level)
# ---------------------------------------------------------------------------


def test_rename_moves_dir_rewrites_placeholders_and_rekeys_secrets(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    secrets = isolated_user_data_and_in_memory_secret_manager
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    old_env = base / "staging" / ".env"
    _write_profile(old_env, "ACTIVE=false\nAPI_KEY=secret://exampletool-staging-api-key\n")
    secrets["exampletool-staging-api-key"] = "staging-key-value"

    rename_profile(
        _store(tool_dir),
        "staging",
        "production",
        secret_name_for_field=_secret_builder(tool_dir),
    )

    new_env = base / "production" / ".env"
    # Old dir gone, new dir present.
    assert not old_env.parent.exists()
    assert new_env.exists()

    # Placeholder rewritten to the new profile-scoped secret name.
    new_secret_name = _config_secret_name(tool_dir, "production", "API_KEY")
    assert new_secret_name == "exampletool-production-api-key"
    assert f"API_KEY=secret://{new_secret_name}" in new_env.read_text()

    # Secret value re-keyed in the store; old key removed.
    assert secrets[new_secret_name] == "staging-key-value"
    assert "exampletool-staging-api-key" not in secrets


def test_rename_copies_cache_directory(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    old_env = base / "staging" / ".env"
    _write_profile(old_env, "ACTIVE=false\nAPI_KEY=\n")
    cache_dir = old_env.parent / "cache"
    cache_dir.mkdir()
    (cache_dir / "token.json").write_text('{"token": "abc"}')

    rename_profile(_store(tool_dir), "staging", "production")

    new_cache_file = base / "production" / "cache" / "token.json"
    assert new_cache_file.exists()
    assert new_cache_file.read_text() == '{"token": "abc"}'
    assert not old_env.parent.exists()


def test_rename_carries_active_marker_from_old_to_new(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    # Two API_KEY profiles; 'staging' is the active one.
    _write_profile(base / "staging" / ".env", "ACTIVE=true\nAPI_KEY=\n")
    _write_profile(base / "other" / ".env", "ACTIVE=false\nAPI_KEY=\n")

    rename_profile(_store(tool_dir), "staging", "production")

    profiles = {p["name"]: p for p in list_profiles(_store(tool_dir))}
    assert "staging" not in profiles
    assert profiles["production"]["active"] is True
    assert profiles["other"]["active"] is False
    # Exactly one active profile for the auth type — never two, never zero.
    assert sum(1 for p in profiles.values() if p["active"]) == 1


def test_rename_fails_fast_when_new_already_exists(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    _write_profile(base / "staging" / ".env", "ACTIVE=false\nAPI_KEY=\n")
    _write_profile(base / "production" / ".env", "ACTIVE=true\nAPI_KEY=\n")

    with pytest.raises(ConfigError, match="Profile 'production' already exists"):
        rename_profile(_store(tool_dir), "staging", "production")

    # Both untouched.
    assert (base / "staging" / ".env").exists()
    assert (base / "production" / ".env").exists()


def test_rename_fails_fast_when_old_missing(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    tool_dir = _tool_dir(tmp_path)

    with pytest.raises(ConfigError, match="Profile 'staging' not found"):
        rename_profile(_store(tool_dir), "staging", "production")


def test_rename_keep_old_leaves_old_dir_and_secrets_and_activates_new(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    secrets = isolated_user_data_and_in_memory_secret_manager
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    old_env = base / "staging" / ".env"
    _write_profile(old_env, "ACTIVE=true\nAPI_KEY=secret://exampletool-staging-api-key\n")
    secrets["exampletool-staging-api-key"] = "staging-key-value"

    rename_profile(
        _store(tool_dir),
        "staging",
        "production",
        secret_name_for_field=_secret_builder(tool_dir),
        keep_old=True,
    )

    new_env = base / "production" / ".env"
    new_secret_name = _config_secret_name(tool_dir, "production", "API_KEY")

    # Old profile + old secret fully intact.
    assert old_env.exists()
    assert secrets["exampletool-staging-api-key"] == "staging-key-value"

    # New profile built, secret copied, and activated; old deactivated.
    assert new_env.exists()
    assert secrets[new_secret_name] == "staging-key-value"

    profiles = {p["name"]: p for p in list_profiles(_store(tool_dir))}
    assert profiles["production"]["active"] is True
    assert profiles["staging"]["active"] is False


def test_renamed_profile_sensitive_fields_resolve_to_original_values(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    secrets = isolated_user_data_and_in_memory_secret_manager
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    old_env = base / "staging" / ".env"
    _write_profile(old_env, "ACTIVE=true\nAPI_KEY=secret://exampletool-staging-api-key\n")
    secrets["exampletool-staging-api-key"] = "original-secret-value"

    rename_profile(
        _store(tool_dir),
        "staging",
        "production",
        secret_name_for_field=_secret_builder(tool_dir),
    )

    # Load the renamed profile through the real config and confirm the
    # sensitive field resolves to the original secret value.
    config = ApiKeyConfig(tool_dir=tool_dir, profile="production")
    assert config.api_key == "original-secret-value"


def test_rename_requires_secret_builder_when_placeholders_present(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    secrets = isolated_user_data_and_in_memory_secret_manager
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    old_env = base / "staging" / ".env"
    _write_profile(old_env, "ACTIVE=false\nAPI_KEY=secret://exampletool-staging-api-key\n")
    secrets["exampletool-staging-api-key"] = "staging-key-value"

    with pytest.raises(ConfigError, match="no .*secret-name builder"):
        rename_profile(_store(tool_dir), "staging", "production")

    # Aborted cleanly: old profile + secret intact, no partial new profile.
    assert old_env.exists()
    assert not (base / "production").exists()
    assert "exampletool-staging-api-key" in secrets


def test_rename_aborts_and_preserves_old_when_secret_copy_fails(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
    monkeypatch,
):
    """A failing secret copy must not delete the old profile or its secrets."""
    import cli_tools_shared.profiles as profiles_module

    secrets = isolated_user_data_and_in_memory_secret_manager
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    old_env = base / "staging" / ".env"
    _write_profile(old_env, "ACTIVE=true\nAPI_KEY=secret://exampletool-staging-api-key\n")
    secrets["exampletool-staging-api-key"] = "staging-key-value"

    def boom(secret_name, value, profile_path):
        raise ConfigError(f"Failed to store secret '{secret_name}' for {profile_path}.")

    monkeypatch.setattr(profiles_module, "_set_secret_value", boom)

    with pytest.raises(ConfigError, match="Failed to store secret"):
        rename_profile(
            _store(tool_dir),
            "staging",
            "production",
            secret_name_for_field=_secret_builder(tool_dir),
        )

    # Old profile + old secret intact; new profile dir rolled back.
    assert old_env.exists()
    assert secrets["exampletool-staging-api-key"] == "staging-key-value"
    assert not (base / "production").exists()


# ---------------------------------------------------------------------------
# auth profiles rename (CLI-level)
# ---------------------------------------------------------------------------


def _build_profiles_app(tool_dir: Path):
    def get_config(profile=None, profile_auth_type=None) -> ApiKeyConfig:
        return ApiKeyConfig(
            tool_dir=tool_dir,
            profile=profile,
            profile_auth_type=profile_auth_type,
        )

    return create_profiles_app(get_config, tool_name=tool_dir.name)


def test_cli_rename_with_force_moves_profile_and_rekeys_secret(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    secrets = isolated_user_data_and_in_memory_secret_manager
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    old_env = base / "staging" / ".env"
    _write_profile(old_env, "ACTIVE=true\nAPI_KEY=secret://exampletool-staging-api-key\n")
    secrets["exampletool-staging-api-key"] = "staging-key-value"

    app = _build_profiles_app(tool_dir)
    result = CliRunner().invoke(app, ["rename", "staging", "production", "--force"])

    assert result.exit_code == 0, result.output
    new_env = base / "production" / ".env"
    new_secret_name = _config_secret_name(tool_dir, "production", "API_KEY")
    assert new_env.exists()
    assert not old_env.parent.exists()
    assert secrets[new_secret_name] == "staging-key-value"
    assert "exampletool-staging-api-key" not in secrets


def test_cli_rename_non_interactive_without_force_refuses(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    old_env = base / "staging" / ".env"
    _write_profile(old_env, "ACTIVE=true\nAPI_KEY=\n")

    app = _build_profiles_app(tool_dir)
    # No TTY in the test runner; without --force the destructive guard refuses.
    result = CliRunner().invoke(app, ["rename", "staging", "production"])

    assert result.exit_code != 0
    # Old profile untouched, new profile not created.
    assert old_env.exists()
    assert not (base / "production").exists()


def test_cli_rename_keep_old_leaves_old_intact(
    tmp_path,
    isolated_user_data_and_in_memory_secret_manager,
):
    secrets = isolated_user_data_and_in_memory_secret_manager
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)

    old_env = base / "staging" / ".env"
    _write_profile(old_env, "ACTIVE=true\nAPI_KEY=secret://exampletool-staging-api-key\n")
    secrets["exampletool-staging-api-key"] = "staging-key-value"

    app = _build_profiles_app(tool_dir)
    # --keep-old skips the destructive confirmation by design.
    result = CliRunner().invoke(app, ["rename", "staging", "production", "--keep-old"])

    assert result.exit_code == 0, result.output
    assert old_env.exists()
    assert secrets["exampletool-staging-api-key"] == "staging-key-value"

    profiles = {p["name"]: p for p in list_profiles(_store(tool_dir))}
    assert profiles["production"]["active"] is True
    assert profiles["staging"]["active"] is False
