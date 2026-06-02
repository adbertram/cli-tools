import sys
import types

import pytest

from copilot_cli import client as copilot_client
from copilot_cli.config import Config, _reset_config
from copilot_cli.commands.mcp import _acquire_mcp_token


def _write_profile(path, *, active, dataverse_url):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"ACTIVE={'true' if active else 'false'}",
                f"DATAVERSE_URL={dataverse_url}",
            ]
        )
        + "\n"
    )


def _setup_profiles_dir(tmp_path, monkeypatch):
    """Point cli-tools user data at tmp_path and return the profiles dir."""
    data_home = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.delenv("COPILOT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("COPILOT_CACHE_DIR", raising=False)
    profiles = data_home / "cli-tools" / "copilot" / "authentication_profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    _reset_config()
    return profiles


def test_config_uses_active_profile_and_ignores_profile_environment_overrides(tmp_path, monkeypatch):
    """The active-profile selection must not be diverted by stray env vars
    such as ``COPILOT_CLI_TOOL_PROFILE`` or ``CLI_TOOLS_PROFILE`` — only an
    explicit ``profile`` argument or the ``ACTIVE=true`` marker
    should switch profiles. This is the core invariant the public CLI
    relies on for predictable credential lookup.
    """
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)

    active_profile = profiles / "active" / ".env"
    env_override_profile = profiles / "env_override" / ".env"
    cli_override_profile = profiles / "cli_override" / ".env"

    _write_profile(active_profile, active=True, dataverse_url="https://active.example.crm.dynamics.com")
    _write_profile(env_override_profile, active=False, dataverse_url="https://env.example.crm.dynamics.com")
    _write_profile(cli_override_profile, active=False, dataverse_url="https://cli.example.crm.dynamics.com")

    monkeypatch.setenv("COPILOT_CLI_TOOL_PROFILE", "env_override")
    monkeypatch.setenv("CLI_TOOLS_PROFILE", "cli_override")

    config = Config()

    assert config.env_file_path == active_profile
    assert config.dataverse_url == "https://active.example.crm.dynamics.com"


def test_config_allows_explicit_profile_argument(tmp_path, monkeypatch):
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)

    active_profile = profiles / "active" / ".env"
    explicit_profile = profiles / "explicit" / ".env"

    _write_profile(active_profile, active=True, dataverse_url="https://active.example.crm.dynamics.com")
    _write_profile(explicit_profile, active=False, dataverse_url="https://explicit.example.crm.dynamics.com")

    monkeypatch.setenv("COPILOT_CLI_TOOL_PROFILE", "active")
    monkeypatch.setenv("CLI_TOOLS_PROFILE", "active")

    config = Config(profile="explicit")

    assert config.env_file_path == explicit_profile
    assert config.dataverse_url == "https://explicit.example.crm.dynamics.com"


def test_expected_azure_cli_user_does_not_hide_saved_credentials(tmp_path, monkeypatch):
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)

    profile = profiles / "different_user" / ".env"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "\n".join(
            [
                "ACTIVE=true",
                "DATAVERSE_URL=https://different-user.example.crm.dynamics.com",
                "AZURE_CLI_EXPECTED_USER=different@example.com",
            ]
        )
        + "\n"
    )

    config = Config()

    assert config.has_credentials() is True


def test_mcp_token_acquisition_uses_only_active_profile(tmp_path, monkeypatch):
    """MCP token acquisition must read AZURE_CLIENT_ID from the active
    profile only — never silently fall back to a different profile that
    happens to have AZURE_CLIENT_SECRET set. This guards against the
    cross-profile credential-leak class of bugs.
    """
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)

    active_profile = profiles / "active" / ".env"
    old_service_principal_profile = profiles / "legacy_tenant_service_principal" / ".env"

    _write_profile(active_profile, active=True, dataverse_url="https://active.example.crm.dynamics.com")
    old_service_principal_profile.parent.mkdir(parents=True, exist_ok=True)
    old_service_principal_profile.write_text(
        "\n".join(
            [
                "ACTIVE=false",
                "DATAVERSE_URL=https://sp.example.crm.dynamics.com",
                "AZURE_CLIENT_ID=service-principal-client-id",
                "AZURE_CLIENT_SECRET=service-principal-secret",
            ]
        )
        + "\n"
    )

    _reset_config()

    class FailingConfidentialClientApplication:
        def __init__(self, **_kwargs):
            raise AssertionError("MCP token acquisition must not load a fallback profile")

    fake_msal = types.SimpleNamespace(
        ConfidentialClientApplication=FailingConfidentialClientApplication,
        PublicClientApplication=FailingConfidentialClientApplication,
    )
    monkeypatch.setitem(sys.modules, "msal", fake_msal)

    with pytest.raises(RuntimeError, match="No AZURE_CLIENT_ID found"):
        _acquire_mcp_token(
            "https://login.microsoftonline.com/tenant-id",
            ["api://resource-id/mcp.tools"],
        )


def test_general_access_token_uses_azure_cli_even_when_service_principal_fields_exist(monkeypatch):
    """Normal CLI commands must keep using Azure CLI delegated auth.

    Profiles can carry client-secret fields for specific command groups, but
    the shared Dataverse/Graph token path must not silently switch the whole
    CLI onto service-principal auth.
    """

    class MixedAuthConfig:
        def has_service_principal_auth(self):
            return True

        def has_cli_auth(self):
            return True

    seen = {}

    def fake_get_config():
        return MixedAuthConfig()

    def fake_azure_cli(resource):
        seen["azure_cli"] = resource
        return "azure-cli-token"

    def fake_service_principal(resource):
        seen["service_principal"] = resource
        return "service-principal-token"

    monkeypatch.setattr(copilot_client, "get_config", fake_get_config)
    monkeypatch.setattr(copilot_client, "get_access_token_from_azure_cli", fake_azure_cli)
    monkeypatch.setattr(copilot_client, "_get_access_token_from_service_principal", fake_service_principal)

    token = copilot_client.get_access_token("https://graph.microsoft.com")

    assert token == "azure-cli-token"
    assert seen == {"azure_cli": "https://graph.microsoft.com"}


def test_config_prefers_azure_cli_auth_method_for_mixed_profiles(tmp_path, monkeypatch):
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)

    profile = profiles / "default" / ".env"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "\n".join(
            [
                "ACTIVE=true",
                "DATAVERSE_URL=https://delegated.example.crm.dynamics.com",
            ]
        )
        + "\n"
    )

    monkeypatch.setattr(Config, "has_service_principal_auth", lambda self: True)

    config = Config()

    assert config.get_auth_method() == "azure_cli"
