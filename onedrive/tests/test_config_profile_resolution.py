"""Regression tests for OneDrive profile routing."""

import sys
from pathlib import Path

from cli_tools_shared.command_registry import _resolve_runtime_profile_context
from cli_tools_shared.config import get_profiles_base_dir, implicit_profile_auth_type


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_active_profile_resolves_without_explicit_profile_for_custom_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))

    profiles_base = get_profiles_base_dir("onedrive")
    profile_env = profiles_base / "default" / ".env"
    profile_env.parent.mkdir(parents=True, exist_ok=True)
    profile_env.write_text("ACTIVE=true\nAUTH_METHOD=az_cli\n")

    from onedrive_cli import config as onedrive_config

    onedrive_config._config = None
    profile_name, profile_auth_type = _resolve_runtime_profile_context(
        onedrive_config.get_config,
        "onedrive",
        None,
        ["custom"],
    )

    assert profile_name == "default"
    assert profile_auth_type == implicit_profile_auth_type()
