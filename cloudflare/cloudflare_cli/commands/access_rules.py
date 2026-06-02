"""IP Access Rules commands for Cloudflare CLI."""
import typer
from typing import Optional
from enum import Enum

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.filters import apply_filters, apply_properties_filter
from cli_tools_shared.output import print_json, print_table, handle_error, print_success


class AccessRuleMode(str, Enum):
    """Action to apply to matched requests."""

    WHITELIST = "whitelist"
    BLOCK = "block"
    CHALLENGE = "challenge"
    JS_CHALLENGE = "js_challenge"
    MANAGED_CHALLENGE = "managed_challenge"


class ConfigurationTarget(str, Enum):
    """Target type for access rule configuration."""

    IP = "ip"
    IP_RANGE = "ip_range"
    ASN = "asn"
    COUNTRY = "country"
    IPV6 = "ipv6"


app = typer.Typer(help="Manage IP Access rules (whitelist, block, challenge)", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def flatten_rule_for_table(rule) -> dict:
    """Flatten an access rule for table display."""
    data = model_to_dict(rule)
    mode = data.get("mode")
    target = data.get("configuration", {}).get("target")
    # Extract enum values if present
    if hasattr(mode, "value"):
        mode = mode.value
    if hasattr(target, "value"):
        target = target.value
    return {
        "id": data.get("id"),
        "mode": mode,
        "target": target,
        "value": data.get("configuration", {}).get("value"),
        "notes": data.get("notes") or "",
    }


@app.command("list")
def access_rules_list(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of rules to return (max 50)"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
    mode: Optional[AccessRuleMode] = typer.Option(None, "--mode", "-m", help="Filter by mode"),
    target: Optional[ConfigurationTarget] = typer.Option(None, "--target", help="Filter by target type"),
    value: Optional[str] = typer.Option(None, "--value", help="Filter by configuration value"),
):
    """
    List IP Access rules for a zone.

    Examples:
        cloudflare access-rules list ZONE_ID
        cloudflare access-rules list ZONE_ID --table
        cloudflare access-rules list ZONE_ID --mode whitelist
        cloudflare access-rules list ZONE_ID --filter "mode:eq:block"
        cloudflare access-rules list ZONE_ID --properties "id,mode,notes"
    """
    try:
        client = get_client()
        rules = client.list_access_rules(
            zone_id=zone_id,
            limit=limit,
            mode=mode.value if mode else None,
            target=target.value if target else None,
            value=value,
        )

        # Convert to dicts for filtering
        rule_dicts = [flatten_rule_for_table(r) for r in rules]

        # Apply client-side filters
        if filter_str:
            rule_dicts = apply_filters(rule_dicts, filter_str)

        # Apply properties filter
        if properties:
            rule_dicts = apply_properties_filter(rule_dicts, properties)

        if table:
            print_table(
                rule_dicts,
                ["id", "mode", "target", "value", "notes"],
                ["ID", "Mode", "Target", "Value", "Notes"],
            )
        else:
            print_json(rule_dicts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def access_rules_get(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    rule_id: str = typer.Argument(..., help="The rule ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as key-value table"),
):
    """
    Get details for a specific IP Access rule.

    Examples:
        cloudflare access-rules get ZONE_ID RULE_ID
        cloudflare access-rules get ZONE_ID RULE_ID --table
    """
    try:
        client = get_client()
        rule = client.get_access_rule(zone_id, rule_id)

        if table:
            # Convert model to key-value table
            rule_dict = model_to_dict(rule)
            rows = []
            for k, v in rule_dict.items():
                if v is not None:
                    if isinstance(v, dict):
                        # Flatten nested dicts
                        for nested_k, nested_v in v.items():
                            rows.append({"field": f"{k}.{nested_k}", "value": str(nested_v)})
                    else:
                        rows.append({"field": k, "value": str(v)})
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(rule)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def access_rules_create(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    target: ConfigurationTarget = typer.Option(..., "--target", "-t", help="Target type (ip, ip_range, asn, country, ipv6)"),
    value: str = typer.Option(..., "--value", "-v", help="Target value (IP, CIDR, ASN, country code)"),
    mode: AccessRuleMode = typer.Option(..., "--mode", "-m", help="Action mode (whitelist, block, challenge, js_challenge, managed_challenge)"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Optional notes/description"),
    table: bool = typer.Option(False, "--table", help="Display result as table"),
):
    """
    Create a new IP Access rule.

    Examples:
        cloudflare access-rules create ZONE_ID --target ip --value 1.2.3.4 --mode whitelist
        cloudflare access-rules create ZONE_ID --target ip_range --value 10.0.0.0/8 --mode whitelist --notes "Internal network"
        cloudflare access-rules create ZONE_ID --target asn --value AS12345 --mode block
        cloudflare access-rules create ZONE_ID --target country --value CN --mode challenge
    """
    try:
        client = get_client()
        rule = client.create_access_rule(
            zone_id=zone_id,
            target=target.value,
            value=value,
            mode=mode.value,
            notes=notes,
        )

        if table:
            flattened = flatten_rule_for_table(rule)
            print_table(
                [flattened],
                ["id", "mode", "target", "value", "notes"],
                ["ID", "Mode", "Target", "Value", "Notes"],
            )
        else:
            print_json(rule)

        print_success(f"Created access rule {rule.id}: {mode.value} {target.value}={value}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def access_rules_update(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    rule_id: str = typer.Argument(..., help="The rule ID"),
    mode: Optional[AccessRuleMode] = typer.Option(None, "--mode", "-m", help="New action mode"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="New notes/description"),
):
    """
    Update an IP Access rule.

    Examples:
        cloudflare access-rules update ZONE_ID RULE_ID --mode challenge
        cloudflare access-rules update ZONE_ID RULE_ID --notes "Updated description"
        cloudflare access-rules update ZONE_ID RULE_ID --mode block --notes "Banned"
    """
    if mode is None and notes is None:
        typer.echo("Error: At least one of --mode or --notes must be specified", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        rule = client.update_access_rule(
            zone_id=zone_id,
            rule_id=rule_id,
            mode=mode.value if mode else None,
            notes=notes,
        )

        print_json(rule)
        print_success(f"Updated access rule {rule_id}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def access_rules_delete(
    zone_id: str = typer.Argument(..., help="The zone ID"),
    rule_id: str = typer.Argument(..., help="The rule ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete an IP Access rule.

    Examples:
        cloudflare access-rules delete ZONE_ID RULE_ID
        cloudflare access-rules delete ZONE_ID RULE_ID --force
    """
    if not force:
        # Show rule details before confirmation
        try:
            client = get_client()
            rule = client.get_access_rule(zone_id, rule_id)
            typer.echo(f"Rule: {rule.mode} {rule.configuration.target}={rule.configuration.value}")
            if rule.notes:
                typer.echo(f"Notes: {rule.notes}")
        except Exception:
            pass

        confirmed = typer.confirm(f"Are you sure you want to delete rule {rule_id}?")
        if not confirmed:
            typer.echo("Cancelled")
            raise typer.Exit(0)

    try:
        client = get_client()
        result = client.delete_access_rule(zone_id, rule_id)

        deleted_id = result.get("id", rule_id)
        print_success(f"Deleted access rule {deleted_id}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "api_key"
    ],
    "delete": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "update": [
        "api_key"
    ]
}
