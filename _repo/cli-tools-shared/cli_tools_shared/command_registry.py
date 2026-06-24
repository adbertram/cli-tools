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

import logging
import functools
import inspect
import sys
from typing import Callable, Optional

import typer

from .auth_verifier import AuthVerifier
from .config import (
    get_runtime_profile_resolution,
    get_profile_auth_settings,
    implicit_profile_auth_type,
    reset_runtime_profile_resolution,
    set_runtime_profile_resolution,
)
from .credentials import CredentialType
from .profiles import ProfileStore, list_profiles

logger = logging.getLogger("cli_tools.command_registry")

# Maps credential type string names (from COMMAND_CREDENTIALS) to CredentialType enum
_CRED_TYPE_MAP = {ct.value: ct for ct in CredentialType}


def _get_config_class(get_config_fn):
    annotations = getattr(get_config_fn, "__annotations__", {}) or {}
    config_cls = annotations.get("return")
    if config_cls is not None:
        return config_cls
    config_cls = getattr(get_config_fn, "__globals__", {}).get("Config")
    if config_cls is not None:
        return config_cls
    for cell in getattr(get_config_fn, "__closure__", ()) or ():
        value = cell.cell_contents
        if isinstance(value, type) and hasattr(value, "CREDENTIAL_TYPES"):
            return value
    return None


def _profile_store_for_command(get_config_fn, config_cls, cli_name: str) -> ProfileStore:
    tool_name = cli_name.replace("-cli", "")
    profile_auth_settings = get_profile_auth_settings(config_cls) if config_cls is not None else None
    tool_dir = None
    if config_cls is not None and getattr(config_cls, "DIST_NAME", None):
        from .config import resolve_tool_dir

        tool_dir = resolve_tool_dir(config_cls.DIST_NAME)
        tool_name = tool_dir.name
    return ProfileStore(tool_name, tool_dir=tool_dir, profile_auth_settings=profile_auth_settings)


def _command_profile_auth_type(
    profile_auth_settings,
    cred_type_strings: list[str],
    *,
    require_unambiguous: bool = True,
) -> Optional[str]:
    if all(type_str == CredentialType.NO_AUTH.value for type_str in cred_type_strings):
        return None

    if profile_auth_settings is None:
        return implicit_profile_auth_type()

    _auth_type_field, auth_types = profile_auth_settings
    matching_auth_types = [
        type_str for type_str in cred_type_strings if type_str in auth_types
    ]
    if len(matching_auth_types) == 1:
        return matching_auth_types[0]
    if len(matching_auth_types) > 1:
        raise typer.BadParameter(
            "This command declares multiple profile auth types: "
            f"{', '.join(matching_auth_types)}."
        )
    if len(auth_types) == 1:
        return next(iter(auth_types))
    if not require_unambiguous:
        return None
    raise typer.BadParameter(
        "This command requires an explicit --profile because its COMMAND_CREDENTIALS "
        "entry does not identify one profile auth type."
    )


def _active_profile_name_for_auth_type(
    get_config_fn,
    config_cls,
    cli_name: str,
    profile_auth_type: Optional[str],
) -> Optional[str]:
    if profile_auth_type is None:
        return None

    store = _profile_store_for_command(get_config_fn, config_cls, cli_name)
    active_profiles = [
        entry
        for entry in list_profiles(store)
        if entry.get("active") is True and entry.get("auth_type") == profile_auth_type
    ]
    if len(active_profiles) == 1:
        return active_profiles[0]["name"]
    if len(active_profiles) > 1:
        names = ", ".join(entry["name"] for entry in active_profiles)
        raise typer.BadParameter(
            f"Multiple active profiles found for auth type '{profile_auth_type}': {names}."
        )
    return None


def _resolve_runtime_profile_context(
    get_config_fn,
    cli_name: str,
    explicit_profile: Optional[str],
    cred_type_strings: list[str],
) -> tuple[Optional[str], Optional[str]]:
    runtime_profile_name, _runtime_profile_auth_type = get_runtime_profile_resolution()
    if explicit_profile is None and runtime_profile_name:
        explicit_profile = runtime_profile_name

    config_cls = _get_config_class(get_config_fn)
    profile_auth_settings = get_profile_auth_settings(config_cls) if config_cls is not None else None
    if explicit_profile:
        if profile_auth_settings is None:
            return explicit_profile, implicit_profile_auth_type()
        command_auth_type = _command_profile_auth_type(
            profile_auth_settings,
            cred_type_strings,
            require_unambiguous=False,
        )
        store = _profile_store_for_command(get_config_fn, config_cls, cli_name)
        profiles = {entry["name"]: entry for entry in list_profiles(store)}
        profile_entry = profiles.get(explicit_profile)
        if profile_entry is None:
            raise typer.BadParameter(f"Profile '{explicit_profile}' not found.")
        if command_auth_type is not None and profile_entry["auth_type"] != command_auth_type:
            raise typer.BadParameter(
                f"Profile '{explicit_profile}' has auth type '{profile_entry['auth_type']}', "
                f"but this command requires auth type '{command_auth_type}'."
            )
        return explicit_profile, profile_entry["auth_type"]

    command_auth_type = _command_profile_auth_type(
        profile_auth_settings,
        cred_type_strings,
    )
    profile_name = _active_profile_name_for_auth_type(
        get_config_fn,
        config_cls,
        cli_name,
        command_auth_type,
    )
    return profile_name, command_auth_type

def _profile_parameter() -> inspect.Parameter:
    return inspect.Parameter(
        "profile",
        inspect.Parameter.KEYWORD_ONLY,
        default=typer.Option(
            None,
            "--profile",
            help="Auth profile name",
        ),
    )


def _callback_name(callback) -> str:
    return callback.__name__.replace("_", "-")


def _is_help_invocation() -> bool:
    """Return True when the current CLI process is rendering help."""
    return any(arg in {"--help", "-h"} for arg in sys.argv[1:])


def _wrap_command_callback(
    command_info,
    *,
    get_config: Callable,
    cli_name: str,
    cred_types: list[str],
) -> None:
    callback = command_info.callback
    if callback is None or getattr(callback, "_cli_tools_profile_wrapped", False):
        return

    signature = inspect.signature(callback)
    has_profile_param = "profile" in signature.parameters
    wrapped_signature = signature
    if not has_profile_param:
        params = list(signature.parameters.values())
        insert_at = len(params)
        for index, parameter in enumerate(params):
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                insert_at = index
                break
        params.insert(insert_at, _profile_parameter())
        wrapped_signature = signature.replace(parameters=params)

    @functools.wraps(callback)
    def _wrapped_command(*args, **kwargs):
        explicit_profile = kwargs.get("profile")
        if not has_profile_param:
            kwargs.pop("profile", None)

        profile_name, profile_auth_type = _resolve_runtime_profile_context(
            get_config,
            cli_name,
            explicit_profile,
            cred_types,
        )
        tokens = set_runtime_profile_resolution(
            profile_name=profile_name,
            profile_auth_type=profile_auth_type,
        )
        try:
            try:
                config = get_config(profile=profile_name)
            except Exception as e:
                logger.debug("Config initialization failed: %s", e)
            else:
                _check_credentials(config, cred_types, cli_name)
            return callback(*args, **kwargs)
        finally:
            reset_runtime_profile_resolution(tokens)

    _wrapped_command.__signature__ = wrapped_signature
    _wrapped_command._cli_tools_profile_wrapped = True
    command_info.callback = _wrapped_command


def _install_command_wrappers(
    typer_app: typer.Typer,
    *,
    cred_map: dict,
    get_config: Callable,
    cli_name: str,
    inherited_cred_types: Optional[list[str]] = None,
) -> None:
    for command_info in typer_app.registered_commands:
        command_name = command_info.name or _callback_name(command_info.callback)
        cred_types = cred_map.get(command_name) or inherited_cred_types
        if cred_types:
            _wrap_command_callback(
                command_info,
                get_config=get_config,
                cli_name=cli_name,
                cred_types=cred_types,
            )

    for group_info in typer_app.registered_groups:
        group_name = group_info.name
        group_cred_types = cred_map.get(group_name) or inherited_cred_types
        _install_command_wrappers(
            group_info.typer_instance,
            cred_map=cred_map,
            get_config=get_config,
            cli_name=cli_name,
            inherited_cred_types=group_cred_types,
        )


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
        # Exit 2 = authentication/credential error (matches the documented
        # exit-code contract and CredentialError handling). Missing credentials
        # is an auth failure, not a generic error.
        raise typer.Exit(2)


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

    _install_command_wrappers(
        sub_app,
        cred_map=cred_map,
        get_config=get_config,
        cli_name=resolved_cli_name,
    )

    @sub_app.callback(invoke_without_command=True)
    def _credential_gate(
        ctx: typer.Context,
        profile: Optional[str] = typer.Option(None, "--profile", help="Auth profile name"),
    ):
        """Preserve the command group's no-subcommand help behavior."""
        if _is_help_invocation():
            return

        invoked = ctx.invoked_subcommand
        if invoked is None:
            # No subcommand — show help (default Typer behavior)
            if original_callback_fn:
                original_callback_fn(ctx)
            else:
                typer.echo(ctx.get_help())
                raise typer.Exit()
            return

        if profile is None:
            return

        cred_types = cred_map.get(invoked)
        if not cred_types:
            return

        profile_name, profile_auth_type = _resolve_runtime_profile_context(
            get_config,
            resolved_cli_name,
            profile,
            cred_types,
        )
        tokens = set_runtime_profile_resolution(
            profile_name=profile_name,
            profile_auth_type=profile_auth_type,
        )
        ctx.call_on_close(lambda: reset_runtime_profile_resolution(tokens))

    app.add_typer(sub_app, name=name, help=help)


def register_root_commands(
    app: typer.Typer,
    get_config: Callable,
    command_module,
    *,
    cli_name: Optional[str] = None,
) -> None:
    """Register a command module's commands directly on the root app.

    This keeps COMMAND_CREDENTIALS enforcement for CLIs that intentionally
    expose leaf commands at the root instead of under a resource group.
    """
    sub_app = command_module.app
    cred_map = getattr(command_module, "COMMAND_CREDENTIALS", None)
    resolved_cli_name = cli_name or (app.info.name if app.info.name else "cli")

    if app.registered_callback is None:
        @app.callback()
        def _cli_tools_root_command_group():
            pass

    if cred_map is not None:
        _install_command_wrappers(
            sub_app,
            cred_map=cred_map,
            get_config=get_config,
            cli_name=resolved_cli_name,
        )

    existing_names = {
        command_info.name or _callback_name(command_info.callback)
        for command_info in app.registered_commands
    }
    existing_names.update(
        group_info.name
        for group_info in app.registered_groups
        if group_info.name
    )

    for command_info in sub_app.registered_commands:
        command_name = command_info.name or _callback_name(command_info.callback)
        if command_name in existing_names:
            raise ValueError(f"Root command '{command_name}' is already registered.")
        app.registered_commands.append(command_info)
        existing_names.add(command_name)
