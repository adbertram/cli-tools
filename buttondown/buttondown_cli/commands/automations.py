"""Automation commands."""
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

from pathlib import Path
from typing import List, Optional

import typer

from cli_tools_shared.output import handle_error

from ..client import get_client
from .common import confirm_delete, emit, parse_json_array, parse_json_object


app = typer.Typer(help="Manage event-driven automations", no_args_is_help=True)


_DEFAULT_COLUMNS = ["id", "name", "status", "trigger", "creation_date"]


@app.command("list")
def automations_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of automations"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List automations."""
    try:
        automations = get_client().list_automations(limit=limit, filters=filter)
        emit(automations, table, properties, _DEFAULT_COLUMNS)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("get")
def automations_get(
    automation_id: str = typer.Argument(..., help="Automation ID (aut_...)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get a single automation."""
    try:
        emit(get_client().get_automation(automation_id), table, properties, _DEFAULT_COLUMNS)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("create")
def automations_create(
    name: str = typer.Option(..., "--name", "-n", help="Automation name"),
    trigger: str = typer.Option(..., "--trigger", help="Trigger event type (e.g. subscriber.confirmed)"),
    actions: str = typer.Option(..., "--actions", "-a", help="Actions JSON array"),
    actions_file: Optional[Path] = typer.Option(None, "--actions-file", help="Read actions JSON array from file"),
    filters: Optional[str] = typer.Option(None, "--filters", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    metadata: Optional[str] = typer.Option(None, "--metadata", help="Metadata JSON object"),
    should_evaluate_filter_after_delay: Optional[bool] = typer.Option(
        None,
        "--reevaluate-filter/--no-reevaluate-filter",
        help="Re-evaluate filter after delay",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Create an automation."""
    try:
        actions_text = actions_file.read_text() if actions_file is not None else actions
        if actions_file is not None and actions:
            raise ValueError("Use either --actions or --actions-file, not both")
        automation = get_client().create_automation(
            name=name,
            trigger=trigger,
            actions=parse_json_array(actions_text, "--actions"),
            filters=parse_json_object(filters, "--filters")
            if filters is not None
            else {"filters": [], "groups": [], "predicate": "and"},
            metadata=parse_json_object(metadata, "--metadata"),
            should_evaluate_filter_after_delay=should_evaluate_filter_after_delay,
        )
        emit(automation, table, properties, _DEFAULT_COLUMNS)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("update")
def automations_update(
    automation_id: str = typer.Argument(..., help="Automation ID (aut_...)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Automation name"),
    trigger: Optional[str] = typer.Option(None, "--trigger", help="Trigger event type"),
    status: Optional[str] = typer.Option(None, "--status", help="Status: active | inactive"),
    actions: Optional[str] = typer.Option(None, "--actions", "-a", help="Actions JSON array"),
    actions_file: Optional[Path] = typer.Option(None, "--actions-file", help="Read actions JSON array from file"),
    filters: Optional[str] = typer.Option(None, "--filters", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    metadata: Optional[str] = typer.Option(None, "--metadata", help="Metadata JSON object"),
    should_evaluate_filter_after_delay: Optional[bool] = typer.Option(
        None,
        "--reevaluate-filter/--no-reevaluate-filter",
        help="Re-evaluate filter after delay",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Update an automation."""
    try:
        actions_text: Optional[str]
        if actions_file is not None and actions is not None:
            raise ValueError("Use either --actions or --actions-file, not both")
        if actions_file is not None:
            actions_text = actions_file.read_text()
        else:
            actions_text = actions
        automation = get_client().update_automation(
            automation_id,
            name=name,
            trigger=trigger,
            status=status,
            actions=parse_json_array(actions_text, "--actions") if actions_text is not None else None,
            filters=parse_json_object(filters, "--filters"),
            metadata=parse_json_object(metadata, "--metadata"),
            should_evaluate_filter_after_delay=should_evaluate_filter_after_delay,
        )
        emit(automation, table, properties, _DEFAULT_COLUMNS)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("delete")
def automations_delete(
    automation_id: str = typer.Argument(..., help="Automation ID (aut_...)"),
    force: bool = typer.Option(False, "--force", "-F", help="Delete without confirmation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Delete an automation."""
    try:
        confirm_delete("automation", automation_id, force)
        emit(get_client().delete_automation(automation_id), table, None, ["ok", "action", "id"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
