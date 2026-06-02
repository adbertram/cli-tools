"""Tests for the cli-tools profile layout and secret placeholder routing.

These tests do NOT require live secrets. They monkeypatch the shared
CLI-tools secret-manager runner with an in-memory dict so profile
``secret://...`` placeholders can be verified deterministically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_secret_manager(monkeypatch):
    """Replace the CLI-tools secret manager with an in-memory dict."""
    store: dict[str, str] = {}

    def _run(command: str, secret_name: str, *, secret_value=None):
        if command == "get":
            if secret_name not in store:
                return subprocess.CompletedProcess([], 1, stdout="", stderr="not found")
            return subprocess.CompletedProcess([], 0, stdout=store[secret_name], stderr="")
        if command == "set":
            store[secret_name] = secret_value
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if command == "has":
            code = 0 if secret_name in store else 1
            return subprocess.CompletedProcess([], code, stdout="", stderr="")
        if command == "delete":
            if secret_name not in store:
                return subprocess.CompletedProcess([], 1, stdout="", stderr="not found")
            del store[secret_name]
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected secret-manager command: {command}")

    import cli_tools_shared.config as config_module

    monkeypatch.setattr(config_module, "_run_secret_manager", _run)
    return store


@pytest.fixture
def xdg_dirs(tmp_path, monkeypatch):
    """Point cli-tools user data at a tmp tree."""
    data_home = tmp_path / "data"
    cfg = data_home / "cli-tools" / "copilot"
    cache = cfg / "authentication_profiles" / "default" / "cache"
    cfg.mkdir(parents=True)
    cache.mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.delenv("COPILOT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("COPILOT_CACHE_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    # Always start with a fresh global config cache.
    from copilot_cli import config as copilot_cfg
    copilot_cfg._reset_config()
    return cfg, cache


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def test_xdg_data_home_resolves_cli_tools_config_root(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    from copilot_cli.config import get_config_root
    assert get_config_root() == tmp_path / "data" / "cli-tools" / "copilot"


def test_xdg_config_home_does_not_change_cli_tools_config_root(monkeypatch, tmp_path):
    monkeypatch.delenv("COPILOT_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    if sys.platform == "win32":
        pytest.skip("XDG_DATA_HOME is not honored on Windows by design.")

    from copilot_cli.config import get_config_root
    assert get_config_root() == tmp_path / "data" / "cli-tools" / "copilot"


def test_platform_default_when_no_overrides(monkeypatch):
    monkeypatch.delenv("COPILOT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    from copilot_cli.config import get_config_root
    root = get_config_root()
    home = Path.home()
    if sys.platform == "win32":
        # %APPDATA%\cli-tools\copilot
        assert root.name == "copilot"
    else:
        assert root == home / ".local" / "share" / "cli-tools" / "copilot"


def test_cache_dir_resolves_under_default_authentication_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    from copilot_cli.config import get_cache_root
    expected = (
        tmp_path
        / "data"
        / "cli-tools"
        / "copilot"
        / "authentication_profiles"
        / "default"
        / "cache"
    )
    assert get_cache_root() == expected


# ---------------------------------------------------------------------------
# Profile loading from cli-tools layout
# ---------------------------------------------------------------------------

def test_default_profile_loaded_from_xdg(xdg_dirs, fake_secret_manager):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "default").mkdir(parents=True, exist_ok=True)
    (profiles / "default" / ".env").write_text(
        "ACTIVE=true\nDATAVERSE_URL=https://default.example/\n"
    )

    from copilot_cli.config import Config
    config = Config()
    assert config.env_file_path == profiles / "default" / ".env"
    assert config.dataverse_url == "https://default.example/"


def test_explicit_profile_argument_wins(xdg_dirs, fake_secret_manager):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "default").mkdir(parents=True, exist_ok=True)
    (profiles / "default" / ".env").write_text(
        "ACTIVE=true\nDATAVERSE_URL=https://default.example/\n"
    )
    (profiles / "staging").mkdir(parents=True, exist_ok=True)
    (profiles / "staging" / ".env").write_text(
        "ACTIVE=false\nDATAVERSE_URL=https://staging.example/\n"
    )

    from copilot_cli.config import Config
    config = Config(profile="staging")
    assert config.env_file_path == profiles / "staging" / ".env"
    assert config.dataverse_url == "https://staging.example/"


def test_custom_profile_auth_type_uses_canonical_profile_resolution(xdg_dirs, fake_secret_manager):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "default").mkdir(parents=True, exist_ok=True)
    (profiles / "default" / ".env").write_text(
        "ACTIVE=true\nDATAVERSE_URL=https://default.example/\n"
    )

    from copilot_cli.config import Config
    config = Config(profile_auth_type="custom")
    assert config.env_file_path == profiles / "default" / ".env"
    assert config.dataverse_url == "https://default.example/"


def test_invalid_profile_auth_type_fails_fast(xdg_dirs, fake_secret_manager):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "default").mkdir(parents=True, exist_ok=True)
    (profiles / "default" / ".env").write_text(
        "ACTIVE=true\nDATAVERSE_URL=https://default.example/\n"
    )

    from cli_tools_shared.exceptions import ConfigError
    from copilot_cli.config import Config

    with pytest.raises(ConfigError, match="only supports profile auth type 'custom'"):
        Config(profile_auth_type="oauth")


def test_active_profile_marker_picks_winner(xdg_dirs, fake_secret_manager):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "default").mkdir(parents=True, exist_ok=True)
    (profiles / "default" / ".env").write_text(
        "ACTIVE=false\nDATAVERSE_URL=https://default.example/\n"
    )
    (profiles / "staging").mkdir(parents=True, exist_ok=True)
    (profiles / "staging" / ".env").write_text(
        "ACTIVE=true\nDATAVERSE_URL=https://staging.example/\n"
    )

    from copilot_cli.config import Config
    config = Config()
    assert config.env_file_path == profiles / "staging" / ".env"


def test_multiple_active_profiles_raises(xdg_dirs, fake_secret_manager):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "a").mkdir(parents=True, exist_ok=True)
    (profiles / "b").mkdir(parents=True, exist_ok=True)
    (profiles / "a" / ".env").write_text("ACTIVE=true\nDATAVERSE_URL=https://a/\n")
    (profiles / "b" / ".env").write_text("ACTIVE=true\nDATAVERSE_URL=https://b/\n")

    from cli_tools_shared.exceptions import ConfigError
    from copilot_cli.config import Config
    with pytest.raises(ConfigError):
        Config()


# ---------------------------------------------------------------------------
# Secret routing through CLI-tools secret placeholders
# ---------------------------------------------------------------------------

def test_sensitive_field_read_from_profile_secret_placeholder(xdg_dirs, fake_secret_manager):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "default").mkdir(parents=True, exist_ok=True)
    (profiles / "default" / ".env").write_text(
        "ACTIVE=true\n"
        "DATAVERSE_URL=https://default.example/\n"
        "AZURE_TENANT_ID=tenant-id\n"
        "AZURE_CLIENT_ID=client-id\n"
        "AZURE_CLIENT_SECRET=secret://copilot-azure-client-secret\n"
    )
    fake_secret_manager["copilot-azure-client-secret"] = "super-secret"

    from copilot_cli.config import Config
    config = Config()
    assert config.azure_client_secret == "super-secret"


def test_sensitive_field_write_routes_to_profile_secret_placeholder(xdg_dirs, fake_secret_manager):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "default").mkdir(parents=True, exist_ok=True)
    (profiles / "default" / ".env").write_text(
        "ACTIVE=true\n"
        "DATAVERSE_URL=https://default.example/\n"
    )

    from copilot_cli.config import Config
    config = Config()
    config._set("AZURE_CLIENT_SECRET", "rotated-secret")

    assert fake_secret_manager["copilot-azure-client-secret"] == "rotated-secret"
    text = (profiles / "default" / ".env").read_text()
    assert "AZURE_CLIENT_SECRET='secret://copilot-azure-client-secret'" in text
    assert "rotated-secret" not in text


def test_sensitive_field_clear_removes_secret_placeholder(xdg_dirs, fake_secret_manager):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "default").mkdir(parents=True, exist_ok=True)
    (profiles / "default" / ".env").write_text(
        "ACTIVE=true\n"
        "DATAVERSE_URL=https://default.example/\n"
        "AZURE_CLIENT_SECRET=secret://copilot-azure-client-secret\n"
    )
    fake_secret_manager["copilot-azure-client-secret"] = "x"

    from copilot_cli.config import Config
    config = Config()
    config._clear("AZURE_CLIENT_SECRET")
    assert "copilot-azure-client-secret" not in fake_secret_manager
    assert "AZURE_CLIENT_SECRET=''" in (profiles / "default" / ".env").read_text()


def test_plaintext_sensitive_profile_value_fails_fast(xdg_dirs, fake_secret_manager):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "default").mkdir(parents=True, exist_ok=True)
    (profiles / "default" / ".env").write_text(
        "ACTIVE=true\n"
        "DATAVERSE_URL=https://default.example/\n"
        "AZURE_CLIENT_SECRET=legacy-from-dotenv\n"
    )

    from cli_tools_shared.exceptions import ConfigError
    from copilot_cli.config import Config

    with pytest.raises(ConfigError, match="plain-text sensitive value"):
        Config()


def test_sensitive_process_env_value_is_ignored_when_profile_field_empty(
    xdg_dirs,
    fake_secret_manager,
    monkeypatch,
):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "authentication_profiles"
    (profiles / "default").mkdir(parents=True, exist_ok=True)
    (profiles / "default" / ".env").write_text(
        "ACTIVE=true\n"
        "DATAVERSE_URL=https://default.example/\n"
    )
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "process-secret")

    from copilot_cli.config import Config
    config = Config()

    assert config.azure_client_secret is None


# ---------------------------------------------------------------------------
# cli_tools_shared.paths sanity
# ---------------------------------------------------------------------------

def test_resolve_config_dir_app_specific_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MYAPP_CONFIG_DIR", str(tmp_path / "myapp-cfg"))
    from cli_tools_shared.paths import resolve_config_dir
    assert resolve_config_dir("myapp") == (tmp_path / "myapp-cfg").resolve()


def test_resolve_cache_dir_app_specific_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MYAPP_CACHE_DIR", str(tmp_path / "myapp-cache"))
    from cli_tools_shared.paths import resolve_cache_dir
    assert resolve_cache_dir("myapp") == (tmp_path / "myapp-cache").resolve()
