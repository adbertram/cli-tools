"""Official Descript API CLI configuration commands."""
from __future__ import annotations

from typing import List, Optional

import typer

from cli_tools_shared.filters import apply_filters, validate_filters
from cli_tools_shared.output import print_error, print_json, print_table

from ..platform import (
    PlatformCLIError,
    run_platform,
    run_platform_passthrough,
    select_object_properties,
    select_properties,
)


app = typer.Typer(
    help="Manage official Descript API CLI configuration",
    no_args_is_help=False,
    invoke_without_command=True,
)


def _run(args: list[str], *, profile: Optional[str] = None) -> None:
    try:
        code = run_platform_passthrough(args, profile=profile)
    except PlatformCLIError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    raise typer.Exit(code)


def _parse_config_list_output(output: str) -> list[dict]:
    config_path = None
    active_profile = None
    records = []

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Configuration (") and stripped.endswith("):"):
            config_path = stripped[len("Configuration ("):-2]
            continue
        if stripped.startswith("Active Profile:"):
            active_profile = stripped.split(":", 1)[1].strip()
            continue
        if ":" not in stripped:
            continue

        key, value = [part.strip() for part in stripped.split(":", 1)]
        source = None
        if value.endswith("(default)"):
            value = value[:-len("(default)")].strip()
            source = "default"
        records.append(
            {
                "id": key,
                "name": key,
                "key": key,
                "value": value,
                "source": source,
                "profile": active_profile,
                "config_path": config_path,
            }
        )

    return records


@app.callback()
def config_default(ctx: typer.Context) -> None:
    """Open the official interactive configuration menu."""
    if ctx.invoked_subcommand is None:
        _run(["config"])


@app.command("list")
def config_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of values"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
) -> None:
    """Show all official configuration values."""
    try:
        result = run_platform(["config", "list"], capture_output=True, profile=profile)
        output_data = _parse_config_list_output(result.stdout)

        if filter:
            try:
                validate_filters(filter)
            except Exception as exc:
                print_error(str(exc))
                raise typer.Exit(1)
            output_data = apply_filters(output_data, filter)

        if limit is not None:
            output_data = output_data[:limit]

        output_data = select_properties(output_data, properties)

        if table:
            headers = list(output_data[0].keys()) if output_data else ["key", "value"]
            display_headers = [header.replace("_", " ").title() for header in headers]
            print_table(output_data, headers, display_headers)
        else:
            print_json(output_data)
    except PlatformCLIError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Configuration key"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
) -> None:
    """Get an official configuration value."""
    try:
        result = run_platform(["config", "get", key], capture_output=True, profile=profile)
        output = select_object_properties(
            {
                "id": key,
                "name": key,
                "key": key,
                "value": result.stdout.strip(),
            },
            properties,
        )
        if table:
            headers = list(output.keys())
            display_headers = [header.replace("_", " ").title() for header in headers]
            print_table([output], headers, display_headers)
        else:
            print_json(output)
    except PlatformCLIError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Configuration key"),
    value: Optional[str] = typer.Argument(None, help="Configuration value"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
) -> None:
    """Set an official configuration value."""
    args = ["config", "set", key]
    if value is not None:
        args.append(value)
    _run(args, profile=profile)


@app.command("clear")
def config_clear(
    key: str = typer.Argument(..., help="Configuration key"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
) -> None:
    """Clear an official configuration value."""
    _run(["config", "clear", key], profile=profile)


@app.command("profiles")
def config_profiles(
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
) -> None:
    """List official Descript API CLI profiles."""
    _run(["config", "profiles"], profile=profile)


@app.command("profile")
def config_profile(
    name: str = typer.Argument(..., help="Profile name"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
) -> None:
    """Switch to an official Descript API CLI profile."""
    _run(["config", "profile", name], profile=profile)


@app.command("profile:create")
def config_profile_create(
    name: str = typer.Argument(..., help="Profile name"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
) -> None:
    """Create an official Descript API CLI profile."""
    _run(["config", "profile:create", name], profile=profile)


@app.command("profile:delete")
def config_profile_delete(
    name: str = typer.Argument(..., help="Profile name"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
) -> None:
    """Delete an official Descript API CLI profile."""
    _run(["config", "profile:delete", name], profile=profile)


@app.command("validate")
def config_validate(
    profile: Optional[str] = typer.Option(None, "--profile", help="Official descript-api profile"),
) -> None:
    """Validate the official Descript API CLI API key."""
    _run(["config", "validate"], profile=profile)


COMMAND_CREDENTIALS = {
    "clear": ["no_auth"],
    "get": ["no_auth"],
    "list": ["no_auth"],
    "profile": ["no_auth"],
    "profile:create": ["no_auth"],
    "profile:delete": ["no_auth"],
    "profiles": ["no_auth"],
    "set": ["no_auth"],
    "validate": ["no_auth"],
}
