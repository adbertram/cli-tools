"""Authentication commands for Mailchimp CLI."""
from __future__ import annotations

import sys
from typing import Optional

import typer
from dotenv import dotenv_values

from cli_tools_shared.auth_commands import (
    _bootstrap_profile_if_missing,
    create_auth_app,
)
from cli_tools_shared.output import command, print_error, print_info, print_success

from ..config import Config, get_config


_LOGIN_CLEAR_FIELDS = (
    "MAILCHIMP_API_KEY",
    "MAILCHIMP_ACCESS_TOKEN",
    "MAILCHIMP_REFRESH_TOKEN",
    "MAILCHIMP_TOKEN_EXPIRES_AT",
)


app = create_auth_app(
    get_config_fn=get_config,
    tool_name="mailchimp",
)
app.registered_commands = [
    command_info
    for command_info in app.registered_commands
    if command_info.name != "login"
]


def _stored_profile_value(config: Config, field_name: str) -> Optional[str]:
    """Read the raw stored profile value for a Mailchimp auth field."""
    if not config.env_file_path.exists():
        return None
    value = dotenv_values(config.env_file_path).get(field_name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _clear_persisted_mailchimp_login_state(config: Config) -> bool:
    """Clear only fields that are actually stored for this profile."""
    cleared = False
    for field_name in _LOGIN_CLEAR_FIELDS:
        if not _stored_profile_value(config, field_name):
            continue
        config._clear(field_name)
        cleared = True
    return cleared


def _normalize_api_key(api_key: Optional[str]) -> Optional[str]:
    """Strip CLI-provided API keys and reject empty values."""
    if api_key is None:
        return None
    normalized = api_key.strip()
    if normalized:
        return normalized
    print_error("Mailchimp API key cannot be empty")
    raise typer.Exit(1)


def _read_api_key_from_stdin() -> str:
    """Read a replacement API key from stdin without clearing saved state first."""
    print_info("Enter Mailchimp API key")
    return sys.stdin.readline()


@app.command("login")
@command
def auth_login(
    profile: Optional[str] = typer.Option(
        None, "--profile", "-p", help="Profile name to save credentials to"
    ),
    force: bool = typer.Option(
        False, "--force", "-F", help="Clear existing credentials and re-authenticate"
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", "-k", help="Mailchimp API key to save without prompting"
    ),
):
    """Configure Mailchimp API credentials."""
    effective_profile = _bootstrap_profile_if_missing(get_config, profile, "mailchimp")
    config = get_config(profile=effective_profile)
    api_key = _normalize_api_key(api_key)

    if api_key is None and config.api_key and not force:
        print_success("Credentials already configured")
        return

    if api_key is None:
        instructions = getattr(config, "LOGIN_INSTRUCTIONS", None)
        if instructions:
            print_info(instructions)
        prompted_value = _read_api_key_from_stdin()
        api_key = _normalize_api_key(prompted_value)
        assert api_key is not None

    if force and _clear_persisted_mailchimp_login_state(config):
        print_info("Existing credentials cleared")

    config._set("MAILCHIMP_API_KEY", api_key)
    print_success("Credentials saved successfully")
