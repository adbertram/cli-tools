"""Runtime credential enforcement for CLI command groups.

Wraps Typer's add_typer() to inject a callback that checks COMMAND_CREDENTIALS
before any command runs. Missing credentials produce a clear message telling
the user to run `auth login` instead of a cryptic error deep inside the command.

Usage in main.py:
    from cli_tools_shared.command_registry import register_commands
    from .config import get_config

    register_commands(
        app,
        get_config,
        accounts, name="accounts", help="Manage accounts",
    )

This replaces:
    app.add_typer(accounts.app, name="accounts", help="Manage accounts")
"""

import sys
import logging
from typing import Callable, Optional

import typer

from .auth_verifier import AuthVerifier
from .credentials import CredentialType

logger = logging.getLogger("cli_tools.command_registry")

# Maps credential type string names (from COMMAND_CREDENTIALS) to CredentialType enum
_CRED_TYPE_MAP = {ct.value: ct for ct in CredentialType}


def _check_credentials(
    config,
    cred_type_strings: list[str],
    cli_name: str,
) -> None:
    """Check that all required credential types are satisfied.

    For OAuth types, attempts automatic token refresh before failing.
    For browser_session, checks saved browser storage when AUTH_STORAGE_KEY is configured,
    otherwise performs a live headless check.
    For API types, checks that required fields are present in config.

    Args:
        config: BaseConfig instance (already loaded).
        cred_type_strings: List of credential type strings from COMMAND_CREDENTIALS.
        cli_name: CLI tool name for error messages.

    Raises:
        typer.Exit: If any credential type is not satisfied.
    """
    missing = []

    for type_str in cred_type_strings:
        cred_type = _CRED_TYPE_MAP.get(type_str)
        if cred_type is None:
            logger.warning("Unknown credential type '%s', skipping check", type_str)
            continue

        if cred_type == CredentialType.NO_AUTH:
            continue

        if cred_type in AuthVerifier.OAUTH_TYPES:
            if not getattr(config, "OAUTH_TOKEN_EXPIRES", True):
                fields = getattr(
                    config,
                    "OAUTH_STATIC_REQUIRED_FIELDS",
                    ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN"),
                )
                missing_fields = [field for field in fields if not config._get(field)]
                if missing_fields:
                    missing.append(f"  - {cred_type.value}: missing {', '.join(missing_fields)}")
                continue

            # Check for access token, attempt refresh if expired
            if not config.access_token:
                missing.append(f"  - {cred_type.value}: no access token")
                continue
            from .token_manager import TokenManager
            tm = TokenManager(config)
            if tm.is_expired():
                try:
                    tm.force_refresh()
                    logger.debug("Auto-refreshed expired OAuth token")
                except Exception:
                    missing.append(f"  - {cred_type.value}: token expired and refresh failed")

        elif cred_type == CredentialType.BROWSER_SESSION:
            # Single source of truth: the persistent Chromium profile on
            # disk. ``config.has_saved_session()`` is the only gate. The
            # previous ``AUTH_STORAGE_KEY`` / ``AUTH_COOKIE_PATTERNS``
            # offline snapshot checks are gone. CLIs that need a stricter live
            # check (one that proves cookies are still valid server-side)
            # MUST perform it themselves at the point of use — that is
            # not the gate's job.
            if not config.has_saved_session():
                missing.append(f"  - {cred_type.value}: no saved browser session")

        else:
            # API_KEY, PERSONAL_ACCESS_TOKEN, USERNAME_PASSWORD, CUSTOM
            for field in cred_type.required_fields:
                if not config._get(field):
                    missing.append(f"  - {cred_type.value}: missing {field}")
                    break  # One missing field is enough to flag this type

    if missing:
        typer.echo(
            f"Authentication required. Missing credentials:\n"
            + "\n".join(missing)
            + f"\n\nRun '{cli_name} auth login' to authenticate.",
            err=True,
        )
        raise typer.Exit(1)


def register_commands(
    app: typer.Typer,
    get_config: Callable,
    command_module,
    *,
    name: str,
    help: str,
    cli_name: Optional[str] = None,
) -> None:
    """Register a command group with runtime credential checking.

    Wraps app.add_typer() and installs a Typer callback on the command group
    that checks COMMAND_CREDENTIALS before any command executes.

    Args:
        app: The root Typer app.
        get_config: Zero-arg callable that returns a BaseConfig instance.
        command_module: The command module (must have .app and .COMMAND_CREDENTIALS).
        name: Subcommand group name (e.g., "accounts").
        help: Help text for the group.
        cli_name: CLI tool name for error messages. If None, uses app.info.name.
    """
    sub_app = command_module.app
    cred_map = getattr(command_module, "COMMAND_CREDENTIALS", None)

    if cred_map is None:
        # No credential mapping — register without enforcement
        app.add_typer(sub_app, name=name, help=help)
        return

    # Resolve CLI name for error messages
    resolved_cli_name = cli_name or (app.info.name if app.info.name else name)

    # Store the original callback if one exists
    original_callback = sub_app.registered_callback
    original_callback_fn = None
    if original_callback and original_callback.callback:
        original_callback_fn = original_callback.callback

    @sub_app.callback(invoke_without_command=True)
    def _credential_gate(ctx: typer.Context):
        """Check credentials before running any command in this group."""
        invoked = ctx.invoked_subcommand
        if invoked is None:
            # No subcommand — show help (default Typer behavior)
            if original_callback_fn:
                original_callback_fn(ctx)
            else:
                typer.echo(ctx.get_help())
                raise typer.Exit()
            return

        # Skip credential check when --help is requested on a subcommand
        if "--help" in sys.argv or "-h" in sys.argv:
            return

        cred_types = cred_map.get(invoked)
        if not cred_types:
            # Command not in credential map — allow through
            return

        try:
            config = get_config()
        except Exception as e:
            logger.debug("Config initialization failed: %s", e)
            # Config can't load — credential check can't run, let the command
            # fail naturally with its own error handling
            return

        _check_credentials(config, cred_types, resolved_cli_name)

    app.add_typer(sub_app, name=name, help=help)
