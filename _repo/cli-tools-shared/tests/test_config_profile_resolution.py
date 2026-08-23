from pathlib import Path

import pytest

import cli_tools_shared.config as config_module
from cli_tools_shared.config import BaseConfig, config_env_path_for_tool, get_profiles_base_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ConfigError
from cli_tools_shared.profiles import (
    create_profile,
    delete_profile,
    list_profiles,
    select_profile,
)


class CustomConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ["API_URL"]
    CUSTOM_ALL_FIELDS = ["API_URL"]


def _write_profile(path: Path, *, active: bool, api_url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"ACTIVE={'true' if active else 'false'}",
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


def _fake_secret_manager(initial: dict[str, str] | None = None):
    secrets = dict(initial or {})

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        if command == "has":
            return type("Result", (), {"returncode": 0 if secret_name in secrets else 1, "stdout": "", "stderr": ""})()
        if command == "get":
            return type(
                "Result",
                (),
                {
                    "returncode": 0 if secret_name in secrets else 1,
                    "stdout": f"{secrets.get(secret_name, '')}\n" if secret_name in secrets else "",
                    "stderr": "",
                },
            )()
        if command == "set":
            secrets[secret_name] = secret_value or ""
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if command == "delete":
            secrets.pop(secret_name, None)
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        raise AssertionError(f"Unexpected command: {command}")

    return fake_run, secrets


def test_config_uses_active_profile_marker(tmp_path, monkeypatch, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profiles_base = get_profiles_base_dir(tool_dir.name)
    active = profiles_base / "active" / ".env"
    other = profiles_base / "env_override" / ".env"

    _write_profile(active, active=True, api_url="https://active.example.com")
    _write_profile(other, active=False, api_url="https://env.example.com")
    monkeypatch.setenv("CLI_TOOLS_PROFILE", "env_override")

    config = CustomConfig(tool_dir=tool_dir)

    assert config.env_file_path == active
    assert config._get("API_URL") == "https://active.example.com"


def test_storage_dir_uses_active_profile_data_dir(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    active = get_profiles_base_dir(tool_dir.name) / "active" / ".env"
    _write_profile(active, active=True, api_url="https://active.example.com")

    config = CustomConfig(tool_dir=tool_dir)

    assert config.storage_dir == config.get_profile_data_dir()
    assert config.storage_dir == active.parent


def test_config_allows_explicit_profile_argument(tmp_path, monkeypatch, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profiles_base = get_profiles_base_dir(tool_dir.name)
    active = profiles_base / "active" / ".env"
    explicit = profiles_base / "explicit" / ".env"

    _write_profile(active, active=True, api_url="https://active.example.com")
    _write_profile(explicit, active=False, api_url="https://explicit.example.com")
    monkeypatch.setenv("CLI_TOOLS_PROFILE", "active")

    config = CustomConfig(tool_dir=tool_dir, profile="explicit")

    assert config.env_file_path == explicit
    assert config._get("API_URL") == "https://explicit.example.com"


def test_process_env_overrides_root_config_env(tmp_path, monkeypatch, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    root_env = config_env_path_for_tool(tool_dir.name)
    root_env.parent.mkdir(parents=True, exist_ok=True)
    root_env.write_text("CACHE_ENABLED=true\nCACHE_TTL=3600\n")
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, active=True, api_url="https://active.example.com")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    monkeypatch.setenv("CACHE_TTL", "0")

    config = CustomConfig(tool_dir=tool_dir)

    assert config._get("CACHE_ENABLED") == "false"
    assert config._get("CACHE_TTL") == "0"


def test_save_tokens_clears_refresh_token_when_missing(tmp_path, isolated_data_home):
    class OAuthConfig(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.OAUTH_AUTHORIZATION_CODE]

    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "ACTIVE=true\n"
        "ACCESS_TOKEN=\n"
        "REFRESH_TOKEN='secret://exampletool-refresh-token'\n"
        "TOKEN_EXPIRES_AT=1\n"
    )
    fake_run, _secrets = _fake_secret_manager(
        {"exampletool-refresh-token": "old-refresh-token"}
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = OAuthConfig(tool_dir=tool_dir)
    config.save_tokens("new-access-token", None, "999")

    content = profile.read_text()
    assert "ACCESS_TOKEN='secret://exampletool-access-token'" in content
    assert "REFRESH_TOKEN=''" in content
    assert "TOKEN_EXPIRES_AT='999'" in content
    assert config.access_token == "new-access-token"
    assert config.refresh_token is None
    monkeypatch.undo()


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
        "ACTIVE=true\n"
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


def test_static_oauth_has_credentials_requires_refresh_token(tmp_path, isolated_data_home, monkeypatch):
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
        "ACTIVE=true\n"
        "CLIENT_ID=client-id\n"
        "CLIENT_SECRET=secret://exampletool-client-secret\n"
        "ACCESS_TOKEN=secret://exampletool-access-token\n"
        "REFRESH_TOKEN=\n"
    )
    fake_run, _secrets = _fake_secret_manager(
        {
            "exampletool-client-secret": "client-secret",
            "exampletool-access-token": "access-token",
        }
    )
    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    config = StaticOAuthConfig(tool_dir=tool_dir)

    assert config.has_credentials() is False


# ---------------------------------------------------------------------------
# Canonical profile cutover: legacy paths are not migrated at runtime.
# ---------------------------------------------------------------------------


def test_source_env_file_raises_clear_cutover_error(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    legacy = tool_dir / ".env"
    legacy.write_text("ACTIVE=true\nAPI_URL=https://legacy.example.com\n")

    with pytest.raises(ConfigError, match="Unsupported legacy profile layout detected"):
        CustomConfig(tool_dir=tool_dir)


def test_source_authentication_profiles_dir_raises_clear_cutover_error(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    legacy = tool_dir / "authentication_profiles" / "default"
    cookies = legacy / "browser-data" / "chromium-profile" / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True)
    cookies.write_text("")

    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, active=True, api_url="https://canonical.example.com")

    with pytest.raises(ConfigError, match="Unsupported legacy profile layout detected"):
        CustomConfig(tool_dir=tool_dir)
    assert cookies.exists()


def test_legacy_user_data_profiles_dir_raises_clear_cutover_error(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    legacy = isolated_data_home / "cli-tools" / tool_dir.name / ".profiles" / "default"
    cookies = legacy / "browser-data" / "chromium-profile" / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True)
    cookies.write_text("")

    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, active=True, api_url="https://canonical.example.com")

    with pytest.raises(ConfigError, match="Unsupported legacy profile layout detected"):
        CustomConfig(tool_dir=tool_dir)
    assert cookies.exists()


def test_no_active_marker_raises_instead_of_falling_back_to_default_profile(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, active=False, api_url="https://default.example.com")

    with pytest.raises(ConfigError, match="No active profile found"):
        CustomConfig(tool_dir=tool_dir)


def test_profile_env_with_tool_config_field_raises(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "ACTIVE=true\n"
        "API_URL=https://auth.example.com\n"
        "BASE_URL=https://config.example.com\n"
    )

    with pytest.raises(ConfigError, match="non-authentication configuration fields"):
        CustomConfig(tool_dir=tool_dir)


def test_sensitive_profile_value_must_be_secret_placeholder(tmp_path, isolated_data_home):
    class OAuthConfig(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.OAUTH]

    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "ACTIVE=true\n"
        "CLIENT_ID=client-id\n"
        "CLIENT_SECRET=raw-secret\n"
        "ACCESS_TOKEN=\n"
    )

    with pytest.raises(ConfigError, match="plain-text sensitive value"):
        OAuthConfig(tool_dir=tool_dir)


def test_profile_crud_uses_canonical_layout_for_tool_dir_callers(tmp_path, isolated_data_home):
    tool_dir = _tool_dir(tmp_path)
    (tool_dir / ".env.example").write_text(
        "API_URL=\nBASE_URL=https://config.example.com\n"
    )

    staging = create_profile(tool_dir, "staging")
    default = create_profile(tool_dir, "default")
    select_profile(tool_dir, "default")

    assert staging == get_profiles_base_dir(tool_dir.name) / "staging" / ".env"
    assert "ACTIVE=false" in staging.read_text()
    assert "BASE_URL" not in staging.read_text()

    root_env = get_profiles_base_dir(tool_dir.name).parent / ".env"
    assert root_env.read_text() == "BASE_URL=https://config.example.com\n"

    profiles = list_profiles(tool_dir)
    assert profiles == [
        {"name": "default", "file": ".env", "auth_type": "default", "active": True},
        {"name": "staging", "file": ".env", "auth_type": "default", "active": False},
    ]

    delete_profile(tool_dir, "staging")
    assert not staging.parent.exists()


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
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, active=True, api_url="https://x")

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
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, active=True, api_url="https://x")

    config = CustomConfig(tool_dir=tool_dir)

    # Nothing -> False.
    assert config.has_saved_session() is False

    # Legacy marker alone -> False.
    (config.get_browser_data_dir() / "profile.json").write_text("{}")
    assert config.has_saved_session() is False

    # The cookie file under chromium-profile/Default -> True.
    cookies = config.get_persistent_profile_dir() / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True, exist_ok=True)
    cookies.write_text("sqlite-stub")
    assert config.has_saved_session() is True


def test_clear_session_removes_browser_data_without_deleting_profile_env(tmp_path, isolated_data_home):
    """Browser-session force login must not wipe non-browser credentials."""
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, active=True, api_url="https://x")

    config = CustomConfig(tool_dir=tool_dir)
    env_file = config.env_file_path
    env_file.write_text(
        "ACTIVE=true\n"
        "CLIENT_ID=client-id\n"
        "CLIENT_SECRET=secret://exampletool-client-secret\n"
        "ACCESS_TOKEN=secret://exampletool-access-token\n"
        "REFRESH_TOKEN=secret://exampletool-refresh-token\n"
    )
    cookies = config.get_persistent_profile_dir() / "Default" / "Cookies"
    cookies.parent.mkdir(parents=True, exist_ok=True)
    cookies.write_text("sqlite-stub")

    config.clear_session()

    assert env_file.exists()
    assert "ACCESS_TOKEN=secret://exampletool-access-token" in env_file.read_text()
    assert not (config.get_profile_data_dir() / "browser-data").exists()


def test_clear_session_removes_browser_data_when_browser_configured(tmp_path, isolated_data_home):
    """Config-level session cleanup owns profile data deletion."""
    tool_dir = _tool_dir(tmp_path)
    profile = get_profiles_base_dir(tool_dir.name) / "default" / ".env"
    _write_profile(profile, active=True, api_url="https://x")

    calls = []

    class _Browser:
        def clear_session(self):
            calls.append("clear_session")

    class BrowserConfig(CustomConfig):
        CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]

        def get_browser(self):
            return _Browser()

    config = BrowserConfig(tool_dir=tool_dir)
    browser_data = config.get_profile_data_dir() / "browser-data"
    browser_data.mkdir(parents=True)

    config.clear_session()

    assert calls == []
    assert not browser_data.exists()
