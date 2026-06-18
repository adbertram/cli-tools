"""Standard profiles Typer app: list, create, select, delete, get."""

from typing import Optional, List

import click

import typer

from .config import ConfigError, get_profile_auth_settings, resolve_tool_dir
from .filters import apply_filters, apply_limit, apply_properties_filter
from .profiles import ProfileStore, create_profile, delete_profile, list_profiles, select_profile
from .output import print_json, print_table, print_output, print_success, print_error, print_info, handle_error, command, confirm_destructive_action


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


def _get_profile_store(get_config_fn, tool_name: str, probe_config=None) -> ProfileStore:
    config_cls = _get_config_class(get_config_fn)
    if config_cls is None and probe_config is not None:
        config_cls = type(probe_config)
    profile_auth_settings = get_profile_auth_settings(config_cls) if config_cls is not None else None
    tool_dir = getattr(probe_config, "tool_dir", None)
    if tool_dir is None:
        tool_dir = _tool_dir_from_closure(get_config_fn)
    if tool_dir is None and config_cls is not None and getattr(config_cls, "DIST_NAME", None):
        tool_dir = resolve_tool_dir(config_cls.DIST_NAME)
    return ProfileStore(tool_name, tool_dir=tool_dir, profile_auth_settings=profile_auth_settings)


def _parse_auth_params(raw_params: Optional[List[str]]) -> dict[str, str]:
    """Parse repeated ``FIELD=VALUE`` auth parameter options."""
    parsed: dict[str, str] = {}
    for raw_param in raw_params or []:
        if "=" not in raw_param:
            print_error(
                f"Invalid auth parameter '{raw_param}'. Use --auth-param FIELD=VALUE."
            )
            raise typer.Exit(1)
        field_name, value = raw_param.split("=", 1)
        field_name = field_name.strip()
        if not field_name:
            print_error(
                f"Invalid auth parameter '{raw_param}'. Use --auth-param FIELD=VALUE."
            )
            raise typer.Exit(1)
        if field_name in parsed:
            print_error(f"Duplicate auth parameter '{field_name}'.")
            raise typer.Exit(1)
        clean_value = value.strip()
        if not clean_value:
            print_error(f"Auth parameter '{field_name}' cannot be empty.")
            raise typer.Exit(1)
        parsed[field_name] = clean_value
    return parsed


def _collect_profile_auth_values(prompts, provided_values: dict[str, str]) -> dict[str, str]:
    """Validate and collect auth-type-specific profile values before profile creation."""
    expected_fields = {field_name for field_name, _prompt_text, _hide in prompts}
    unexpected = sorted(set(provided_values) - expected_fields)
    if unexpected:
        expected = ", ".join(sorted(expected_fields)) if expected_fields else "(none)"
        print_error(
            f"Unexpected auth parameters: {', '.join(unexpected)}. Expected fields: {expected}."
        )
        raise typer.Exit(1)

    resolved_values: dict[str, str] = {}
    for field_name, prompt_text, hide_input in prompts:
        value = provided_values.get(field_name)
        if value is None:
            try:
                value = typer.prompt(f"Enter {prompt_text}", hide_input=hide_input)
            except click.Abort:
                print_error(
                    "Missing required auth parameter values. "
                    "Provide --auth-param FIELD=VALUE or run interactively to enter them."
                )
                raise typer.Exit(1)
            value = value.strip()
        if not value:
            print_error(f"{prompt_text} cannot be empty.")
            raise typer.Exit(1)
        resolved_values[field_name] = value
    return resolved_values


def create_profiles_app(get_config_fn, tool_name: str):
    """Create a standard profiles Typer app for a CLI tool.

    Args:
        get_config_fn: Callable that accepts (profile=None) and returns a BaseConfig.

    Returns:
        typer.Typer app with list, get, create, select, delete commands.
    """
    app = typer.Typer(help="Manage authentication profiles", no_args_is_help=True)
    probe_config = None
    if _get_config_class(get_config_fn) is None:
        try:
            probe_config = get_config_fn()
        except Exception:
            probe_config = None
    profile_store = _get_profile_store(get_config_fn, tool_name, probe_config)

    @app.command("list")
    @command
    def profiles_list(
        table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
        limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of profiles to return"),
        filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., active:eq:True)"),
        properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    ):
        """List all profiles and show their auth types and active state."""
        profiles = list_profiles(profile_store)

        if not profiles:
            print_error("No profiles found. Run 'auth profiles create <name>' to create one.")
            raise typer.Exit(1)

        # Apply filters
        profiles = apply_filters(profiles, filter)
        profiles = apply_limit(profiles, limit)
        profiles = apply_properties_filter(profiles, properties)

        if table:
            if properties:
                cols = [p.strip() for p in properties.split(",")]
                headers = [c.replace("_", " ").title() for c in cols]
                print_table(profiles, cols, headers)
            else:
                print_table(
                    profiles,
                    ["name", "file", "auth_type", "active"],
                    ["Name", "File", "Auth Type", "Active"],
                )
        else:
            print_json(profiles)

    @app.command("get")
    @command
    def profiles_get(
        name: str = typer.Argument(..., help="Profile name to get details for"),
        table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    ):
        """Get details for a specific profile."""
        profiles = list_profiles(profile_store)

        match = [p for p in profiles if p.get("name") == name]
        if not match:
            print_error(f"Profile '{name}' not found.")
            raise typer.Exit(1)

        profile = match[0]
        print_output(profile, table)

    try:
        profile_auth_settings = profile_store.get_profile_auth_settings()
    except ConfigError as exc:
        raise RuntimeError(f"Invalid profile auth configuration: {exc}") from exc

    if profile_auth_settings is None:
        @app.command("create")
        @command
        def profiles_create(
            name: str = typer.Argument(..., help="Profile name (e.g., staging, production)"),
        ):
            """Create a new profile from .env.example template."""
            path = create_profile(profile_store, name)
            print_success(f"Profile '{name}' created at {path.name}")
            print_info(f"Run 'auth login --profile {name}' to configure credentials.")
    else:
        auth_type_field, auth_types = profile_auth_settings
        valid_auth_types = ", ".join(auth_types)

        @app.command("create")
        @command
        def profiles_create(
            name: str = typer.Argument(..., help="Profile name (e.g., staging, production)"),
            auth_type: str = typer.Option(
                ...,
                "--auth-type",
                help=f"Authentication type for this profile. Valid values: {valid_auth_types}",
            ),
            auth_param: Optional[List[str]] = typer.Option(
                None,
                "--auth-param",
                help="Auth parameter as FIELD=VALUE. Repeat for additional required values.",
            ),
        ):
            """Create a new profile from .env.example template."""
            prompts = auth_types.get(auth_type)
            if prompts is None:
                print_error(
                    f"Unknown auth type '{auth_type}'. Valid types: {valid_auth_types}."
                )
                raise typer.Exit(1)

            auth_values = _collect_profile_auth_values(
                prompts,
                _parse_auth_params(auth_param),
            )
            path = create_profile(profile_store, name, auth_type=auth_type)
            profile_config = get_config_fn(profile=name)
            profile_config._set(auth_type_field, auth_type)
            for field_name, value in auth_values.items():
                profile_config._set(field_name, value)
            print_success(f"Profile '{name}' created at {path.name}")
            print_info(f"Run 'auth login --profile {name}' to configure credentials.")

    @app.command("select")
    @command
    def profiles_select(
        name: str = typer.Argument(..., help="Profile name to activate within its auth type"),
    ):
        """Activate a profile within its auth type."""
        select_profile(profile_store, name)
        print_success(f"Profile '{name}' is now active for its auth type")

    def _delete_profile(
        name: str = typer.Argument(..., help="Profile name to delete"),
        force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation"),
    ):
        """Delete a profile and its data."""
        confirm_destructive_action(
            f"Delete profile '{name}'? This removes the .env file and profile data.",
            assume_yes=force,
            action_description=f"delete profile '{name}'",
        )

        delete_profile(profile_store, name)
        print_success(f"Profile '{name}' deleted")

    app.command("delete")(
        command(_delete_profile)
    )
    app.command("remove")(
        command(_delete_profile)
    )

    return app
