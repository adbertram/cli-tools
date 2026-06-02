"""Workflows commands - list, get, create, update, delete, activate, deactivate, execute, and export n8n workflows."""
import json
import typer
from pathlib import Path
from typing import Optional, List

from ..n8n_api import get_n8n_api_client, N8nApiError, GLOBAL_ERROR_HANDLER_ID
from cli_tools_shared.output import print_json, print_table, print_error, print_success, print_info, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit
from ..parsers import format_local_time
from ..server import run_on_server
from .workflow_nodes import _writable_payload
from .workflow_nodes import app as workflow_nodes_app

app = typer.Typer(help="Manage n8n workflows", no_args_is_help=True)
app.add_typer(workflow_nodes_app, name="node", help="Add and connect nodes in workflows")

COMMAND_CREDENTIALS = {
    "activate": [
        "api_key"
    ],
    "assign-error-handler": [
        "api_key"
    ],
    "create": [
        "api_key"
    ],
    "deactivate": [
        "api_key"
    ],
    "delete": [
        "api_key"
    ],
    "execute": [
        "api_key"
    ],
    "export": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ],
    "node": [
        "api_key"
    ],
    "update": [
        "api_key"
    ]
}


@app.command("list")
def workflows_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    active: Optional[bool] = typer.Option(None, "--active", help="Filter by active status (true/false)"),
):
    """
    List all workflows on the n8n server.

    Examples:
        n8n workflows list
        n8n workflows list --table
        n8n workflows list --active
        n8n workflows list --filter "name:contains:backup"
        n8n workflows list --properties "id,name,active"
    """
    try:
        api = get_n8n_api_client()
        data = api.list_workflows(active=active, limit=limit)

        if filter:
            data = apply_filters(data, filter)

        data = apply_limit(data, limit)

        if properties:
            data = apply_properties_filter(data, properties)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(data, fields, fields)
            else:
                rows = []
                for wf in data:
                    rows.append({
                        "id": wf.get("id"),
                        "name": wf.get("name"),
                        "active": wf.get("active"),
                        "createdAt": format_local_time(wf.get("createdAt", "")),
                        "updatedAt": format_local_time(wf.get("updatedAt", "")),
                    })
                print_table(
                    rows,
                    ["id", "name", "active", "createdAt", "updatedAt"],
                    ["ID", "Name", "Active", "Created", "Updated"],
                )
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def workflows_get(
    workflow_id: str = typer.Argument(..., help="Workflow ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get full details for a specific workflow by ID.

    Example:
        n8n workflows get abc123
        n8n workflows get abc123 --table
    """
    try:
        api = get_n8n_api_client()
        result = api.get_workflow(workflow_id)

        if not result:
            print_error(f"Workflow '{workflow_id}' not found")
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in result.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def workflows_create(
    file: str = typer.Argument(..., help="Path to workflow JSON file"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Override workflow name"),
    activate: bool = typer.Option(False, "--activate", help="Activate the workflow after creation"),
    error_workflow: Optional[str] = typer.Option(
        GLOBAL_ERROR_HANDLER_ID, "--error-workflow",
        help="Error handler workflow ID (default: global handler, use 'none' to skip)",
    ),
):
    """
    Create a workflow from a JSON file.

    The JSON file should contain the workflow definition with nodes and connections.

    Example:
        n8n workflows create workflow.json
        n8n workflows create workflow.json --name "My Workflow"
        n8n workflows create workflow.json --activate
        n8n workflows create workflow.json --error-workflow none
    """
    try:
        path = Path(file)
        if not path.exists():
            print_error(f"File not found: {file}")
            raise typer.Exit(1)

        try:
            workflow_data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON in {file}: {e}")
            raise typer.Exit(1)

        if name:
            workflow_data["name"] = name

        if "name" not in workflow_data:
            print_error("Workflow must have a 'name' field (provide in JSON or use --name)")
            raise typer.Exit(1)

        ew = error_workflow if error_workflow and error_workflow.lower() != "none" else None
        api = get_n8n_api_client()
        result = api.create_workflow(
            name=workflow_data["name"],
            nodes=workflow_data.get("nodes", []),
            connections=workflow_data.get("connections", {}),
            error_workflow=ew,
        )

        workflow_id = result.get("id")
        print_success(f"Created workflow '{result.get('name')}' (id: {workflow_id})")

        if activate and workflow_id:
            api.activate_workflow(workflow_id)
            print_success(f"Activated workflow '{workflow_id}'")

        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def workflows_update(
    workflow_id: str = typer.Argument(..., help="Workflow ID to update"),
    file: Optional[str] = typer.Option(None, "--file", "-f", help="Path to workflow JSON file"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Update workflow name"),
    activate: Optional[bool] = typer.Option(None, "--activate/--deactivate", help="Activate or deactivate the workflow"),
):
    """
    Update an existing workflow.

    Provide a JSON file to replace the workflow definition, and/or use flags
    to update name and active status.

    Example:
        n8n workflows update abc123 --file updated.json
        n8n workflows update abc123 --name "New Name"
        n8n workflows update abc123 --activate
        n8n workflows update abc123 --deactivate
    """
    try:
        api = get_n8n_api_client()

        # Get current workflow to merge with updates
        current = api.get_workflow(workflow_id)
        if not current:
            print_error(f"Workflow '{workflow_id}' not found")
            raise typer.Exit(1)

        update_data = dict(current)

        if file:
            path = Path(file)
            if not path.exists():
                print_error(f"File not found: {file}")
                raise typer.Exit(1)
            try:
                file_data = json.loads(path.read_text())
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON in {file}: {e}")
                raise typer.Exit(1)
            update_data.update(file_data)

        if name:
            update_data["name"] = name

        result = api.update_workflow(workflow_id, _writable_payload(update_data))
        print_success(f"Updated workflow '{result.get('name')}' (id: {workflow_id})")

        # Handle activate/deactivate after update
        if activate is True:
            api.activate_workflow(workflow_id)
            print_success(f"Activated workflow '{workflow_id}'")
        elif activate is False:
            api.deactivate_workflow(workflow_id)
            print_success(f"Deactivated workflow '{workflow_id}'")

        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def workflows_delete(
    workflow_id: str = typer.Argument(..., help="Workflow ID to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """
    Delete a workflow from the n8n server.

    Example:
        n8n workflows delete abc123
        n8n workflows delete abc123 --yes
    """
    try:
        api = get_n8n_api_client()

        if not yes:
            # Show workflow name before confirming
            wf = api.get_workflow(workflow_id)
            if not wf:
                print_error(f"Workflow '{workflow_id}' not found")
                raise typer.Exit(1)
            confirm = typer.confirm(f"Delete workflow '{wf.get('name')}' (id: {workflow_id})?")
            if not confirm:
                print_info("Aborted")
                raise typer.Exit(0)

        result = api.delete_workflow(workflow_id)
        print_success(f"Deleted workflow '{workflow_id}'")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("activate")
def workflows_activate(
    workflow_id: str = typer.Argument(..., help="Workflow ID to activate"),
):
    """
    Activate a workflow.

    Example:
        n8n workflows activate abc123
    """
    try:
        api = get_n8n_api_client()
        result = api.activate_workflow(workflow_id)
        print_success(f"Activated workflow '{result.get('name')}' (id: {workflow_id})")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("deactivate")
def workflows_deactivate(
    workflow_id: str = typer.Argument(..., help="Workflow ID to deactivate"),
):
    """
    Deactivate a workflow.

    Example:
        n8n workflows deactivate abc123
    """
    try:
        api = get_n8n_api_client()
        result = api.deactivate_workflow(workflow_id)
        print_success(f"Deactivated workflow '{result.get('name')}' (id: {workflow_id})")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("export")
def workflows_export(
    workflow_id: str = typer.Argument(..., help="Workflow ID to export"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path (default: stdout)"),
):
    """
    Export a workflow as JSON.

    Exports the full workflow definition including nodes, connections, and settings.

    Example:
        n8n workflows export abc123
        n8n workflows export abc123 -o workflow-backup.json
    """
    try:
        api = get_n8n_api_client()
        result = api.get_workflow(workflow_id)

        if not result:
            print_error(f"Workflow '{workflow_id}' not found")
            raise typer.Exit(1)

        if output:
            path = Path(output)
            path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            print_success(f"Exported workflow '{result.get('name')}' to {output}")
        else:
            print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("execute")
def workflows_execute(
    workflow_id: str = typer.Argument(..., help="Workflow ID to execute"),
):
    """
    Execute a workflow on the n8n server.

    Triggers a manual execution via the internal REST API. Works with any
    workflow regardless of trigger type. Prefers Manual Trigger nodes when
    available, otherwise uses the first trigger node found.

    Examples:
        n8n workflows execute abc123
        n8n workflows execute U7cK5XlQqmgG9CWlrB6wM
    """
    try:
        api = get_n8n_api_client()
        print_info(f"Executing workflow '{workflow_id}'...")
        result = api.execute_workflow(workflow_id)
        data = result.get("data", result)

        if data.get("waitingForWebhook"):
            print_info("Workflow is waiting for webhook input")
        else:
            execution_id = data.get("executionId", "unknown")
            print_success(f"Workflow '{workflow_id}' executed (execution: {execution_id})")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("assign-error-handler")
def workflows_assign_error_handler(
    workflow_id: Optional[str] = typer.Option(None, "--workflow-id", "-w", help="Assign to a single workflow"),
    all_workflows: bool = typer.Option(False, "--all", help="Assign to all workflows"),
    error_workflow_id: str = typer.Option(
        GLOBAL_ERROR_HANDLER_ID, "--error-workflow-id",
        help="Error handler workflow ID to assign",
    ),
):
    """
    Assign an error handler workflow to one or all workflows.

    Sets settings.errorWorkflow so failures trigger the error handler.

    Examples:
        n8n workflows assign-error-handler --all
        n8n workflows assign-error-handler --workflow-id abc123
        n8n workflows assign-error-handler --all --error-workflow-id xyz789
    """
    if not workflow_id and not all_workflows:
        print_error("Specify --workflow-id or --all")
        raise typer.Exit(1)

    try:
        api = get_n8n_api_client()

        if workflow_id:
            targets = [api.get_workflow(workflow_id)]
        else:
            targets = api.list_workflows(limit=500)

        updated = 0
        skipped = 0
        errors = 0

        for wf in targets:
            wf_id = wf.get("id")
            if wf_id == error_workflow_id:
                skipped += 1
                continue

            try:
                full = api.get_workflow(wf_id) if not workflow_id else wf
                if full.get("isArchived"):
                    skipped += 1
                    continue
                settings = full.get("settings") or {}
                if settings.get("errorWorkflow") == error_workflow_id:
                    skipped += 1
                    continue

                settings["errorWorkflow"] = error_workflow_id
                full["settings"] = settings
                api.update_workflow(wf_id, _writable_payload(full))
                updated += 1
            except Exception as e:
                print_error(f"Failed to update {wf_id} ({wf.get('name')}): {e}")
                errors += 1

        print_success(f"Done: {updated} updated, {skipped} skipped, {errors} errors")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
