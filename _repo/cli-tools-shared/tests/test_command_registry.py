"""Unit tests for the command-registry credential gate.

After the persistent-profile refactor, the BROWSER_SESSION gate uses ONLY
``config.has_saved_session()`` — the single source of truth shared with
``auth status``. The previous ``AUTH_STORAGE_KEY`` / ``AUTH_COOKIE_PATTERNS``
offline snapshot checks have been removed. CLIs that need a stricter live
check perform it at the point of use, not in the gate.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from cli_tools_shared.command_registry import (
    _check_credentials,
    _resolve_runtime_profile_context,
    register_commands,
    register_root_commands,
)
from cli_tools_shared.config import BaseConfig, get_profiles_base_dir
from cli_tools_shared.credentials import CredentialType


def _config_with_session(has_session: bool) -> MagicMock:
    """Build a mock config whose ``has_saved_session()`` returns ``has_session``."""
    config = MagicMock()
    config.has_saved_session.return_value = has_session
    config.get_browser.return_value = MagicMock()
    return config


def test_static_oauth_gate_uses_required_fields_without_token_refresh():
    config = MagicMock()
    config.OAUTH_TOKEN_EXPIRES = False
    config.OAUTH_STATIC_REQUIRED_FIELDS = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN")
    config._get.side_effect = lambda field: {
        "CLIENT_ID": "consumer-key",
        "CLIENT_SECRET": "consumer-secret",
        "ACCESS_TOKEN": "token-value",
        "REFRESH_TOKEN": "token-secret",
    }.get(field)

    with patch("cli_tools_shared.token_manager.TokenManager") as MockTM:
        _check_credentials(config, ["oauth"], "tool")

    MockTM.assert_not_called()


def test_static_oauth_gate_fails_when_required_field_missing():
    config = MagicMock()
    config.OAUTH_TOKEN_EXPIRES = False
    config.OAUTH_STATIC_REQUIRED_FIELDS = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN")
    config._get.side_effect = lambda field: {
        "CLIENT_ID": "consumer-key",
        "CLIENT_SECRET": "consumer-secret",
        "ACCESS_TOKEN": "token-value",
        "REFRESH_TOKEN": "",
    }.get(field)

    with pytest.raises(typer.Exit):
        _check_credentials(config, ["oauth"], "tool")


def test_browser_session_gate_passes_when_config_has_saved_session():
    """``config.has_saved_session()`` is the only signal the gate consults."""
    config = _config_with_session(True)

    _check_credentials(config, ["browser_session"], "tool")

    config.has_saved_session.assert_called_once_with()


def test_browser_session_gate_fails_when_config_has_no_saved_session():
    config = _config_with_session(False)

    with pytest.raises(typer.Exit):
        _check_credentials(config, ["browser_session"], "tool")

    config.has_saved_session.assert_called_once_with()


def test_browser_session_gate_does_not_call_live_is_authenticated():
    """The gate must NEVER do a live browser navigation. That's the bug the
    refactor fixed: ``auth status`` (filesystem-only) disagreeing with the
    gate (which used to live-navigate).
    """
    config = _config_with_session(True)
    browser = config.get_browser.return_value

    _check_credentials(config, ["browser_session"], "tool")

    browser.is_authenticated.assert_not_called()
    browser.has_session.assert_not_called()


def test_browser_session_gate_does_not_consider_browser_class_attributes():
    """Old contract: gate looked at ``AUTH_STORAGE_KEY`` / ``AUTH_COOKIE_PATTERNS``
    on the browser subclass to do an offline disk snapshot check. New contract:
    those class attrs no longer affect the gate — only the persistent profile
    on disk does.
    """
    config = _config_with_session(False)
    browser = config.get_browser.return_value
    # Declare BOTH hooks — these used to bypass ``has_saved_session()``.
    browser.AUTH_STORAGE_KEY = "token"
    browser.AUTH_COOKIE_PATTERNS = [r"^session$"]

    # Even though the browser subclass declares both hooks, the gate fails
    # because ``has_saved_session()`` is False. The hooks have no effect.
    with pytest.raises(typer.Exit):
        _check_credentials(config, ["browser_session"], "tool")


class MultiProfileConfig(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.API_KEY, CredentialType.BROWSER_SESSION]
    PROFILE_AUTH_TYPE_FIELD = "AUTH_TYPE"
    PROFILE_AUTH_TYPES = {
        "api_key": [],
        "browser_session": [],
    }


def _write_profile(path, *, auth_type: str, active: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"ACTIVE={'true' if active else 'false'}\nAUTH_TYPE={auth_type}\n"
    )


def _multi_profile_get_config() -> MultiProfileConfig:
    raise AssertionError("profile context resolution must not instantiate config")


def test_command_profile_auth_type_comes_from_command_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    profiles_base = get_profiles_base_dir("tool")
    _write_profile(profiles_base / "api" / ".env", auth_type="api_key")
    _write_profile(
        profiles_base / "browser" / ".env",
        auth_type="browser_session",
    )

    profile_name, profile_auth_type = _resolve_runtime_profile_context(
        _multi_profile_get_config,
        "tool",
        None,
        ["api_key"],
    )

    assert profile_name == "api"
    assert profile_auth_type == "api_key"


def test_explicit_profile_must_match_command_profile_auth_type(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    profiles_base = get_profiles_base_dir("tool")
    _write_profile(profiles_base / "api" / ".env", auth_type="api_key")
    _write_profile(
        profiles_base / "browser" / ".env",
        auth_type="browser_session",
    )

    with pytest.raises(typer.BadParameter, match="requires auth type 'api_key'"):
        _resolve_runtime_profile_context(
            _multi_profile_get_config,
            "tool",
            "browser",
            ["api_key"],
        )


def test_explicit_profile_is_allowed_when_command_auth_type_is_ambiguous(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    profiles_base = get_profiles_base_dir("tool")
    _write_profile(profiles_base / "api" / ".env", auth_type="api_key")
    _write_profile(
        profiles_base / "browser" / ".env",
        auth_type="browser_session",
    )

    profile_name, profile_auth_type = _resolve_runtime_profile_context(
        _multi_profile_get_config,
        "tool",
        "browser",
        ["custom"],
    )

    assert profile_name == "browser"
    assert profile_auth_type == "browser_session"


def test_multi_profile_auth_type_command_without_mapping_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    profiles_base = get_profiles_base_dir("tool")
    _write_profile(profiles_base / "api" / ".env", auth_type="api_key")
    _write_profile(
        profiles_base / "browser" / ".env",
        auth_type="browser_session",
    )

    with pytest.raises(typer.BadParameter, match="does not identify one profile auth type"):
        _resolve_runtime_profile_context(
            _multi_profile_get_config,
            "tool",
            None,
            ["custom"],
        )


def test_registered_command_accepts_profile_option_after_leaf_command():
    calls = []
    ran = []

    class SingleProfileConfig:
        CREDENTIAL_TYPES = [CredentialType.API_KEY]

        def _get(self, name):
            return {"API_KEY": "saved-key"}.get(name)

    def get_config(profile=None) -> SingleProfileConfig:
        calls.append(profile)
        return SingleProfileConfig()

    command_app = typer.Typer()

    @command_app.command("list")
    def list_items(limit: int = typer.Option(1, "--limit", "-l")):
        ran.append(limit)
        typer.echo("ok")

    root = typer.Typer()
    register_commands(
        root,
        get_config,
        SimpleNamespace(
            app=command_app,
            COMMAND_CREDENTIALS={"list": ["api_key"]},
        ),
        name="items",
        help="Manage items",
        cli_name="tool",
    )

    result = CliRunner().invoke(
        root,
        ["items", "list", "--limit", "3", "--profile", "staging"],
    )

    assert result.exit_code == 0, result.output
    assert "ok" in result.output
    assert calls == ["staging"]
    assert ran == [3]


def test_registered_group_help_exposes_profile_option():
    command_app = typer.Typer()

    @command_app.command("list")
    def list_items(limit: int = typer.Option(1, "--limit", "-l")):
        typer.echo(limit)

    root = typer.Typer()
    register_commands(
        root,
        lambda profile=None: None,
        SimpleNamespace(
            app=command_app,
            COMMAND_CREDENTIALS={"list": ["api_key"]},
        ),
        name="items",
        help="Manage items",
        cli_name="tool",
    )

    result = CliRunner().invoke(root, ["items", "--help"])

    assert result.exit_code == 0, result.output
    assert "--profile" in result.output


def test_registered_root_commands_enforce_credentials_and_expose_profile_option():
    calls = []
    ran = []

    class SingleProfileConfig:
        CREDENTIAL_TYPES = [CredentialType.API_KEY]

        def _get(self, name):
            return {"API_KEY": "saved-key"}.get(name)

    def get_config(profile=None) -> SingleProfileConfig:
        calls.append(profile)
        return SingleProfileConfig()

    command_app = typer.Typer()

    @command_app.command("import")
    def import_media():
        ran.append("import")
        typer.echo("ok")

    root = typer.Typer()
    register_root_commands(
        root,
        get_config,
        SimpleNamespace(
            app=command_app,
            COMMAND_CREDENTIALS={"import": ["api_key"]},
        ),
        cli_name="tool",
    )

    help_result = CliRunner().invoke(root, ["import", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "--profile" in help_result.output

    result = CliRunner().invoke(root, ["import", "--profile", "staging"])

    assert result.exit_code == 0, result.output
    assert "ok" in result.output
    assert calls == ["staging"]
    assert ran == ["import"]


def test_registered_group_accepts_profile_option_before_leaf_command():
    calls = []
    ran = []

    class SingleProfileConfig:
        CREDENTIAL_TYPES = [CredentialType.API_KEY]

        def _get(self, name):
            return {"API_KEY": "saved-key"}.get(name)

    def get_config(profile=None) -> SingleProfileConfig:
        calls.append(profile)
        return SingleProfileConfig()

    command_app = typer.Typer()

    @command_app.command("list")
    def list_items(limit: int = typer.Option(1, "--limit", "-l")):
        ran.append(limit)
        typer.echo("ok")

    root = typer.Typer()
    register_commands(
        root,
        get_config,
        SimpleNamespace(
            app=command_app,
            COMMAND_CREDENTIALS={"list": ["api_key"]},
        ),
        name="items",
        help="Manage items",
        cli_name="tool",
    )

    result = CliRunner().invoke(
        root,
        ["items", "--profile", "staging", "list", "--limit", "3"],
    )

    assert result.exit_code == 0, result.output
    assert "ok" in result.output
    assert calls == ["staging"]
    assert ran == [3]


def test_help_bypasses_ambiguous_profile_auth_type_gate(monkeypatch):
    class MultiProfileConfig:
        CREDENTIAL_TYPES = [CredentialType.CUSTOM]
        PROFILE_AUTH_TYPE_FIELD = "AUTH_TYPE"
        PROFILE_AUTH_TYPES = {
            "az_cli": [],
            "msal_device_code": [],
        }

        def _get(self, _name):
            return None

    def get_config(profile=None) -> MultiProfileConfig:
        return MultiProfileConfig()

    command_app = typer.Typer()

    @command_app.command("list")
    def list_items():
        typer.echo("ok")

    root = typer.Typer()
    register_commands(
        root,
        get_config,
        SimpleNamespace(
            app=command_app,
            COMMAND_CREDENTIALS={"list": ["custom"]},
        ),
        name="items",
        help="Manage items",
        cli_name="tool",
    )

    runner = CliRunner()
    original_argv = sys.argv[:]
    monkeypatch.setattr(sys, "argv", ["tool", "items", "list", "--help"])
    try:
        result = runner.invoke(root, ["items", "list", "--help"])
    finally:
        monkeypatch.setattr(sys, "argv", original_argv)

    assert result.exit_code == 0, result.output
    assert "--profile" in result.output
