"""Cloudflare Email Routing commands.

Subgroups:
  settings  - Zone-scoped enable/disable/status
  rules     - Zone-scoped rules (custom address -> forward/drop action)
  addresses - Account-scoped destination addresses (reusable as forward
              targets across every zone in the account)
"""
COMMAND_CREDENTIALS = {
    "settings": ["api_key"],
    "rules": ["api_key"],
    "addresses": ["api_key"],
}

import json
from typing import Optional

import typer

from ..client import DEFAULT_LIST_LIMIT, get_client
from ..presentation import print_records as _output
from cli_tools_shared.output import command, print_success, confirm_destructive_action


app = typer.Typer(help="Manage Cloudflare Email Routing (settings, rules, destination addresses)", no_args_is_help=True)
settings_app = typer.Typer(help="Zone-level Email Routing enable/disable/status", no_args_is_help=True)
rules_app = typer.Typer(help="Zone-scoped Email Routing rules (custom address -> action)", no_args_is_help=True)
addresses_app = typer.Typer(help="Account-scoped Email Routing destination addresses", no_args_is_help=True)

app.add_typer(settings_app, name="settings")
app.add_typer(rules_app, name="rules")
app.add_typer(addresses_app, name="addresses")

SETTINGS_COLUMNS = ("id", "name", "enabled", "status")
RULE_COLUMNS = ("id", "name", "enabled", "priority")
ADDRESS_COLUMNS = ("id", "email", "verified")


def _account_id(client, account):
    return client.resolve_account_id(account) if account else client.default_account_id()


# ==================== Settings ====================


@settings_app.command("get")
@command
def settings_get(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """Get Email Routing settings (enabled/disabled status) for a zone.

    Examples:
        cloudflare email-routing settings get example.com
        cloudflare email-routing settings get ZONE_ID --table
    """
    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    _output(client.get_email_routing_settings(zone_id), table, properties, SETTINGS_COLUMNS)


@settings_app.command("enable")
@command
def settings_enable(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Enable Email Routing for a zone. Cloudflare adds and locks the MX/SPF records it needs.

    Examples:
        cloudflare email-routing settings enable example.com
    """
    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    result = client.enable_email_routing(zone_id)
    _output(result, table, default_columns=SETTINGS_COLUMNS)
    print_success(f"Enabled Email Routing for zone {zone}")


@settings_app.command("disable")
@command
def settings_disable(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Disable Email Routing for a zone. Cloudflare removes the extra MX records it added.

    Examples:
        cloudflare email-routing settings disable example.com
    """
    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    result = client.disable_email_routing(zone_id)
    _output(result, table, default_columns=SETTINGS_COLUMNS)
    print_success(f"Disabled Email Routing for zone {zone}")


# ==================== Rules ====================


@rules_app.command("list")
@command
def rules_list(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(DEFAULT_LIST_LIMIT, "--limit", "-l", min=0, help="Maximum matching rules; 0 returns all"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Client-side filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
    enabled: Optional[bool] = typer.Option(None, "--enabled", help="Server-side filter by rule enabled status"),
):
    """List Email Routing rules for a zone; filters precede the result limit.

    Examples:
        cloudflare email-routing rules list example.com --limit 0
        cloudflare email-routing rules list ZONE_ID --filter "name:contains:Support" --table
    """
    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    _output(client.list_email_routing_rules(zone_id, limit, filter_str, enabled), table, properties, RULE_COLUMNS)


@rules_app.command("get")
@command
def rules_get(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    rule_id: str = typer.Argument(..., help="Rule ID from rules list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """Get a single Email Routing rule.

    Examples:
        cloudflare email-routing rules get example.com RULE_ID
    """
    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    _output(client.get_email_routing_rule(zone_id, rule_id), table, properties, RULE_COLUMNS)


def _build_matchers(address: Optional[str], catch_all: bool, matchers_json: Optional[str]) -> list[dict]:
    if matchers_json:
        try:
            matchers = json.loads(matchers_json)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"--matchers-json is not valid JSON: {exc}")
        if not isinstance(matchers, list):
            raise typer.BadParameter("--matchers-json must be a JSON array of matcher objects")
        return matchers
    if catch_all:
        return [{"type": "all"}]
    if address:
        return [{"type": "literal", "field": "to", "value": address}]
    raise typer.BadParameter("Specify --address, --catch-all, or --matchers-json")


def _build_actions(forward_to: Optional[str], drop: bool, actions_json: Optional[str]) -> list[dict]:
    if actions_json:
        try:
            actions = json.loads(actions_json)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"--actions-json is not valid JSON: {exc}")
        if not isinstance(actions, list):
            raise typer.BadParameter("--actions-json must be a JSON array of action objects")
        return actions
    if drop:
        return [{"type": "drop"}]
    if forward_to:
        return [{"type": "forward", "value": [forward_to]}]
    raise typer.BadParameter("Specify --forward-to, --drop, or --actions-json")


@rules_app.command("create")
@command
def rules_create(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    address: Optional[str] = typer.Option(None, "--address", "-a", help="Custom address to match, e.g. sales@example.com"),
    catch_all: bool = typer.Option(False, "--catch-all", help="Match every address not matched by a more specific rule"),
    forward_to: Optional[str] = typer.Option(None, "--forward-to", "-d", help="Verified destination address to forward matched mail to"),
    drop: bool = typer.Option(False, "--drop", help="Drop matched mail instead of forwarding"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Rule name/description"),
    priority: Optional[int] = typer.Option(None, "--priority", help="Rule priority (lower runs first)"),
    enabled: Optional[bool] = typer.Option(None, "--enabled/--disabled", help="Create the rule enabled or disabled (default: Cloudflare's default, enabled)"),
    matchers_json: Optional[str] = typer.Option(None, "--matchers-json", help="Raw matchers array JSON; overrides --address/--catch-all"),
    actions_json: Optional[str] = typer.Option(None, "--actions-json", help="Raw actions array JSON; overrides --forward-to/--drop"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """Create an Email Routing rule mapping a custom address to a forward/drop action.

    Forward actions require a destination address that is already verified
    (see 'cloudflare email-routing addresses create/list').

    Examples:
        cloudflare email-routing rules create example.com --address sales@example.com --forward-to me@gmail.com
        cloudflare email-routing rules create example.com --catch-all --drop --name "Catch-all drop"
    """
    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    matchers = _build_matchers(address, catch_all, matchers_json)
    actions = _build_actions(forward_to, drop, actions_json)
    result = client.create_email_routing_rule(zone_id, matchers=matchers, actions=actions, name=name, enabled=enabled, priority=priority)
    _output(result, table, default_columns=RULE_COLUMNS)
    print_success(f"Created Email Routing rule for zone {zone}")


@rules_app.command("update")
@command
def rules_update(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    rule_id: str = typer.Argument(..., help="Rule ID from rules list"),
    address: Optional[str] = typer.Option(None, "--address", "-a", help="New custom address to match"),
    catch_all: bool = typer.Option(False, "--catch-all", help="Match every address not matched by a more specific rule"),
    forward_to: Optional[str] = typer.Option(None, "--forward-to", "-d", help="New verified destination address to forward matched mail to"),
    drop: bool = typer.Option(False, "--drop", help="Drop matched mail instead of forwarding"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="New rule name/description"),
    priority: Optional[int] = typer.Option(None, "--priority", help="New priority (lower runs first)"),
    enabled: Optional[bool] = typer.Option(None, "--enabled/--disabled", help="New enabled status"),
    matchers_json: Optional[str] = typer.Option(None, "--matchers-json", help="Raw matchers array JSON; overrides --address/--catch-all"),
    actions_json: Optional[str] = typer.Option(None, "--actions-json", help="Raw actions array JSON; overrides --forward-to/--drop"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """Update an Email Routing rule. Only the fields provided are changed.

    Examples:
        cloudflare email-routing rules update example.com RULE_ID --disabled
        cloudflare email-routing rules update example.com RULE_ID --forward-to new-dest@example.net
    """
    if all(v in (None, False) for v in [address, catch_all, forward_to, drop, name, priority, enabled, matchers_json, actions_json]):
        typer.echo("Error: At least one field to update must be specified", err=True)
        raise typer.Exit(1)

    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    matchers = _build_matchers(address, catch_all, matchers_json) if (address or catch_all or matchers_json) else None
    actions = _build_actions(forward_to, drop, actions_json) if (forward_to or drop or actions_json) else None
    result = client.update_email_routing_rule(
        zone_id, rule_id, matchers=matchers, actions=actions, name=name, enabled=enabled, priority=priority
    )
    _output(result, table, default_columns=RULE_COLUMNS)
    print_success(f"Updated Email Routing rule {rule_id}")


@rules_app.command("delete")
@command
def rules_delete(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    rule_id: str = typer.Argument(..., help="Rule ID from rules list"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """Delete an Email Routing rule.

    Examples:
        cloudflare email-routing rules delete example.com RULE_ID --force
    """
    confirm_destructive_action(
        f"Are you sure you want to delete Email Routing rule {rule_id}?",
        assume_yes=force,
        action_description=f"delete Email Routing rule {rule_id}",
        skip_flag_hint="--force",
    )

    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    result = client.delete_email_routing_rule(zone_id, rule_id)
    print_success(f"Deleted Email Routing rule {result.get('id', rule_id)}")


# ==================== Destination Addresses (account-scoped) ====================


@addresses_app.command("list")
@command
def addresses_list(
    account: Optional[str] = typer.Argument(None, help="Account name or ID; defaults to the single visible account"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(DEFAULT_LIST_LIMIT, "--limit", "-l", min=0, help="Maximum matching addresses; 0 returns all"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Client-side filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
    verified: Optional[bool] = typer.Option(None, "--verified", help="Server-side filter by verification status"),
):
    """List Email Routing destination addresses for an account; filters precede the result limit.

    Examples:
        cloudflare email-routing addresses list --limit 0
        cloudflare email-routing addresses list ACCOUNT_ID --verified false --table
    """
    client = get_client()
    _output(
        client.list_email_routing_addresses(_account_id(client, account), limit, filter_str, verified),
        table, properties, ADDRESS_COLUMNS,
    )


@addresses_app.command("get")
@command
def addresses_get(
    address_id: str = typer.Argument(..., help="Destination address ID from addresses list"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID; defaults to the single visible account"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
):
    """Get a single Email Routing destination address.

    Examples:
        cloudflare email-routing addresses get ADDRESS_ID ACCOUNT_ID
    """
    client = get_client()
    _output(client.get_email_routing_address(_account_id(client, account), address_id), table, properties, ADDRESS_COLUMNS)


@addresses_app.command("create")
@command
def addresses_create(
    email: str = typer.Argument(..., help="Destination email address to add"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID; defaults to the single visible account"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """Add a destination address with one POST attempt, never replayed.

    Cloudflare emails the address a verification link; it cannot be used as a
    forward target until that link is clicked. There is no documented API
    endpoint to resend the verification email or mark an address verified, so
    this command does not offer that action -- resend from the Cloudflare
    dashboard if the link is lost.

    Examples:
        cloudflare email-routing addresses create me@gmail.com
        cloudflare email-routing addresses create me@gmail.com ACCOUNT_ID
    """
    client = get_client()
    result = client.create_email_routing_address(_account_id(client, account), email)
    _output(result, table, default_columns=ADDRESS_COLUMNS)
    print_success(f"Added destination address {email}; Cloudflare emailed it a verification link")


@addresses_app.command("delete")
@command
def addresses_delete(
    address_id: str = typer.Argument(..., help="Destination address ID from addresses list"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID; defaults to the single visible account"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """Delete an Email Routing destination address.

    Examples:
        cloudflare email-routing addresses delete ADDRESS_ID ACCOUNT_ID --force
    """
    confirm_destructive_action(
        f"Are you sure you want to delete destination address {address_id}?",
        assume_yes=force,
        action_description=f"delete destination address {address_id}",
        skip_flag_hint="--force",
    )

    client = get_client()
    result = client.delete_email_routing_address(_account_id(client, account), address_id)
    print_success(f"Deleted destination address {result.get('id', address_id)}")
