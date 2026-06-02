"""DNS commands for Cloudflare CLI.

Subgroups:
  zones   - List and get zones (read-only)
  records - Full CRUD for DNS records
"""
import typer
from typing import Optional
from enum import Enum

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
)
from cli_tools_shared.output import print_json, print_table, handle_error, print_success


class DNSRecordType(str, Enum):
    """Supported DNS record types."""

    A = "A"
    AAAA = "AAAA"
    CAA = "CAA"
    CNAME = "CNAME"
    MX = "MX"
    NS = "NS"
    PTR = "PTR"
    SRV = "SRV"
    TXT = "TXT"


# Top-level dns group
app = typer.Typer(help="Manage DNS zones and records", no_args_is_help=True)

# Subgroups
zones_app = typer.Typer(help="List and inspect DNS zones", no_args_is_help=True)
records_app = typer.Typer(help="Manage DNS records", no_args_is_help=True)

app.add_typer(zones_app, name="zones")
app.add_typer(records_app, name="records")


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


# ==================== Zones (read-only) ====================


@zones_app.command("list")
def zones_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of zones to return (max 50)"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Filter by zone name"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (active, pending, etc.)"),
):
    """
    List DNS zones.

    Examples:
        cloudflare dns zones list
        cloudflare dns zones list --table
        cloudflare dns zones list --name example.com
        cloudflare dns zones list --filter "status:eq:active"
        cloudflare dns zones list --properties "id,name"
    """
    try:
        client = get_client()
        filters = []
        if name:
            filters.append(f"name:{name}")
        if status:
            filters.append(f"status:{status}")

        zones = client.list_zones(limit=limit, filters=filters if filters else None)

        # Convert to dicts for filtering
        zone_dicts = []
        for z in zones:
            data = model_to_dict(z)
            s = data.get("status")
            if hasattr(s, "value"):
                data["status"] = s.value
            zone_dicts.append(data)

        # Apply client-side filters
        if filter_str:
            zone_dicts = apply_filters(zone_dicts, filter_str)

        # Apply properties filter
        if properties:
            zone_dicts = apply_properties_filter(zone_dicts, properties)

        if table:
            flattened = [{
                "id": d.get("id"),
                "name": d.get("name"),
                "status": d.get("status"),
            } for d in zone_dicts]
            print_table(
                flattened,
                ["id", "name", "status"],
                ["ID", "Name", "Status"],
            )
        else:
            print_json(zone_dicts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@zones_app.command("get")
def zones_get(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as key-value table"),
):
    """
    Get details for a specific DNS zone.

    Examples:
        cloudflare dns zones get ZONE_ID
        cloudflare dns zones get ZONE_ID --table
    """
    try:
        client = get_client()
        zone = client.get_zone(zone_id)

        if table:
            zone_dict = model_to_dict(zone)
            rows = []
            for k, v in zone_dict.items():
                if v is not None:
                    rows.append({"field": k, "value": str(v)})
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(zone)

    except Exception as e:
        raise typer.Exit(handle_error(e))


# ==================== Records ====================


def flatten_record_for_table(record) -> dict:
    """Flatten a DNS record for table display."""
    data = model_to_dict(record)
    record_type = data.get("type")
    if hasattr(record_type, "value"):
        record_type = record_type.value
    return {
        "id": data.get("id"),
        "type": record_type,
        "name": data.get("name"),
        "content": data.get("content"),
        "ttl": data.get("ttl"),
        "proxied": "Yes" if data.get("proxied") else "No",
    }


@records_app.command("list")
def records_list(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of records to return (max 5000)"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", help="Comma-separated fields to display"),
    record_type: Optional[DNSRecordType] = typer.Option(None, "--type", help="Filter by record type"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Filter by exact name match"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="Filter by content match"),
    proxied_filter: Optional[bool] = typer.Option(None, "--proxied", "-p", help="Filter by proxied status"),
):
    """
    List DNS records for a zone.

    Examples:
        cloudflare dns records list ZONE_ID
        cloudflare dns records list ZONE_ID --table
        cloudflare dns records list ZONE_ID --type TXT
        cloudflare dns records list ZONE_ID --filter "type:eq:A"
        cloudflare dns records list ZONE_ID --properties "id,name,content"
    """
    try:
        client = get_client()
        records = client.list_dns_records(
            zone_id=zone_id,
            limit=limit,
            record_type=record_type.value if record_type else None,
            name=name,
            content=content,
            proxied=proxied_filter,
        )

        # Convert to dicts for filtering
        record_dicts = [model_to_dict(r) for r in records]
        for d in record_dicts:
            t = d.get("type")
            if hasattr(t, "value"):
                d["type"] = t.value

        # Apply client-side filters
        if filter_str:
            record_dicts = apply_filters(record_dicts, filter_str)

        # Apply properties filter
        if properties:
            record_dicts = apply_properties_filter(record_dicts, properties)

        if table:
            flattened = [{
                "id": d.get("id"),
                "type": d.get("type"),
                "name": d.get("name"),
                "content": d.get("content"),
                "ttl": d.get("ttl"),
                "proxied": "Yes" if d.get("proxied") else "No",
            } for d in record_dicts]
            print_table(
                flattened,
                ["id", "type", "name", "content", "ttl", "proxied"],
                ["ID", "Type", "Name", "Content", "TTL", "Proxied"],
            )
        else:
            print_json(record_dicts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@records_app.command("get")
def records_get(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    record_id: str = typer.Argument(..., help="The record ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as key-value table"),
):
    """
    Get details for a specific DNS record.

    Examples:
        cloudflare dns records get ZONE_ID RECORD_ID
        cloudflare dns records get ZONE_ID RECORD_ID --table
    """
    try:
        client = get_client()
        record = client.get_dns_record(zone_id, record_id)

        if table:
            record_dict = model_to_dict(record)
            rows = []
            for k, v in record_dict.items():
                if v is not None:
                    rows.append({"field": k, "value": str(v)})
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(record)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@records_app.command("create")
def records_create(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    record_type: DNSRecordType = typer.Option(..., "--type", "-T", help="Record type (A, AAAA, CNAME, TXT, MX, etc.)"),
    name: str = typer.Option(..., "--name", "-n", help="Record name (e.g., example.com, subdomain.example.com)"),
    content: str = typer.Option(..., "--content", "-c", help="Record content (IP, hostname, text, etc.)"),
    ttl: int = typer.Option(1, "--ttl", help="TTL in seconds (1 = auto, 60-86400 for custom)"),
    proxied: bool = typer.Option(False, "--proxied", "-p", help="Proxy through Cloudflare (A/AAAA/CNAME only)"),
    priority: Optional[int] = typer.Option(None, "--priority", help="Priority (for MX/SRV records)"),
    comment: Optional[str] = typer.Option(None, "--comment", help="Optional comment"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Create a new DNS record.

    Examples:
        cloudflare dns records create ZONE_ID --type A --name example.com --content 1.2.3.4
        cloudflare dns records create ZONE_ID --type A --name example.com --content 1.2.3.4 --proxied
        cloudflare dns records create ZONE_ID --type CNAME --name www.example.com --content example.com
        cloudflare dns records create ZONE_ID --type TXT --name example.com --content "v=spf1 include:_spf.google.com ~all"
        cloudflare dns records create ZONE_ID --type MX --name example.com --content mail.example.com --priority 10
    """
    try:
        client = get_client()
        record = client.create_dns_record(
            zone_id=zone_id,
            record_type=record_type.value,
            name=name,
            content=content,
            ttl=ttl,
            proxied=proxied,
            priority=priority,
            comment=comment,
        )

        if table:
            flattened = flatten_record_for_table(record)
            print_table(
                [flattened],
                ["id", "type", "name", "content", "ttl", "proxied"],
                ["ID", "Type", "Name", "Content", "TTL", "Proxied"],
            )
        else:
            print_json(record)

        print_success(f"Created {record_type.value} record: {name} -> {content}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@records_app.command("update")
def records_update(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    record_id: str = typer.Argument(..., help="The record ID"),
    record_type: Optional[DNSRecordType] = typer.Option(None, "--type", "-T", help="New record type"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="New record name"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="New content"),
    ttl: Optional[int] = typer.Option(None, "--ttl", help="New TTL"),
    proxied: Optional[bool] = typer.Option(None, "--proxied", "-p", help="New proxied status"),
    priority: Optional[int] = typer.Option(None, "--priority", help="New priority"),
    comment: Optional[str] = typer.Option(None, "--comment", help="New comment"),
):
    """
    Update a DNS record.

    Examples:
        cloudflare dns records update ZONE_ID RECORD_ID --content 5.6.7.8
        cloudflare dns records update ZONE_ID RECORD_ID --proxied true
        cloudflare dns records update ZONE_ID RECORD_ID --ttl 3600 --comment "Updated"
    """
    if all(v is None for v in [record_type, name, content, ttl, proxied, priority, comment]):
        typer.echo("Error: At least one field to update must be specified", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        record = client.update_dns_record(
            zone_id=zone_id,
            record_id=record_id,
            record_type=record_type.value if record_type else None,
            name=name,
            content=content,
            ttl=ttl,
            proxied=proxied,
            priority=priority,
            comment=comment,
        )

        print_json(record)
        print_success(f"Updated DNS record {record_id}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@records_app.command("delete")
def records_delete(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    record_id: str = typer.Argument(..., help="The record ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a DNS record.

    Examples:
        cloudflare dns records delete ZONE_ID RECORD_ID
        cloudflare dns records delete ZONE_ID RECORD_ID --force
    """
    if not force:
        try:
            client = get_client()
            record = client.get_dns_record(zone_id, record_id)
            typer.echo(f"Record: {record.type} {record.name} -> {record.content}")
        except Exception:
            pass

        confirmed = typer.confirm(f"Are you sure you want to delete record {record_id}?")
        if not confirmed:
            typer.echo("Cancelled")
            raise typer.Exit(0)

    try:
        client = get_client()
        result = client.delete_dns_record(zone_id, record_id)

        deleted_id = result.get("id", record_id)
        print_success(f"Deleted DNS record {deleted_id}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "records": [
        "api_key"
    ],
    "zones": [
        "api_key"
    ]
}
