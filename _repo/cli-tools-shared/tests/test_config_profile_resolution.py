from pathlib import Path

import pytest

from cli_tools_shared.config import BaseConfig, config_env_path_for_tool, get_profiles_base_dir
from cli_tools_shared.credentials import CredentialType


class CustomConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ["API_URL"]
    CUSTOM_ALL_FIELDS = ["API_URL"]


def _write_profile(path: Path, *, is_default: bool, api_url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"IS_DEFAULT_PROFILE={1 if is_default else 0}",
                f"API_URL={api_url}",
            ]
        )
        + "\n"
    )


@pytest.fixture
def isolated_data_home(tmp_path, monkeypatch):
    """Redirect ``XDG_DATA_HOME`` so per-account state is sandboxed."""
    data_home = tmp_path / "share"
    data_home.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    return data_home


def _tool_dir(tmp_path: Path, name: str = "exampletool") -> Path:
    """Materialize a fake tool source folder for ``BaseConfig`` to use."""
    tool_dir = tmp_path / name
    tool_dir.mkdir()
    return tool_dir


def test_config_uses_active_profile_marked_default(tmp_path, monkeypatch, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profiles_base = get_profiles_base_dir(tool_dir.name)
    active = profiles_base / "active" / ".env"
    other = profiles_base / "env_override" / ".env"

    _write_profile(active, is_default=True, api_url="https://active.example.com")
    _write_profile(other, is_default=False, api_url="https://env.example.com")
    monkeypatch.setenv("CLI_TOOLS_PROFILE", "env_override")

    config = CustomConfig(tool_dir=tool_dir)

    assert config.env_file_path == active
    assert config._get("API_URL") == "https://active.example.com"


def test_config_allows_explicit_profile_argument(tmp_path, monkeypatch, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profiles_base = get_profiles_base_dir(tool_dir.name)
    active = profiles_base / "active" / ".env"
    explicit = profiles_base / "explicit" / ".env"

    _write_profile(active, is_default=True, api_url="https://active.example.com")
    _write_profile(explicit, is_default=False, api_url="https://explicit.example.com")
    monkeypatch.setenv("CLI_TOOLS_PROFILE", "active")

    config = CustomConfig(tool_dir=tool_dir, profile="explicit")

    assert config.env_file_path == explicit
    assert config._get("API_URL") == "https://explicit.example.com"


def test_save_tokens_clears_refresh_token_when_missing(tmp_path, isolated_data_home):
    class OAuthConfig(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.OAUTH_AUTHORIZATION_CODE]

    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "ACCESS_TOKEN=old-access-token\n"
        "REFRESH_TOKEN=old-refresh-token\n"
        "TOKEN_EXPIRES_AT=1\n"
    )

    config = OAuthConfig(tool_dir=tool_dir)
    config.save_tokens("new-access-token", None, "999")

    content = profile.read_text()
    assert "ACCESS_TOKEN='new-access-token'" in content
    assert "REFRESH_TOKEN=''" in content
    assert "TOKEN_EXPIRES_AT='999'" in content
    assert config.refresh_token is None


def test_static_oauth_missing_credentials_include_refresh_token(tmp_path, isolated_data_home):
    class StaticOAuthConfig(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.OAUTH]
        OAUTH_TOKEN_EXPIRES = False
        OAUTH_STATIC_REQUIRED_FIELDS = (
            "CLIENT_ID",
            "CLIENT_SECRET",
            "ACCESS_TOKEN",
            "REFRESH_TOKEN",
        )

    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "CLIENT_ID=\n"
        "CLIENT_SECRET=\n"
        "ACCESS_TOKEN=\n"
        "REFRESH_TOKEN=\n"
    )

    config = StaticOAuthConfig(tool_dir=tool_dir)

    assert config.get_missing_credentials() == [
        "CLIENT_ID",
        "CLIENT_SECRET",
        "ACCESS_TOKEN",
        "REFRESH_TOKEN",
    ]


def test_static_oauth_has_credentials_requires_refresh_token(tmp_path, isolated_data_home):
    class StaticOAuthConfig(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.OAUTH]
        OAUTH_TOKEN_EXPIRES = False
        OAUTH_STATIC_REQUIRED_FIELDS = (
            "CLIENT_ID",
            "CLIENT_SECRET",
            "ACCESS_TOKEN",
            "REFRESH_TOKEN",
        )

    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "CLIENT_ID=client-id\n"
        "CLIENT_SECRET=client-secret\n"
        "ACCESS_TOKEN=access-token\n"
        "REFRESH_TOKEN=\n"
    )

    config = StaticOAuthConfig(tool_dir=tool_dir)

    assert config.has_credentials() is False


# ---------------------------------------------------------------------------
# Migration from legacy ``tool_dir/.env*`` layout
# ---------------------------------------------------------------------------


def test_migrates_default_env_to_user_data_dir(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    legacy = tool_dir / ".env"
    legacy.write_text("IS_DEFAULT_PROFILE=1\nAPI_URL=https://migrated.example.com\n")

    config = CustomConfig(tool_dir=tool_dir)

    expected = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    assert expected.exists()
    assert not legacy.exists()
    assert config.env_file_path == expected
    assert config._get("API_URL") == "https://migrated.example.com"


def test_migrates_non_auth_env_values_to_tool_root_config(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    (tool_dir / ".env").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "API_URL=https://auth.example.com\n"
        "BASE_URL=https://config.example.com\n"
        "CACHE_ENABLED=false\n"
    )

    config = CustomConfig(tool_dir=tool_dir)

    profile_env = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    root_env = config_env_path_for_tool(tool_dir.name)
    assert profile_env.exists()
    assert root_env.exists()
    assert "API_URL=https://auth.example.com" in profile_env.read_text()
    assert "BASE_URL" not in profile_env.read_text()
    root_content = root_env.read_text()
    assert "BASE_URL=https://config.example.com" in root_content
    assert "CACHE_ENABLED=false" in root_content
    assert config.base_url == "https://config.example.com"


def test_migrates_named_profile_envs(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    (tool_dir / ".env").write_text(
        "IS_DEFAULT_PROFILE=1\nAPI_URL=https://default.example.com\n"
    )
    (tool_dir / ".env.staging").write_text(
        "IS_DEFAULT_PROFILE=0\nAPI_URL=https://staging.example.com\n"
    )

    CustomConfig(tool_dir=tool_dir)

    base = get_profiles_base_dir(tool_dir.name)
    assert (base / "default" / ".env").exists()
    assert (base / "staging" / ".env").exists()
    assert not (tool_dir / ".env").exists()
    assert not (tool_dir / ".env.staging").exists()


def test_migration_preserves_env_example(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    (tool_dir / ".env").write_text("IS_DEFAULT_PROFILE=1\nAPI_URL=https://x\n")
    (tool_dir / ".env.example").write_text("API_URL=...\n")

    CustomConfig(tool_dir=tool_dir)

    assert (tool_dir / ".env.example").exists()
    assert not (tool_dir / ".env").exists()


def test_migration_is_idempotent(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    (tool_dir / ".env").write_text("IS_DEFAULT_PROFILE=1\nAPI_URL=https://x\n")

    CustomConfig(tool_dir=tool_dir)
    target = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    mtime_after_first = target.stat().st_mtime

    # Second instantiation should not touch the migrated file.
    CustomConfig(tool_dir=tool_dir)
    assert target.stat().st_mtime == mtime_after_first


def test_migration_with_collision_drops_repo_copy(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    base = get_profiles_base_dir(tool_dir.name)
    target = base / "default" / ".env"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("IS_DEFAULT_PROFILE=1\nAPI_URL=https://local.example.com\n")
    (tool_dir / ".env").write_text(
        "IS_DEFAULT_PROFILE=1\nAPI_URL=https://repo.example.com\n"
    )

    config = CustomConfig(tool_dir=tool_dir)

    # Local copy wins; repo copy is removed.
    assert config._get("API_URL") == "https://local.example.com"
    assert not (tool_dir / ".env").exists()


# ---------------------------------------------------------------------------
# Source-tree ``tool_dir/authentication_profiles/`` browser-state migration
# ---------------------------------------------------------------------------


def test_migrates_source_authentication_profiles_dir(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    legacy = tool_dir / "authentication_profiles" / "default"
    cookies = legacy / "browser-data" / "chromium-profile" / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True)
    cookies.write_text("")

    (tool_dir / ".env").write_text("IS_DEFAULT_PROFILE=1\nAPI_URL=https://x\n")

    CustomConfig(tool_dir=tool_dir)

    new_dir = get_profiles_base_dir(tool_dir.name) / "default"
    assert (new_dir / "browser-data" / "chromium-profile" / "Default" / "Cookies").exists()
    assert (new_dir / ".env").exists()
    assert not (tool_dir / "authentication_profiles").exists()


# ---------------------------------------------------------------------------
# Persistent Chromium profile dir resolution (A1).
#
# ``BaseConfig.get_persistent_profile_dir()`` must point at
# ``<browser_data_dir>/chromium-profile`` — the persistent Chromium
# user-data-dir for the active profile. Chrome auto-creates ``Default/``
# inside.
# ---------------------------------------------------------------------------


def test_get_persistent_profile_dir_resolves_under_browser_data_dir(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    (tool_dir / ".env").write_text("IS_DEFAULT_PROFILE=1\nAPI_URL=https://x\n")

    config = CustomConfig(tool_dir=tool_dir)

    persistent = config.get_persistent_profile_dir()
    expected = config.get_browser_data_dir() / "chromium-profile"
    assert persistent == expected


def test_has_saved_session_requires_chromium_profile_default_cookies(tmp_path, isolated_data_home):
    """Single source of truth: only the Chrome cookies DB counts.

    Legacy ``profile.json`` markers or arbitrary files under
    ``browser-data/`` are no longer considered "saved session".
    """
    tool_dir = _tool_dir(tmp_path)
    (tool_dir / ".env").write_text("IS_DEFAULT_PROFILE=1\nAPI_URL=https://x\n")

    config = CustomConfig(tool_dir=tool_dir)

    # Nothing → False.
    assert config.has_saved_session() is False

    # Legacy marker alone → False.
    (config.get_browser_data_dir() / "profile.json").write_text("{}")
    assert config.has_saved_session() is False

    # The cookie file under chromium-profile/Default → True.
    cookies = config.get_persistent_profile_dir() / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True, exist_ok=True)
    cookies.write_text("sqlite-stub")
    assert config.has_saved_session() is True


def test_clear_session_removes_browser_data_without_deleting_profile_env(tmp_path, isolated_data_home):
    """Browser-session force login must not wipe non-browser credentials."""
    tool_dir = _tool_dir(tmp_path)
    (tool_dir / ".env").write_text("IS_DEFAULT_PROFILE=1\nAPI_URL=https://x\n")

    config = CustomConfig(tool_dir=tool_dir)
    env_file = config.env_file_path
    env_file.write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "CLIENT_ID=client-id\n"
        "CLIENT_SECRET=client-secret\n"
        "ACCESS_TOKEN=access-token\n"
        "REFRESH_TOKEN=refresh-token\n"
    )
    cookies = config.get_persistent_profile_dir() / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True, exist_ok=True)
    cookies.write_text("sqlite-stub")

    config.clear_session()

    assert env_file.exists()
    assert "ACCESS_TOKEN=access-token" in env_file.read_text()
    assert not (config.get_profile_data_dir() / "browser-data").exists()
