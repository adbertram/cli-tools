from pathlib import Path
import subprocess

import pytest

import cli_tools_shared.config as config_module
from cli_tools_shared.config import get_profiles_base_dir, validate_auth_profile_secret_placeholders
from cli_tools_shared.exceptions import ConfigError


def _write_profile(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_validate_auth_profile_secret_placeholders_accepts_existing_secrets(monkeypatch):
    tool_name = "exampletool"
    default_profile = get_profiles_base_dir(tool_name) / "default" / ".env"
    staging_profile = get_profiles_base_dir(tool_name) / "staging" / ".env"
    _write_profile(default_profile, "ACTIVE=true\nAPI_KEY=secret://exampletool-api-key\n")
    _write_profile(staging_profile, "ACTIVE=false\nPASSWORD=secret://exampletool-staging-password\n")

    checked = []

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        checked.append((command, secret_name, secret_value))
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    validate_auth_profile_secret_placeholders(tool_name)

    assert checked == [
        ("has", "exampletool-api-key", None),
        ("has", "exampletool-staging-password", None),
    ]


def test_validate_auth_profile_secret_placeholders_reports_every_missing_secret(monkeypatch):
    tool_name = "exampletool"
    default_profile = get_profiles_base_dir(tool_name) / "default" / ".env"
    staging_profile = get_profiles_base_dir(tool_name) / "staging" / ".env"
    _write_profile(default_profile, "ACTIVE=true\nAPI_KEY=secret://exampletool-api-key\n")
    _write_profile(staging_profile, "ACTIVE=false\nPASSWORD=secret://exampletool-staging-password\n")

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        assert command == "has"
        return subprocess.CompletedProcess([], 1, stdout="", stderr="missing")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    with pytest.raises(ConfigError) as excinfo:
        validate_auth_profile_secret_placeholders(tool_name)

    message = str(excinfo.value)
    assert "Missing CLI-tools secrets referenced by authentication profiles:" in message
    assert str(default_profile) in message
    assert "API_KEY" in message
    assert "exampletool-api-key" in message
    assert str(staging_profile) in message
    assert "PASSWORD" in message
    assert "exampletool-staging-password" in message


def test_validate_auth_profile_secret_placeholders_rejects_invalid_placeholder(monkeypatch):
    tool_name = "exampletool"
    default_profile = get_profiles_base_dir(tool_name) / "default" / ".env"
    _write_profile(default_profile, "ACTIVE=true\nAPI_KEY=secret://\n")

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        raise AssertionError("Secret manager should not run for an invalid placeholder")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)

    with pytest.raises(ConfigError) as excinfo:
        validate_auth_profile_secret_placeholders(tool_name)

    message = str(excinfo.value)
    assert str(default_profile) in message
    assert "API_KEY" in message
    assert "Invalid secret placeholder" in message


def test_validate_auth_profile_secret_placeholders_skips_missing_optional_secret(monkeypatch):
    tool_name = "exampletool"
    default_profile = get_profiles_base_dir(tool_name) / "default" / ".env"
    _write_profile(
        default_profile,
        "ACTIVE=true\n"
        "USERNAME=secret://exampletool-username\n"
        "PASSWORD=secret://exampletool-password\n"
        "OPTIONAL_TOKEN=secret://exampletool-optional-token\n",
    )

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        assert command == "has"
        return subprocess.CompletedProcess(
            [],
            0 if secret_name in {"exampletool-username", "exampletool-password"} else 1,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)
    monkeypatch.setattr(
        config_module,
        "_optional_secret_fields_for_tool",
        lambda _tool_name: {"OPTIONAL_TOKEN"},
    )

    validate_auth_profile_secret_placeholders(tool_name)
