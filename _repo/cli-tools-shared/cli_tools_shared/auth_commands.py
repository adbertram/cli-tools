"""Standard auth Typer app: login, logout, status, refresh with --profile support."""

import logging
import typer
from typing import Callable, Optional

from ._debug_logging import get_debug_logger
from .auth_verifier import AuthVerifier
from .credentials import (
    CredentialType,
    combined_ephemeral_fields,
    combined_login_prompts,
    mask_value,
)
from .exceptions import ConfigError
from .config import BaseConfig, get_profile_auth_settings, resolve_tool_dir
from .output import print_json, print_table, print_output, print_success, print_error, print_info, handle_error, command

logger = get_debug_logger("cli_tools.auth_commands")


_CREDENTIAL_TYPE_ALIASES = {
    "browser": CredentialType.BROWSER_SESSION.value,
}


def _login_setup_instructions(config) -> Optional[str]:
    """Return the preferred auth setup message for a config."""
    for attr_name in ("AUTH_SETUP_INSTRUCTIONS", "LOGIN_INSTRUCTIONS"):
        value = getattr(config, attr_name, None)
        if value:
            return str(value).strip()
    return None


def _has_prompt_placeholder_value(config, field_name: str, current_value: Optional[str]) -> bool:
    """Return True when a stored prompt value still matches the config default."""
    if not current_value:
        return False
    default_value = getattr(config, f"DEFAULT_{field_name}", None)
    return bool(default_value) and current_value == default_value


def _prompt_and_save(config, prompts, skip_if_set: bool = True) -> bool:
    """Prompt for credential fields and save values to config.

    Args:
        config: BaseConfig instance.
        prompts: Iterable of (field_name, prompt_text, hide_input) tuples.
        skip_if_set: If True, skip fields that already have a value.

    Returns:
        True if any field was prompted.
    """
    instructions_shown = False
    setup_instructions = _login_setup_instructions(config)
    prompted = False
    for field_name, prompt_text, hide in prompts:
        current = config._get(field_name)
        if current and skip_if_set and not _has_prompt_placeholder_value(config, field_name, current):
            continue
        if not instructions_shown:
            if setup_instructions:
                print_info(setup_instructions)
            instructions_shown = True
        prompted = True
        value = typer.prompt(f"Enter {prompt_text}", hide_input=hide)
        if not value or not value.strip():
            print_error(f"{prompt_text} cannot be empty")
            raise typer.Exit(1)
        config._set(field_name, value.strip())
    return prompted


def _clear_login_state(config, credential_types: list[CredentialType]) -> None:
    """Clear transient login state without removing reusable credentials."""
    fields = combined_ephemeral_fields(credential_types, config=config)
    for field_name in dict.fromkeys(fields):
        config._clear(field_name)

    if CredentialType.BROWSER_SESSION in credential_types:
        browser = config.get_browser() if hasattr(config, "get_browser") else None
        if browser is not None:
            browser.clear_session()
        else:
            config.clear_session()


def _handle_browser_login(config, tool_name: str, force: bool):
    """Handle browser session login if config.get_browser() is configured.

    Never claims "already authenticated" based on session files alone —
    cookies on disk can be expired or revoked server-side. The
    short-circuit must be backed by a live round-trip via
    ``browser.is_authenticated()``. If the live check fails we proceed
    to the interactive login flow even though session files exist on
    disk, because that is exactly the case the user wants caught.
    """
    logger.debug("_handle_browser_login: tool=%s force=%s", tool_name, force)
    browser = config.get_browser()
    if browser is None:
        logger.debug("_handle_browser_login: no browser configured, skipping")
        return
    # When the live check fails, the saved session is stale — we must
    # force the inner authenticate() to clear it, otherwise its
    # ``has_saved_session()`` short-circuit returns immediately without
    # ever opening the browser. The user would see "Browser session
    # authenticated" while nothing actually happened.
    effective_force = force
    try:
        if not force:
            has_session = config.has_saved_session()
            logger.debug("_handle_browser_login: has_saved_session=%s", has_session)
            if has_session:
                # Live-verify before declaring "already authenticated".
                try:
                    live = browser.is_authenticated()
                    live_ok = bool(live)
                except Exception as e:
                    logger.debug("_handle_browser_login: live check raised: %s", e)
                    live_ok = False
                logger.debug("_handle_browser_login: live check=%s", live_ok)
                if live_ok:
                    print_success(f"Already authenticated ({tool_name} browser session)")
                    return
                print_info(
                    "Saved session is no longer valid — re-running browser login."
                )
                effective_force = True

        print_info("Opening browser for login...")
        logger.debug("_handle_browser_login: calling browser.login(force=%s)", effective_force)
        result = browser.login(force=effective_force)
        logger.debug("_handle_browser_login: login result=%s", result)
        if result.get("success"):
            print_success("Browser session authenticated")
        else:
            print_error(f"Browser auth failed: {result.get('message', 'Unknown error')}")
            raise typer.Exit(1)
    finally:
        browser.close()


def _mask_saved_fields(config, cred_type) -> dict:
    """Return masked sensitive field values for a single credential type.

    Only fields with non-empty stored values are included. Both the
    required fields and the type's sensitive fields are masked so that
    callers can show a safe preview of what's configured.
    """
    fields = []
    if cred_type == CredentialType.CUSTOM:
        fields.extend(getattr(config, "CUSTOM_REQUIRED_FIELDS", []) or [])
    else:
        fields.extend(cred_type.required_fields)
    for f in cred_type.sensitive_fields:
        if f not in fields:
            fields.append(f)

    masked = {}
    for field in fields:
        value = config._get(field)
        if value:
            masked[field.lower()] = mask_value(value)
    return masked


def _resolve_profile_names(get_config_fn, requested_profile: Optional[str], tool_name: str) -> list:
    """Return the list of profile names to check.

    If a specific profile is requested, returns just that one. Otherwise
    enumerates every .env* file in the tool directory via list_profiles().
    Falls back to [None] when no profiles have been created yet.
    """
    if requested_profile:
        return [requested_profile]

    from .profiles import list_profiles

    config_cls = _get_config_class(get_config_fn)
    configured_credential_types = list(
        getattr(config_cls, "CREDENTIAL_TYPES", None)
        or []
    )
    profile_store = _get_profile_store_for_auth(get_config_fn, config_cls, tool_name)
    profile_entries = [entry for entry in list_profiles(profile_store) if entry.get("active") is True]
    if not profile_entries:
        return [None]
    return [entry["name"] for entry in profile_entries]


def _get_config_class(get_config_fn):
    get_config_fn = getattr(get_config_fn, "__wrapped__", get_config_fn)
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


def _tool_dir_from_closure(get_config_fn):
    for cell in getattr(get_config_fn, "__closure__", ()) or ():
        value = cell.cell_contents
        if isinstance(value, type(None)):
            continue
        if hasattr(value, "is_dir") and hasattr(value, "exists"):
            try:
                if value.exists():
                    return value
            except OSError:
                continue
    return None


def _get_profile_store_for_auth(get_config_fn, config_cls, tool_name: str):
    from .profiles import ProfileStore
    probe_config = None

    profile_auth_settings = None
    tool_dir = _tool_dir_from_closure(get_config_fn)
    if config_cls is not None:
        profile_auth_settings = get_profile_auth_settings(config_cls)
        if tool_dir is None and getattr(config_cls, "DIST_NAME", None):
            tool_dir = resolve_tool_dir(config_cls.DIST_NAME)

    if config_cls is None or tool_dir is None:
        try:
            probe_config = get_config_fn()
        except Exception:
            probe_config = None

    if config_cls is None and probe_config is not None:
        config_cls = type(probe_config)
        profile_auth_settings = get_profile_auth_settings(config_cls)

    if tool_dir is None:
        tool_dir = getattr(probe_config, "tool_dir", None)
    if tool_dir is None:
        tool_dir = _tool_dir_from_closure(get_config_fn)
    if config_cls is not None:
        if tool_dir is None and getattr(config_cls, "DIST_NAME", None):
            tool_dir = resolve_tool_dir(config_cls.DIST_NAME)
    return ProfileStore(tool_name, tool_dir=tool_dir, profile_auth_settings=profile_auth_settings)


def _collect_profile_statuses(
    get_config_fn,
    tool_name: str,
    profile: Optional[str],
    api_test_handler=None,
    verbose: bool = False,
) -> dict:
    """Run AuthVerifier for each target profile and build the response dict.

    Always returns {"profiles": [...]}. Each profile entry contains
    `name`, `auth_type`, `active`, `authenticated`, and `credential_types`. When
    `verbose` is True, `base_url` is added to every profile entry.
    """
    from .profiles import list_profiles

    profile_names = _resolve_profile_names(get_config_fn, profile, tool_name)

    config_cls = _get_config_class(get_config_fn)
    profile_store = _get_profile_store_for_auth(get_config_fn, config_cls, tool_name)
    profile_map = {
        entry["name"]: entry
        for entry in list_profiles(profile_store)
    }
    configured_credential_types = list(
        getattr(config_cls, "CREDENTIAL_TYPES", []) if config_cls is not None else []
    )

    profile_entries = []
    for prof_name in profile_names:
        try:
            config = get_config_fn(profile=prof_name)
        except ConfigError as exc:
            message = str(exc)
            if (
                config_cls is None
                or not message.startswith("Missing secret '")
                or " referenced by " not in message
            ):
                raise
            active_name = prof_name or "default"
            profile_meta = profile_map.get(active_name, {})
            credential_types = {
                ct.value: {
                    "credentials_saved": False,
                    "authenticated": False,
                    "api_test": f"failed: {message}",
                    "message": message,
                }
                for ct in configured_credential_types
            }
            profile_entries.append(
                {
                    "name": active_name,
                    "auth_type": profile_meta.get("auth_type") or "default",
                    "active": bool(profile_meta.get("active", False)),
                    "authenticated": False,
                    "credential_types": credential_types,
                    "missing": [message],
                }
            )
            continue
        verifier = AuthVerifier(config, api_test_handler=api_test_handler)
        result = verifier.verify()

        active_name = config.get_active_profile_name()
        profile_meta = profile_map.get(active_name)
        if profile_meta is None:
            profile_map = {
                entry["name"]: entry
                for entry in list_profiles(profile_store)
            }
            profile_meta = profile_map.get(active_name, {})
        entry = {
            "name": active_name,
            "auth_type": profile_meta.get("auth_type"),
            "active": bool(profile_meta.get("active", False)),
            "authenticated": result["authenticated"],
            "credential_types": result["credential_types"],
        }

        # Attach per-type static credential previews and missing-credentials
        # hints so the output is self-explanatory.
        for ct in config.CREDENTIAL_TYPES:
            type_key = ct.value
            block = entry["credential_types"].get(type_key)
            if block is None:
                continue
            if block.get("credentials_saved"):
                for masked_key, masked_val in _mask_saved_fields(config, ct).items():
                    block.setdefault(masked_key, masked_val)
            else:
                block.setdefault(
                    "message",
                    f"Not authenticated. Run '{tool_name} auth login' to configure.",
                )

        if not any(block.get("credentials_saved") for block in entry["credential_types"].values()):
            entry["missing"] = config.get_missing_credentials()

        if verbose:
            entry["base_url"] = config.base_url

        logger.debug("auth_status: profile=%s entry=%s", active_name, entry)
        profile_entries.append(entry)

    return {"profiles": profile_entries}


def _exit_if_no_authenticated_profile(data: dict) -> None:
    if not any(profile["authenticated"] for profile in data["profiles"]):
        raise typer.Exit(2)


def _bootstrap_profile_if_missing(get_config_fn, requested_profile: Optional[str], tool_name: str) -> Optional[str]:
    """Ensure a profile exists for ``auth login`` to write credentials into.

    On a fresh install no ``.env`` files exist yet, so ``auth login`` would
    silently write credentials without a registered profile and downstream
    commands like ``auth profiles list`` and ``auth status`` would fail to
    discover them. This helper auto-creates the profile that ``auth login``
    is about to populate.

    Behavior:
      * If ``requested_profile`` is ``None`` AND no profile env files exist
        for the tool, create a ``default`` profile.
      * If ``requested_profile`` is set and its env file does not exist,
        create that profile.
      * If the relevant profile already exists, do nothing.

    Returns the effective profile name to use for subsequent
    ``get_config_fn(profile=...)`` calls (either ``requested_profile`` or
    ``"default"`` after bootstrapping). Raises on creation failure — no
    silent suppression.
    """
    from .profiles import create_profile, list_profiles

    config_cls = _get_config_class(get_config_fn)
    profile_store = _get_profile_store_for_auth(get_config_fn, config_cls, tool_name)
    existing = list_profiles(profile_store)
    existing_names = {entry["name"] for entry in existing}

    if requested_profile is None:
        if existing:
            return None
        target_name = "default"
    else:
        if requested_profile in existing_names:
            return requested_profile
        target_name = requested_profile

    create_profile(profile_store, target_name)
    print_info(f"Created profile '{target_name}'")

    return target_name if requested_profile else None


def _require_profile_for_multi_auth_login(
    get_config_fn,
    requested_profile: Optional[str],
    tool_name: str,
) -> None:
    if requested_profile:
        return
    config_cls = _get_config_class(get_config_fn)
    profile_auth_settings = get_profile_auth_settings(config_cls) if config_cls is not None else None
    if profile_auth_settings is None:
        return
    _auth_type_field, auth_types = profile_auth_settings
    if len(auth_types) < 2:
        return
    valid_types = ", ".join(sorted(auth_types))
    print_error(
        f"{tool_name} auth login requires --profile because this CLI has "
        f"multiple profile auth types: {valid_types}. Create or select the "
        "target profile first, then run auth login --profile <name>."
    )
    raise typer.Exit(1)


def _resolve_credential_type(config, credential_type_str: str):
    """Resolve a credential type string to a CredentialType enum, validating it's configured."""
    cred_types = config.CREDENTIAL_TYPES
    if len(cred_types) < 2:
        print_error("--credential-type is only valid for CLIs with multiple credential types")
        raise typer.Exit(1)
    normalized = _CREDENTIAL_TYPE_ALIASES.get(credential_type_str, credential_type_str)
    for ct in cred_types:
        if ct.value == normalized:
            return ct
    valid = ", ".join(ct.value for ct in cred_types)
    print_error(f"Unknown credential type '{credential_type_str}'. Valid types: {valid}")
    raise typer.Exit(1)


def create_auth_app(
    get_config_fn,
    tool_name: str = "tool",
    login_handler: Optional[Callable] = None,
    test_handler: Optional[Callable] = None,
    profiles_app: Optional[typer.Typer] = None,
    include_profiles: bool = True,
):
    """Create a standard auth Typer app for a CLI tool.

    Args:
        get_config_fn: Callable that accepts (profile=None) and returns a BaseConfig.
        tool_name: CLI tool name for help text (e.g., 'cloudflare').
        login_handler: Optional callable(config, force) for custom login flows.
            Used by CLIs that need a custom OAuth flow (e.g., OAuth 1.0a,
            dual-auth). When provided, replaces the default interactive
            prompt login AND the built-in OAuth auto-detection. The handler
            is responsible for the entire login flow including obtaining
            and saving tokens.

            Handler priority (3-way resolution):
            1. Explicit login_handler param -> always wins
            2. Config has OAUTH_AUTH_URL + OAUTH_TOKEN_URL -> built-in oauth_login
            3. Neither -> default prompt-based login

        test_handler: Optional callable(config) -> dict for auth testing.
            Returns dict with at minimum {"api_test": "passed"|"failed: reason"}.
            Only provides the API test — credential checks and browser session
            checks are handled automatically by the shared package.
        profiles_app: Optional pre-built profiles Typer app. Use this when a CLI
            has a local profiles app that must be mounted exactly as-is.
        include_profiles: Mount the standard profiles app under auth.

    Returns:
        typer.Typer app with login, logout, status commands (+ refresh for OAuth,
        + profiles, + test if test_handler provided).
    """
    app = typer.Typer(help=f"Manage {tool_name} authentication", no_args_is_help=True)
    config_cls = _get_config_class(get_config_fn)
    probe_config = None
    if config_cls is None:
        try:
            probe_config = get_config_fn()
        except Exception:
            probe_config = None
    if config_cls is None and probe_config is not None:
        config_cls = type(probe_config)
    configured_credential_types = list(
        getattr(config_cls, "CREDENTIAL_TYPES", None)
        or getattr(probe_config, "CREDENTIAL_TYPES", [])
        or []
    )
    has_browser_auth = CredentialType.BROWSER_SESSION in configured_credential_types
    allow_credential_type_selection = len(configured_credential_types) > 1
    credential_type_examples = ", ".join(f"'{ct.value}'" for ct in configured_credential_types)
    if credential_type_examples:
        credential_type_help = f"Authenticate only this credential type (e.g., {credential_type_examples})"
    else:
        credential_type_help = "Authenticate only this credential type"
    logout_help = "Clear stored credentials and browser sessions." if has_browser_auth else "Clear stored credentials."
    if has_browser_auth:
        status_help = (
            "Check authentication status across profiles.\n\n"
            "Performs a live round-trip for every configured credential type so\n"
            "the report reflects ground truth — not on-disk belief. Saved\n"
            "credentials whose live verification fails are reported as\n"
            "``authenticated: false`` with the failure reason in\n"
            "``api_test`` (API/OAuth) or via the live browser check\n"
            "(browser_session)."
        )
    else:
        status_help = (
            "Check authentication status across profiles.\n\n"
            "Performs a live round-trip for every configured credential type so\n"
            "the report reflects ground truth — not on-disk belief. Saved\n"
            "credentials whose live verification fails are reported as\n"
            "``authenticated: false`` with the failure reason in\n"
            "``api_test``."
        )

    # Resolve the effective test handler ONCE so both ``auth status`` and
    # ``auth test`` use the same live-verification path. ``auth status``
    # MUST do live checks — filesystem state is not proof of being
    # authenticated.
    effective_test_handler = test_handler
    if effective_test_handler is None:
        try:
            if config_cls is not None and config_cls.test_connection is not BaseConfig.test_connection:
                def _auto_test_handler(config):
                    result = config.test_connection()
                    if result is not None:
                        return result
                    return {"api_test": "skipped: no test_connection implemented"}
                effective_test_handler = _auto_test_handler
        except Exception:
            pass

    login_doc = (
        "Configure authentication credentials.\n\n"
        "Prompts for required credentials based on the tool's authentication type.\n"
        "For OAuth authorization code flows, opens a browser for user consent."
    )

    def _run_auth_login(
        profile: Optional[str],
        force: bool,
        credential_type: Optional[str] = None,
    ):
        _require_profile_for_multi_auth_login(get_config_fn, profile, tool_name)
        # Auto-create a profile when none exists yet (or the requested one
        # is missing) so credentials saved during this login flow land in a
        # registered profile that ``auth profiles list`` / ``auth status``
        # can discover.
        effective_profile = _bootstrap_profile_if_missing(get_config_fn, profile, tool_name)
        config = get_config_fn(profile=effective_profile)

        # Resolve scoped credential type if specified
        resolved_type = None
        if credential_type:
            resolved_type = _resolve_credential_type(config, credential_type)

        # Determine which credential types to process
        active_types = [resolved_type] if resolved_type else config.CREDENTIAL_TYPES

        # Resolve effective handler (3-way)
        effective_handler = login_handler
        if effective_handler is None and config.OAUTH_AUTH_URL and config.OAUTH_TOKEN_URL:
            from .oauth import oauth_login
            effective_handler = oauth_login

        # Force clears only transient auth state. Static credentials such as
        # client IDs, client secrets, API keys, and redirect URIs remain usable.
        if force:
            _clear_login_state(config, active_types)
            print_info("Existing ephemeral auth state cleared")

        _prompt_and_save(
            config,
            getattr(config, "AUTH_CONFIG_PROMPTS", []),
            skip_if_set=True,
        )

        # Browser session only — skip all prompts, go directly to browser login
        if resolved_type == CredentialType.BROWSER_SESSION:
            _handle_browser_login(config, tool_name, force)
            return

        if effective_handler is not None:
            # Custom or built-in OAuth login flow
            # Ensure setup fields (CLIENT_ID, etc.) are configured first
            _prompt_and_save(
                config,
                combined_login_prompts(active_types, config=config),
                skip_if_set=True,
            )
            _prompt_and_save(config, config.AUTH_EXTRA_PROMPTS, skip_if_set=True)

            # Delegate to handler for token acquisition
            effective_handler(config, force)
        else:
            # Default prompt-based login — skip fields that already have values
            # (force only clears ephemeral fields, so static creds remain)
            prompted = _prompt_and_save(config, combined_login_prompts(active_types, config=config))
            _prompt_and_save(config, config.AUTH_EXTRA_PROMPTS, skip_if_set=True)

            if prompted:
                print_success("Credentials saved successfully")

        # Browser session login (if configured and no custom handler)
        # Custom handlers manage their own browser flow
        # Skip if --credential-type is set and it's not BROWSER_SESSION
        if effective_handler is None or effective_handler is not login_handler:
            if not resolved_type or resolved_type == CredentialType.BROWSER_SESSION:
                _handle_browser_login(config, tool_name, force)

    if allow_credential_type_selection:
        @app.command("login")
        @command
        def auth_login(
            profile: Optional[str] = typer.Option(
                None, "--profile", "-p", help="Profile name to save credentials to"
            ),
            force: bool = typer.Option(
                False, "--force", "-F", help="Clear existing ephemeral auth state and re-authenticate"
            ),
            credential_type: Optional[str] = typer.Option(
                None, "--credential-type", "--credential", "-c", help=credential_type_help
            ),
        ):
            _run_auth_login(profile, force, credential_type)

        auth_login.__doc__ = login_doc
    else:
        @app.command("login")
        @command
        def auth_login(
            profile: Optional[str] = typer.Option(
                None, "--profile", "-p", help="Profile name to save credentials to"
            ),
            force: bool = typer.Option(
                False, "--force", "-F", help="Clear existing ephemeral auth state and re-authenticate"
            ),
        ):
            _run_auth_login(profile, force)

        auth_login.__doc__ = login_doc

    @app.command("logout", help=logout_help)
    @command
    def auth_logout(
        profile: Optional[str] = typer.Option(
            None, "--profile", "-p", help="Profile name to clear credentials from"
        ),
    ):
        target_profiles = _resolve_profile_names(get_config_fn, profile, tool_name)
        for profile_name in target_profiles:
            config = get_config_fn(profile=profile_name)
            config.clear_credentials()
            browser = config.get_browser()
            if browser is not None:
                browser.close()
            config.clear_session()
        print_success("Credentials cleared")

    @app.command("status", help=status_help)
    @command
    def auth_status(
        profile: Optional[str] = typer.Option(
            None, "--profile", "-p", help="Profile name to check (defaults to all profiles)"
        ),
        table: bool = typer.Option(
            False, "--table", "-t", help="Display as table"
        ),
    ):
        data = _collect_profile_statuses(
            get_config_fn=get_config_fn,
            tool_name=tool_name,
            profile=profile,
            api_test_handler=effective_test_handler,
        )
        print_output(data, table)
        _exit_if_no_authenticated_profile(data)

    # Add refresh command only if config has OAuth token URL
    # We check lazily via a probe config to avoid requiring profile at import time
    if config_cls is not None and getattr(config_cls, "OAUTH_TOKEN_URL", ""):
        @app.command("refresh")
        @command
        def auth_refresh(
            profile: Optional[str] = typer.Option(
                None, "--profile", "-p", help="Profile name"
            ),
            table: bool = typer.Option(
                False, "--table", "-t", help="Display as table"
            ),
        ):
            """Refresh OAuth access token using stored refresh token."""
            config = get_config_fn(profile=profile)
            from .token_manager import TokenManager
            tm = TokenManager(config)
            tm.force_refresh()
            print_success("Access token refreshed")

    # Add test command if test_handler is provided or auto-detected.
    # ``effective_test_handler`` is resolved once at the top of this
    # function and reused for both ``auth status`` and ``auth test``.
    if effective_test_handler is not None:
        @app.command("test")
        @command
        def auth_test(
            table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
            verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed checks"),
            profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Profile name (defaults to all profiles)"),
        ):
            """Test authentication by verifying credentials work across profiles."""
            data = _collect_profile_statuses(
                get_config_fn=get_config_fn,
                tool_name=tool_name,
                profile=profile,
                api_test_handler=effective_test_handler,
                verbose=verbose,
            )
            print_output(data, table)
            _exit_if_no_authenticated_profile(data)

    if include_profiles:
        if profiles_app is None:
            from .profiles_commands import create_profiles_app
            profiles_app = create_profiles_app(get_config_fn, tool_name)
        app.add_typer(profiles_app, name="profiles", help="Manage authentication profiles")

    return app
