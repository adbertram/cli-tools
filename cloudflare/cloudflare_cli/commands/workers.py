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
    ]
}
