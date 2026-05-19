"""Profiles commands for eBay CLI with standard list flags."""
import typer
from typing import Optional, List

from cli_tools_shared.profiles import list_profiles, create_profile, set_default_profile, delete_profile
from cli_tools_shared.output import print_json, print_table, print_error, print_success, print_info, handle_error
from ..config import get_config
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError


app = typer.Typer(help="Manage profiles", no_args_is_help=True)


@app.command("list")
def profiles_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of profiles to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """List all profiles and show which is the default."""
    try:
        config = get_config()
        profiles = list_profiles(config.tool_dir)

        if not profiles:
            print_error("No profiles found. Run 'auth login' to create one.")
            raise typer.Exit(1)

        # Apply client-side filtering
        if filter:
            try:
                validate_filters(filter)
                profiles = apply_filters(profiles, filter)
            except FilterValidationError as e:
                print_error(f"Invalid filter: {e}")
                raise typer.Exit(1)

        # Apply limit
        profiles = profiles[:limit]

        # Apply property selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            profiles = [{f: p.get(f) for f in fields} for p in profiles]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(profiles, fields, fields)
            else:
                print_table(
                    profiles,
                    ["name", "file", "is_default"],
                    ["Name", "File", "Default"],
                )
        else:
            print_json(profiles)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def profiles_get(
    name: str = typer.Argument(..., help="Profile name to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get details for a specific profile."""
    try:
        config = get_config()
        profiles = list_profiles(config.tool_dir)

        match = [p for p in profiles if p["name"] == name]
        if not match:
            print_error(f"Profile '{name}' not found")
            raise typer.Exit(1)

        profile = match[0]

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in profile.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(profile)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def profiles_create(
    name: str = typer.Argument(..., help="Profile name (e.g., staging, production)"),
):
    """Create a new profile from .env.example template."""
    try:
        config = get_config()
        path = create_profile(config.tool_dir, name)
        print_success(f"Profile '{name}' created at {path.name}")
        print_info(f"Run 'auth login --profile {name}' to configure credentials.")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("set-default")
def profiles_set_default(
    name: str = typer.Argument(..., help="Profile name to set as default"),
):
    """Set a profile as the default (IS_DEFAULT_PROFILE=1)."""
    try:
        config = get_config()
        set_default_profile(config.tool_dir, name)
        print_success(f"Profile '{name}' is now the default")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def profiles_delete(
    name: str = typer.Argument(..., help="Profile name to delete"),
    force: bool = typer.Option(False, "--force", "-F", help="Skip confirmation"),
):
    """Delete a profile and its data."""
    try:
        if not force and not typer.confirm(
            f"Delete profile '{name}'? This removes the .env file and profile data."
        ):
            raise typer.Exit(0)

        config = get_config()
        delete_profile(config.tool_dir, name)
        print_success(f"Profile '{name}' deleted")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
