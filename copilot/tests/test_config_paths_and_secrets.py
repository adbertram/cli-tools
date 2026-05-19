"""Tests for the XDG config layout and OS-keychain secret routing.

These tests do NOT require a live keychain — they monkeypatch
``cli_tools_shared.secrets`` so the keyring layer is replaced with an
in-memory dict. That mirrors what the real ``keyring`` package does for
the Null/Fail backends, but lets us verify round-trip behavior
deterministically and on CI runners that don't have a Keychain backend
available.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_keyring(monkeypatch):
    """Replace the underlying keyring backend with an in-memory dict.

    Patches ``keyring.get_password`` / ``set_password`` / ``delete_password``
    so every consumer of ``cli_tools_shared.secrets`` (regardless of how it
    was imported) sees the same store. The fixture also pretends a real
    backend is active so ``set_secret`` does not refuse to write.
    """
    store: dict[tuple[str, str], str] = {}

    import keyring

    def _get(service, username):
        return store.get((service, username))

    def _set(service, username, value):
        store[(service, username)] = value

    def _del(service, username):
        if (service, username) not in store:
            from keyring.errors import PasswordDeleteError
            raise PasswordDeleteError("not found")
        del store[(service, username)]

    monkeypatch.setattr(keyring, "get_password", _get)
    monkeypatch.setattr(keyring, "set_password", _set)
    monkeypatch.setattr(keyring, "delete_password", _del)

    # Force the backend-availability check to pass.
    from cli_tools_shared import secrets as secrets_mod
    monkeypatch.setattr(secrets_mod, "is_dummy_keyring", lambda _b: False)
    monkeypatch.setattr(secrets_mod, "keyring_available", lambda: True)
    return store


@pytest.fixture
def xdg_dirs(tmp_path, monkeypatch):
    """Point COPILOT_CONFIG_DIR + COPILOT_CACHE_DIR at a tmp tree."""
    cfg = tmp_path / "config"
    cache = tmp_path / "cache"
    cfg.mkdir()
    cache.mkdir()
    monkeypatch.setenv("COPILOT_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("COPILOT_CACHE_DIR", str(cache))
    # Keep XDG vars cleared so platform-default and override paths are
    # exercised in isolation.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    # Always start with a fresh global config cache.
    from copilot_cli import config as copilot_cfg
    copilot_cfg._reset_config()
    return cfg, cache


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def test_xdg_override_takes_precedence(monkeypatch, tmp_path):
    """COPILOT_CONFIG_DIR wins over XDG_CONFIG_HOME and platform default."""
    monkeypatch.setenv("COPILOT_CONFIG_DIR", str(tmp_path / "explicit"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    from copilot_cli.config import get_config_root
    assert get_config_root() == (tmp_path / "explicit").resolve()


def test_xdg_config_home_used_when_no_override(monkeypatch, tmp_path):
    monkeypatch.delenv("COPILOT_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    if sys.platform == "win32":
        pytest.skip("XDG_CONFIG_HOME is not honored on Windows by design.")

    from copilot_cli.config import get_config_root
    assert get_config_root() == tmp_path / "xdg" / "copilot"


def test_platform_default_when_no_overrides(monkeypatch):
    monkeypatch.delenv("COPILOT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    from copilot_cli.config import get_config_root
    root = get_config_root()
    home = Path.home()
    if sys.platform == "win32":
        # %APPDATA%\copilot
        assert root.name == "copilot"
    else:
        assert root == home / ".config" / "copilot"


def test_cache_dir_resolves_via_override(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_CACHE_DIR", str(tmp_path / "cache"))

    from copilot_cli.config import get_cache_root
    assert get_cache_root() == (tmp_path / "cache").resolve()


# ---------------------------------------------------------------------------
# Profile loading from XDG layout
# ---------------------------------------------------------------------------

def test_default_profile_loaded_from_xdg(xdg_dirs, fake_keyring):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "default.env").write_text(
        "IS_DEFAULT_PROFILE=1\nDATAVERSE_URL=https://default.example/\n"
    )

    from copilot_cli.config import Config
    config = Config()
    assert config.env_file_path == profiles / "default.env"
    assert config.dataverse_url == "https://default.example/"


def test_explicit_profile_argument_wins(xdg_dirs, fake_keyring):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "default.env").write_text(
        "IS_DEFAULT_PROFILE=1\nDATAVERSE_URL=https://default.example/\n"
    )
    (profiles / "staging.env").write_text(
        "IS_DEFAULT_PROFILE=0\nDATAVERSE_URL=https://staging.example/\n"
    )

    from copilot_cli.config import Config
    config = Config(profile="staging")
    assert config.env_file_path == profiles / "staging.env"
    assert config.dataverse_url == "https://staging.example/"


def test_is_default_profile_marker_picks_winner(xdg_dirs, fake_keyring):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "default.env").write_text(
        "IS_DEFAULT_PROFILE=0\nDATAVERSE_URL=https://default.example/\n"
    )
    (profiles / "staging.env").write_text(
        "IS_DEFAULT_PROFILE=1\nDATAVERSE_URL=https://staging.example/\n"
    )

    from copilot_cli.config import Config
    config = Config()
    assert config.env_file_path == profiles / "staging.env"


def test_multiple_default_profiles_raises(xdg_dirs, fake_keyring):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "a.env").write_text("IS_DEFAULT_PROFILE=1\nDATAVERSE_URL=https://a/\n")
    (profiles / "b.env").write_text("IS_DEFAULT_PROFILE=1\nDATAVERSE_URL=https://b/\n")

    from cli_tools_shared.exceptions import ConfigError
    from copilot_cli.config import Config
    with pytest.raises(ConfigError):
        Config()


# ---------------------------------------------------------------------------
# Secret routing through keychain
# ---------------------------------------------------------------------------

def test_sensitive_field_read_from_keyring(xdg_dirs, fake_keyring):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "default.env").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "DATAVERSE_URL=https://default.example/\n"
        "AZURE_TENANT_ID=tenant-id\n"
        "AZURE_CLIENT_ID=client-id\n"
    )
    fake_keyring[("copilot-cli", "default:AZURE_CLIENT_SECRET")] = "super-secret"

    from copilot_cli.config import Config
    config = Config()
    assert config.azure_client_secret == "super-secret"


def test_sensitive_field_write_routes_to_keyring(xdg_dirs, fake_keyring):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "default.env").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "DATAVERSE_URL=https://default.example/\n"
    )

    from copilot_cli.config import Config
    config = Config()
    config._set("AZURE_CLIENT_SECRET", "rotated-secret")

    # Stored in keychain
    assert fake_keyring[("copilot-cli", "default:AZURE_CLIENT_SECRET")] == "rotated-secret"
    # NOT written to .env file
    text = (profiles / "default.env").read_text()
    assert "rotated-secret" not in text


def test_sensitive_field_clear_removes_from_keyring(xdg_dirs, fake_keyring):
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "default.env").write_text(
        "IS_DEFAULT_PROFILE=1\nDATAVERSE_URL=https://default.example/\n"
    )
    fake_keyring[("copilot-cli", "default:AZURE_CLIENT_SECRET")] = "x"

    from copilot_cli.config import Config
    config = Config()
    config._clear("AZURE_CLIENT_SECRET")
    assert ("copilot-cli", "default:AZURE_CLIENT_SECRET") not in fake_keyring


def test_legacy_dotenv_value_used_when_keychain_empty(xdg_dirs, fake_keyring):
    """A user mid-migration may still have AZURE_CLIENT_SECRET in their
    profile .env. The Config class must read it back (via dotenv loading)
    when the keychain has no entry yet, so existing setups keep working
    until ``copilot config migrate`` rotates the secret into the keychain.
    """
    cfg_root, _ = xdg_dirs
    profiles = cfg_root / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "default.env").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "DATAVERSE_URL=https://default.example/\n"
        "AZURE_CLIENT_SECRET=legacy-from-dotenv\n"
    )

    from copilot_cli.config import Config
    config = Config()
    assert config.azure_client_secret == "legacy-from-dotenv"


# ---------------------------------------------------------------------------
# Migration idempotency
# ---------------------------------------------------------------------------

def test_migrate_dry_run_makes_no_changes(xdg_dirs, fake_keyring, tmp_path, monkeypatch):
    cfg_root, _ = xdg_dirs
    legacy_dir = tmp_path / "legacy_pkg"
    legacy_dir.mkdir()
    (legacy_dir / ".env").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "DATAVERSE_URL=https://legacy.example/\n"
        "AZURE_CLIENT_SECRET=old-secret\n"
    )

    # Tell the config module that "legacy_pkg" is the package source dir.
    from copilot_cli import config as copilot_cfg
    monkeypatch.setattr(copilot_cfg, "resolve_tool_dir", lambda _name: legacy_dir)

    from copilot_cli.commands.config import config_migrate
    # dry-run: inspect that nothing got written to the keyring.
    config_migrate(yes=False, skip_secrets=False, dry_run=True)
    assert ("copilot-cli", "default:AZURE_CLIENT_SECRET") not in fake_keyring
    # No new profile file was created.
    assert not (cfg_root / "profiles" / "default.env").exists()


def test_migrate_runs_idempotent(xdg_dirs, fake_keyring, tmp_path, monkeypatch):
    cfg_root, _ = xdg_dirs
    legacy_dir = tmp_path / "legacy_pkg"
    legacy_dir.mkdir()
    (legacy_dir / ".env").write_text(
        "IS_DEFAULT_PROFILE=1\n"
        "DATAVERSE_URL=https://legacy.example/\n"
        "AZURE_TENANT_ID=tenant-x\n"
        "AZURE_CLIENT_SECRET=old-secret\n"
    )

    from copilot_cli import config as copilot_cfg
    monkeypatch.setattr(copilot_cfg, "resolve_tool_dir", lambda _name: legacy_dir)

    from copilot_cli.commands.config import config_migrate
    config_migrate(yes=True, skip_secrets=False, dry_run=False)

    new_default = cfg_root / "profiles" / "default.env"
    assert new_default.exists()
    written = new_default.read_text()
    assert "DATAVERSE_URL=https://legacy.example/" in written
    assert "AZURE_TENANT_ID=tenant-x" in written
    # Secret moved to keychain, not the .env file.
    assert "old-secret" not in written
    assert fake_keyring[("copilot-cli", "default:AZURE_CLIENT_SECRET")] == "old-secret"

    # Marker exists.
    assert (legacy_dir / ".env.migrated").exists()

    # Re-running with the same legacy file is a clean no-op: marker present
    # AND target exists ⇒ migrate skips. The keychain is left untouched
    # (we don't re-prompt for already-migrated secrets).
    secret_key = ("copilot-cli", "default:AZURE_CLIENT_SECRET")
    assert fake_keyring[secret_key] == "old-secret"
    config_migrate(yes=True, skip_secrets=False, dry_run=False)
    # Profile file unchanged on disk.
    assert (cfg_root / "profiles" / "default.env").read_text() == written
    # Removing the marker re-enables migration on the next run.
    (legacy_dir / ".env.migrated").unlink()
    fake_keyring[secret_key] = "should-be-overwritten"
    config_migrate(yes=True, skip_secrets=False, dry_run=False)
    assert fake_keyring[secret_key] == "old-secret"


def test_migrate_no_legacy_files_is_noop(xdg_dirs, fake_keyring, tmp_path, monkeypatch):
    legacy_dir = tmp_path / "legacy_pkg"
    legacy_dir.mkdir()  # exists but empty

    from copilot_cli import config as copilot_cfg
    monkeypatch.setattr(copilot_cfg, "resolve_tool_dir", lambda _name: legacy_dir)

    from copilot_cli.commands.config import config_migrate
    # Should not raise even when no legacy files are present.
    config_migrate(yes=False, skip_secrets=False, dry_run=False)
    assert fake_keyring == {}


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
