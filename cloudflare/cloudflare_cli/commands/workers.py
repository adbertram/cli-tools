"""Workers commands for Cloudflare CLI.

Account-level Workers script management:
  list    - List scripts in an account
  get     - Download a script's source content
  upload  - Create or replace a script (multipart PUT)
  delete  - Delete a script
"""
import json
from datetime import datetime
from enum import Enum
from typing import Optional

import typer

from ..client import get_client
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import (
    apply_filters,
    apply_properties_filter,
)
from cli_tools_shared.output import (
    print_json,
    print_table,
    command,
    print_success,
    confirm_destructive_action,
)


class WorkerFormat(str, Enum):
    """Supported Worker script upload formats."""

    MODULES = "modules"
    SERVICE_WORKER = "service-worker"


app = typer.Typer(help="Manage Workers scripts", no_args_is_help=True)


def _resolve_account(client, account: Optional[str]) -> str:
    """Resolve the optional account argument to an account ID."""
    if account:
        return client.resolve_account_id(account)
    return client.default_account_id()


def _format_local_timestamp(value) -> str:
    """Render an API ISO timestamp in the local timezone for table display."""
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _parse_bindings(bindings: Optional[str]) -> Optional[list]:
    """Parse the --bindings JSON array, raising ClientError on bad input."""
    if bindings is None:
        return None
    try:
        parsed = json.loads(bindings)
    except json.JSONDecodeError as e:
        raise ClientError(f"Invalid --bindings JSON: {e}")
    if not isinstance(parsed, list):
        raise ClientError("--bindings must be a JSON array of binding objects")
    return parsed


@app.command("list")
@command
def list_scripts(
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of scripts to return"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., id:contains:my-worker)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    List Workers scripts for an account.

    Examples:
        cloudflare workers list
        cloudflare workers list ACCOUNT_NAME --table
        cloudflare workers list --limit 10
        cloudflare workers list --filter "id:contains:cron"
        cloudflare workers list --properties "id,modified_on"
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    scripts = client.list_worker_scripts(account_id=account_id, limit=limit)

    # Apply client-side filters
    if filter_str:
        scripts = apply_filters(scripts, filter_str)

    # Apply properties filter
    if properties:
        scripts = apply_properties_filter(scripts, properties)

    if table:
        flattened = [{
            "id": s.get("id"),
            "created_on": _format_local_timestamp(s.get("created_on")),
            "modified_on": _format_local_timestamp(s.get("modified_on")),
        } for s in scripts]
        print_table(
            flattened,
            ["id", "created_on", "modified_on"],
            ["ID", "Created", "Modified"],
        )
    else:
        print_json(scripts)


@app.command("get")
@command
def get_script(
    script_name: str = typer.Argument(..., help="The worker script name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Write the script content to this file instead of stdout"),
):
    """
    Download a Worker script's source content.

    Examples:
        cloudflare workers get my-worker > worker.js
        cloudflare workers get my-worker my-account --output worker.js
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    content = client.get_worker_script(account_id=account_id, script_name=script_name)

    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(content)
        print_success(f"Wrote {script_name} to {output}")
    else:
        typer.echo(content)


@app.command("upload")
@command
def upload_script(
    script_name: str = typer.Argument(..., help="The worker script name"),
    file: typer.FileText = typer.Option(..., "--file", help="Path to the script source ('-' for stdin)"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    worker_format: WorkerFormat = typer.Option(WorkerFormat.MODULES, "--format", help="Script format"),
    main_module: str = typer.Option("worker.js", "--main-module", help="Entry module filename (modules format)"),
    compatibility_date: Optional[str] = typer.Option(None, "--compatibility-date", help="Compatibility date (YYYY-MM-DD)"),
    bindings: Optional[str] = typer.Option(None, "--bindings", help='JSON array of bindings (e.g. \'[{"type":"plain_text","name":"TITLE","text":"hi"}]\')'),
):
    """
    Upload (create or replace) a Worker script.

    Examples:
        cloudflare workers upload my-worker --file ./worker.js
        cloudflare workers upload my-worker --file - < worker.js
        cloudflare workers upload my-worker --file ./worker.js --compatibility-date 2026-01-15
        cloudflare workers upload my-worker --file ./worker.js --format service-worker
    """
    client = get_client()
    account_id = _resolve_account(client, account)
    binding_list = _parse_bindings(bindings)

    result = client.upload_worker_script(
        account_id=account_id,
        script_name=script_name,
        content=file.read(),
        script_format=worker_format.value,
        main_module=main_module,
        bindings=binding_list,
        compatibility_date=compatibility_date,
    )

    print_json(result)
    print_success(f"Uploaded worker script {script_name}")


@app.command("delete")
@command
def delete_script(
    script_name: str = typer.Argument(..., help="The worker script name"),
    account: Optional[str] = typer.Argument(None, help="Account name or ID (defaults to the single visible account)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a Worker script.

    Examples:
        cloudflare workers delete my-worker
        cloudflare workers delete my-worker my-account --force
    """
    client = get_client()
    account_id = _resolve_account(client, account)

    confirm_destructive_action(
        f"Are you sure you want to delete worker script {script_name}?",
        assume_yes=force,
        action_description=f"delete worker script {script_name}",
        skip_flag_hint="--force",
    )

    result = client.delete_worker_script(account_id, script_name)

    deleted_id = result.get("id", script_name)
    print_success(f"Deleted worker script {deleted_id}")


routes_app = typer.Typer(help="Manage zone Worker routes", no_args_is_help=True)


@routes_app.command("list")
@command
def list_routes(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of routes to return"),
    filter_str: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., script:eq:my-worker)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """
    List Worker routes for a zone.

    Examples:
        cloudflare workers routes list example.com
        cloudflare workers routes list example.com --table
        cloudflare workers routes list example.com --filter "script:eq:my-worker"
        cloudflare workers routes list example.com --properties "id,pattern,script"
    """
    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    routes = client.list_worker_routes(zone_id=zone_id)

    # Apply client-side filters
    if filter_str:
        routes = apply_filters(routes, filter_str)

    routes = routes[:limit]

    # Apply properties filter
    if properties:
        routes = apply_properties_filter(routes, properties)

    if table:
        flattened = [{
            "id": r.get("id"),
            "pattern": r.get("pattern"),
            "script": r.get("script"),
        } for r in routes]
        print_table(
            flattened,
            ["id", "pattern", "script"],
            ["ID", "Pattern", "Script"],
        )
    else:
        print_json(routes)


@routes_app.command("get")
@command
def get_route(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    route_id: str = typer.Argument(..., help="The route ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as key-value table"),
):
    """
    Get a single Worker route for a zone.

    Examples:
        cloudflare workers routes get example.com <route-id>
        cloudflare workers routes get example.com <route-id> --table
    """
    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    route = client.get_worker_route(zone_id=zone_id, route_id=route_id)

    if table:
        rows = []
        for k, v in route.items():
            if v is not None:
                rows.append({"field": k, "value": str(v)})
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(route)


@routes_app.command("create")
@command
def create_route(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    pattern: str = typer.Option(..., "--pattern", help="Route pattern (e.g. 'example.com/llms.txt*')"),
    script: str = typer.Option(..., "--script", help="Worker script name to invoke for matching requests"),
):
    """
    Create a Worker route binding a URL pattern to a script.

    Examples:
        cloudflare workers routes create example.com --pattern 'example.com/llms.txt*' --script my-worker
    """
    client = get_client()
    zone_id = client.resolve_zone_id(zone)
    result = client.create_worker_route(zone_id=zone_id, pattern=pattern, script=script)
    print_json(result)
    print_success(f"Created route {pattern} -> {script}")


@routes_app.command("delete")
@command
def delete_route(
    zone: str = typer.Argument(..., help="Zone name or ID"),
    route_id: str = typer.Argument(..., help="The route ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Delete a Worker route.

    Examples:
        cloudflare workers routes delete example.com <route-id> --force
    """
    client = get_client()
    zone_id = client.resolve_zone_id(zone)

    confirm_destructive_action(
        f"Are you sure you want to delete worker route {route_id}?",
        assume_yes=force,
        action_description=f"delete worker route {route_id}",
        skip_flag_hint="--force",
    )

    client.delete_worker_route(zone_id=zone_id, route_id=route_id)
    print_success(f"Deleted worker route {route_id}")


app.add_typer(routes_app, name="routes")


COMMAND_CREDENTIALS = {
    "list": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "upload": [
        "api_key"
    ],
    "delete": [
        "api_key"
    ],
    "routes": [
        "api_key"
    ]
}
