"""Standard profiles Typer app: list, create, set-default, delete, get."""

from typing import Optional, List

import typer

from .filters import apply_filters, apply_limit, apply_properties_filter
from .profiles import list_profiles, create_profile, set_default_profile, delete_profile
from .output import print_json, print_table, print_output, print_success, print_error, print_info, handle_error, command


def create_profiles_app(get_config_fn):
    """Create a standard profiles Typer app for a CLI tool.

    Args:
        get_config_fn: Callable that accepts (profile=None) and returns a BaseConfig.

    Returns:
        typer.Typer app with list, get, create, set-default, delete commands.
    """
    app = typer.Typer(help="Manage authentication profiles", no_args_is_help=True)

    @app.command("list")
    @command
    def profiles_list(
        table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
        limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of profiles to return"),
        filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., is_default:eq:True)"),
        properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    ):
        """List all profiles and show which is the default."""
        config = get_config_fn()
        profiles = list_profiles(config)

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
                    ["name", "file", "is_default"],
                    ["Name", "File", "Default"],
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
        config = get_config_fn()
        profiles = list_profiles(config)

        match = [p for p in profiles if p.get("name") == name]
        if not match:
            print_error(f"Profile '{name}' not found.")
            raise typer.Exit(1)

        profile = match[0]
        print_output(profile, table)

    @app.command("create")
    @command
    def profiles_create(
        name: str = typer.Argument(..., help="Profile name (e.g., staging, production)"),
    ):
        """Create a new profile from .env.example template."""
        config = get_config_fn()
        path = create_profile(config, name)
        print_success(f"Profile '{name}' created at {path.name}")
        print_info(f"Run 'auth login --profile {name}' to configure credentials.")

    @app.command("set-default")
    @command
    def profiles_set_default(
        name: str = typer.Argument(..., help="Profile name to set as default"),
    ):
        """Set a profile as the default (IS_DEFAULT_PROFILE=1)."""
        config = get_config_fn()
        set_default_profile(config, name)
        print_success(f"Profile '{name}' is now the default")

    @app.command("delete")
    @command
    def profiles_delete(
        name: str = typer.Argument(..., help="Profile name to delete"),
        force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation"),
    ):
        """Delete a profile and its data."""
        if not force and not typer.confirm(
            f"Delete profile '{name}'? This removes the .env file and profile data."
        ):
            raise typer.Exit(0)

        config = get_config_fn()
        delete_profile(config, name)
        print_success(f"Profile '{name}' deleted")

    return app
