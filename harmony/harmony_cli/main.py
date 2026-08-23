"""Main entry point for Harmony CLI."""

from __future__ import annotations

from typing import List, Optional

import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import command, print_error, print_json, print_table

from . import __version__
from .client import get_client
from .config import get_config

HubOption = typer.Option(None, "--hub", "-H", help="Hub IP, hostname, or discovered hub name")
ProtocolOption = typer.Option(None, "--protocol", help="Protocol: WEBSOCKETS or XMPP")
LimitOption = typer.Option(100, "--limit", "-l", help="Maximum number of results")
FilterOption = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)")
TableOption = typer.Option(False, "--table", "-t", help="Display as table")
PropertiesOption = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include")

app = create_app(name="harmony", help="Manage Logitech Harmony hubs and devices", version=__version__)
hubs_app = typer.Typer(help="Manage Harmony hubs", no_args_is_help=True)
activities_app = typer.Typer(help="Manage Harmony activities", no_args_is_help=True)
devices_app = typer.Typer(help="Manage Harmony devices", no_args_is_help=True)
commands_app = typer.Typer(help="Manage Harmony device commands", no_args_is_help=True)
config_app = typer.Typer(help="Inspect Harmony hub configuration", no_args_is_help=True)


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _validate(filters: Optional[List[str]]) -> None:
    if not filters:
        return
    try:
        validate_filters(filters)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


def _filter_and_project(rows: list[dict], filters: Optional[List[str]], properties: Optional[str]) -> list[dict]:
    _validate(filters)
    if filters:
        rows = apply_filters(rows, filters)
    if properties:
        rows = apply_properties_filter(rows, properties)
    return rows


def _render_rows(
    rows: list[dict],
    *,
    table: bool,
    properties: Optional[str],
    default_columns: list[str],
) -> None:
    fields = _property_fields(properties)
    if not table:
        print_json(rows)
        return
    columns = fields or default_columns
    print_table(rows, columns, [column.replace("_", " ").title() for column in columns])


def _render_object(row: dict, *, table: bool, properties: Optional[str]) -> None:
    rows = apply_properties_filter([row], properties) if properties else [row]
    record = rows[0] if rows else {}
    if not table:
        print_json(record)
        return
    print_table(
        [{"field": key, "value": value} for key, value in record.items()],
        ["field", "value"],
        ["Field", "Value"],
    )


@hubs_app.command("list")
@command
def list_hubs(
    timeout: float = typer.Option(3.0, "--timeout", help="Discovery timeout in seconds"),
    limit: int = LimitOption,
    filter: Optional[List[str]] = FilterOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Discover Harmony hubs on the local network."""
    rows = get_client().list_hubs(limit=limit, timeout=timeout)
    rows = _filter_and_project(rows, filter, properties)
    _render_rows(rows, table=table, properties=properties, default_columns=["id", "name", "ip", "protocol"])


@hubs_app.command("get")
@command
def get_hub(
    hub: str = typer.Argument(..., help="Hub IP, hostname, or discovered hub name"),
    protocol: Optional[str] = ProtocolOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Get hub status and summary details."""
    _render_object(get_client().get_hub(hub, protocol=protocol), table=table, properties=properties)


@hubs_app.command("search")
@command
def search_hubs(
    query: str = typer.Argument(..., help="Search text"),
    timeout: float = typer.Option(3.0, "--timeout", help="Discovery timeout in seconds"),
    limit: int = LimitOption,
    filter: Optional[List[str]] = FilterOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Search discovered hubs."""
    rows = get_client().search_hubs(query, limit=limit, timeout=timeout)
    rows = _filter_and_project(rows, filter, properties)
    _render_rows(rows, table=table, properties=properties, default_columns=["id", "name", "ip", "protocol"])


@hubs_app.command("probe")
@command
def probe_hubs(
    cidr: Optional[str] = typer.Option(None, "--cidr", help="IPv4 CIDR to scan; defaults to the primary local /24"),
    port: Optional[List[int]] = typer.Option(None, "--port", help="TCP port to probe; repeat for multiple ports"),
    timeout: float = typer.Option(0.25, "--timeout", help="Per-port connection timeout in seconds"),
    workers: int = typer.Option(96, "--workers", help="Concurrent probe workers"),
    max_hosts: int = typer.Option(1024, "--max-hosts", help="Maximum hosts allowed in the CIDR"),
    verify: bool = typer.Option(True, "--verify/--no-verify", help="Verify candidates by connecting as Harmony hubs"),
    limit: int = LimitOption,
    filter: Optional[List[str]] = FilterOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Probe a subnet for Harmony-compatible TCP ports."""
    rows = get_client().probe_hubs(
        cidr=cidr,
        ports=port,
        timeout=timeout,
        workers=workers,
        max_hosts=max_hosts,
        limit=limit,
        verify=verify,
    )
    rows = _filter_and_project(rows, filter, properties)
    _render_rows(
        rows,
        table=table,
        properties=properties,
        default_columns=["id", "name", "ip", "open_ports", "protocols", "verified"],
    )


@hubs_app.command("sync")
@command
def sync_hub(
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Sync the hub with Logitech's Harmony service."""
    _render_object(get_client().sync(hub=hub, protocol=protocol), table=table, properties=properties)


@activities_app.command("list")
@command
def list_activities(
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    limit: int = LimitOption,
    filter: Optional[List[str]] = FilterOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """List activities configured on a hub."""
    rows = get_client().list_activities(hub=hub, protocol=protocol, limit=limit)
    rows = _filter_and_project(rows, filter, properties)
    _render_rows(rows, table=table, properties=properties, default_columns=["id", "name", "status"])


@activities_app.command("get")
@command
def get_activity(
    activity: str = typer.Argument(..., help="Activity ID or name"),
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Get one activity."""
    _render_object(get_client().get_activity(activity, hub=hub, protocol=protocol), table=table, properties=properties)


@activities_app.command("current")
@command
def current_activity(
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Show the current activity."""
    _render_object(get_client().get_current_activity(hub=hub, protocol=protocol), table=table, properties=properties)


@activities_app.command("start")
@command
def start_activity(
    activity: str = typer.Argument(..., help="Activity ID or name"),
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Start an activity."""
    row = get_client().start_activity(activity, hub=hub, protocol=protocol)
    _render_object(row, table=table, properties=properties)


@activities_app.command("power-off")
@command
def power_off(
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Power off the current activity."""
    _render_object(get_client().power_off(hub=hub, protocol=protocol), table=table, properties=properties)


@activities_app.command("search")
@command
def search_activities(
    query: str = typer.Argument(..., help="Search text"),
    hub: Optional[str] = HubOption,
    limit: int = LimitOption,
    filter: Optional[List[str]] = FilterOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Search hub activities."""
    rows = get_client().search_activities(query, hub=hub, limit=limit)
    rows = _filter_and_project(rows, filter, properties)
    _render_rows(rows, table=table, properties=properties, default_columns=["id", "name", "status"])


@devices_app.command("list")
@command
def list_devices(
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    limit: int = LimitOption,
    filter: Optional[List[str]] = FilterOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """List devices configured on a hub."""
    rows = get_client().list_devices(hub=hub, protocol=protocol, limit=limit)
    rows = _filter_and_project(rows, filter, properties)
    _render_rows(rows, table=table, properties=properties, default_columns=["id", "name", "manufacturer", "model", "command_count"])


@devices_app.command("get")
@command
def get_device(
    device: str = typer.Argument(..., help="Device ID or name"),
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Get one device."""
    _render_object(get_client().get_device(device, hub=hub, protocol=protocol), table=table, properties=properties)


@devices_app.command("search")
@command
def search_devices(
    query: str = typer.Argument(..., help="Search text"),
    hub: Optional[str] = HubOption,
    limit: int = LimitOption,
    filter: Optional[List[str]] = FilterOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Search hub devices."""
    rows = get_client().search_devices(query, hub=hub, limit=limit)
    rows = _filter_and_project(rows, filter, properties)
    _render_rows(rows, table=table, properties=properties, default_columns=["id", "name", "manufacturer", "model", "command_count"])


@commands_app.command("list")
@command
def list_commands(
    device: str = typer.Argument(..., help="Device ID or name"),
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    limit: int = LimitOption,
    filter: Optional[List[str]] = FilterOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """List commands for a device."""
    rows = get_client().list_commands(device, hub=hub, protocol=protocol, limit=limit)
    rows = _filter_and_project(rows, filter, properties)
    _render_rows(rows, table=table, properties=properties, default_columns=["id", "name", "command", "device_name", "group"])


@commands_app.command("get")
@command
def get_command(
    device: str = typer.Argument(..., help="Device ID or name"),
    command_name: str = typer.Argument(..., help="Command ID or name"),
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Get one device command."""
    row = get_client().get_command(device, command_name, hub=hub, protocol=protocol)
    _render_object(row, table=table, properties=properties)


@commands_app.command("send")
@command
def send_command(
    device: str = typer.Argument(..., help="Device ID or name"),
    command_name: str = typer.Argument(..., help="Command name"),
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    repeat: int = typer.Option(1, "--repeat", "-r", help="Number of times to send the command"),
    delay: float = typer.Option(0.4, "--delay", help="Seconds between repeats"),
    hold: float = typer.Option(0.0, "--hold", help="Seconds to hold the command"),
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Send a command to a device."""
    row = get_client().send_command(
        device,
        command_name,
        hub=hub,
        protocol=protocol,
        repeat=repeat,
        delay=delay,
        hold=hold,
    )
    _render_object(row, table=table, properties=properties)


@commands_app.command("channel")
@command
def change_channel(
    channel: str = typer.Argument(..., help="Numeric channel"),
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Change channel on the current activity."""
    _render_object(get_client().change_channel(channel, hub=hub, protocol=protocol), table=table, properties=properties)


@config_app.command("get")
@command
def get_config_command(
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """Get the full hub configuration."""
    _render_object(get_client().get_config(hub=hub, protocol=protocol), table=table, properties=properties)


@config_app.command("list")
@command
def list_config(
    hub: Optional[str] = HubOption,
    protocol: Optional[str] = ProtocolOption,
    limit: int = LimitOption,
    filter: Optional[List[str]] = FilterOption,
    table: bool = TableOption,
    properties: Optional[str] = PropertiesOption,
):
    """List hub configurations."""
    rows = [get_client().get_config(hub=hub, protocol=protocol)]
    rows = rows[:limit] if limit > 0 else rows
    rows = _filter_and_project(rows, filter, properties)
    _render_rows(rows, table=table, properties=properties, default_columns=["hub", "configuration"])


app.add_typer(hubs_app, name="hubs")
app.add_typer(activities_app, name="activities")
app.add_typer(devices_app, name="devices")
app.add_typer(commands_app, name="commands")
app.add_typer(config_app, name="config")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
