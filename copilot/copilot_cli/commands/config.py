"""Config management commands: paths, profile inspection, and secrets.

Subcommands:

    copilot config show        Print effective config dirs and profiles.
    copilot config path        Print a single resolved path.
    copilot config set-secret  Store a profile-scoped secret placeholder.
"""

from __future__ import annotations

from typing import Optional

import typer

from cli_tools_shared.output import (
    print_json,
    print_table,
    print_success,
    print_error,
    handle_error,
)
from cli_tools_shared.repo_paths import secret_manager_script

from ..config import (
    Config,
    get_cache_root,
    get_config_root,
    get_profiles_dir,
    list_profile_files,
    profile_name_from_xdg_path,
)


app = typer.Typer(help="Manage copilot configuration paths, profiles, and secrets.", no_args_is_help=True)

COMMAND_CREDENTIALS = {
    "show": ["no_auth"],
    "path": ["no_auth"],
    "set-secret": ["no_auth"],
}


@app.command("show")
def config_show(
    json_output: bool = typer.Option(
        False, "--json", help="Emit JSON instead of a table.",
    ),
):
    """Show effective config paths and active profile."""
    try:
        cfg = Config()
        active = cfg.get_active_profile_name()
        profiles = [profile_name_from_xdg_path(p) for p in list_profile_files()]

        data = {
            "config_dir": str(get_config_root()),
            "cache_dir": str(get_cache_root()),
            "profiles_dir": str(get_profiles_dir()),
            "active_profile": active,
            "available_profiles": profiles,
            "secret_manager": str(secret_manager_script()),
        }

        if json_output:
            print_json(data)
            return

        rows = [
            {"property": "Config dir", "value": data["config_dir"]},
            {"property": "Cache dir", "value": data["cache_dir"]},
            {"property": "Profiles dir", "value": data["profiles_dir"]},
            {"property": "Active profile", "value": data["active_profile"]},
            {"property": "Available profiles", "value": ", ".join(profiles) or "(none)"},
            {"property": "Secret manager", "value": data["secret_manager"]},
        ]
        print_table(rows, columns=["property", "value"], headers=["Property", "Value"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("path")
def config_path(
    kind: str = typer.Argument(
        ...,
        help="Which path to print: config | cache | profiles | active",
    ),
):
    """Print a single resolved path."""
    try:
        kind_l = kind.lower()
        if kind_l == "config":
            typer.echo(str(get_config_root()))
        elif kind_l == "cache":
            typer.echo(str(get_cache_root()))
        elif kind_l == "profiles":
            typer.echo(str(get_profiles_dir()))
        elif kind_l == "active":
            cfg = Config()
            typer.echo(str(cfg.env_file_path))
        else:
            print_error(f"Unknown path kind '{kind}'. Choose: config | cache | profiles | active")
            raise typer.Exit(2)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("set-secret")
def config_set_secret(
    key: str = typer.Argument(..., help="Secret name (e.g. AZURE_CLIENT_SECRET)."),
    value: Optional[str] = typer.Option(None, "--value", help="Value to store. Prompted if omitted."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile to scope the secret to (default: active)."),
):
    """Store a secret in the CLI-tools secret manager for a profile."""
    try:
        from getpass import getpass

        cfg = Config(profile=profile) if profile else Config()
        active = cfg.get_active_profile_name()

        key = key.upper()
        allowed = set(Config.CUSTOM_SENSITIVE_FIELDS)
        if key not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            print_error(f"Unknown copilot secret field '{key}'. Choose: {allowed_text}")
            raise typer.Exit(2)

        if value is None:
            value = getpass(f"Enter value for {key}: ")
            if not value:
                print_error("Value cannot be empty.")
                raise typer.Exit(1)

        cfg._set(key, value)
        print_success(f"Stored {key} with the CLI-tools secret manager (profile={active}).")
    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
