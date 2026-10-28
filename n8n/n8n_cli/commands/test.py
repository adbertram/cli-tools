"""Test command - test an n8n node by executing it in a temporary workflow.

Also exposes static health analysis (--workflow mode) that walks an existing
workflow's nodes and reports broken loadOptions, missing required parameters,
deleted credentials, version mismatches, dead webhook paths, and more.
"""
import json as json_mod
import subprocess
import time
import uuid
from typing import List, Optional

import typer

from ..n8n_api import get_n8n_api_client, N8nApiError
from cli_tools_shared.output import (
    print_json, print_error, print_info, print_success, print_warning,
)
from ..server import run_on_server_raw
from .deploy import N8N_NODES_DIR
from .. import health as health_mod


def _check_ui_visibility(package_name: str, node_js_name: str) -> list[str]:
    """Check for known issues that prevent a node from appearing in the n8n UI node picker.

    Inspects the installed node package on the server for patterns that are known
    to cause the node to load via the API but be invisible in the UI search.

    Returns:
        List of warning/error messages. Empty list means no issues found.
    """
    issues = []
    node_module_dir = f"{N8N_NODES_DIR}/node_modules/{package_name}"

    # Check 1: .node.json codex files can interfere with UI node indexing
    find_result = run_on_server_raw(f'sudo find {node_module_dir}/dist -name "*.node.json" 2>/dev/null', timeout=30)
    if find_result.returncode == 0 and find_result.stdout.strip():
        codex_files = find_result.stdout.strip().split('\n')
        issues.append(
            f"Found .node.json codex file(s) that may prevent UI visibility: "
            f"{', '.join(codex_files)}. "
            f"Remove these files — community nodes work without them."
        )

    # Check 2: testedBy in credentials causes silent UI indexing failure
    node_js_path = f"{node_module_dir}/dist/nodes"
    grep_result = run_on_server_raw(f'sudo grep -r "testedBy" {node_js_path}/ 2>/dev/null', timeout=30)
    if grep_result.returncode == 0 and grep_result.stdout.strip():
        issues.append(
            "Node credentials contain 'testedBy' field which can prevent UI visibility. "
            "Remove the testedBy property from the credentials array in the node description."
        )

    return issues


def _cleanup(api, workflow_id, no_cleanup, created_cred_ids=None):
    """Deactivate and optionally delete a workflow and any test-created credentials."""
    try:
        api.deactivate_workflow(workflow_id)
    except N8nApiError:
        pass
    if not no_cleanup:
        try:
            api.delete_workflow(workflow_id)
        except N8nApiError:
            pass
        # Clean up credentials created during test
        for cred_id in (created_cred_ids or []):
            try:
                api.delete_credential(cred_id)
            except N8nApiError:
                pass


def _print_findings_table(findings):
    """Render Findings as a grouped table on stdout (no Rich color noise — we want
    a plain readable layout that grep-s well). Failures rendered red, warns yellow.
    """
    from cli_tools_shared.output import console
    from rich.table import Table
    from rich import box

    if not findings:
        print_success("Health: 0 findings.")
        return

    table = Table(show_header=True, header_style="bold cyan", box=box.HEAVY_HEAD)
    table.add_column("Node")
    table.add_column("Severity")
    table.add_column("Check")
    table.add_column("Message", no_wrap=False)

    for f in findings:
        color = "red" if f.severity == "fail" else "yellow"
        table.add_row(
            f.node,
            f"[{color}]{f.severity}[/{color}]",
            f.check,
            f.message,
        )
    console.print(table)
    fail_count = sum(1 for f in findings if f.severity == "fail")
    warn_count = sum(1 for f in findings if f.severity == "warn")
    summary = f"Health: {fail_count} fail, {warn_count} warn."
    if fail_count:
        print_error(summary)
    elif warn_count:
        print_warning(summary)
    else:
        print_success(summary)


def _emit_findings_json(findings):
    """Emit findings as JSON on stdout, with a top-level summary count."""
    payload = {
        "summary": {
            "total": len(findings),
            "fail": sum(1 for f in findings if f.severity == "fail"),
            "warn": sum(1 for f in findings if f.severity == "warn"),
        },
        "findings": [f.to_dict() for f in findings],
    }
    print_json(payload)


def _run_workflow_health_mode(
    api,
    workflow_id: str,
    node_filter: Optional[str],
    strict: bool,
    as_json: bool,
):
    """Health-check mode: do NOT create/activate/execute anything. Walk an existing
    workflow and report findings.
    """
    try:
        workflow = api.get_workflow(workflow_id)
    except N8nApiError as e:
        print_error(f"Failed to fetch workflow {workflow_id}: {e}")
        raise typer.Exit(1)

    findings = health_mod.run_health_checks(
        workflow,
        api,
        node_name_filter=node_filter,
        strict=strict,
    )
    if as_json:
        _emit_findings_json(findings)
    else:
        _print_findings_table(findings)
    if health_mod.has_failures(findings):
        raise typer.Exit(1)


def test_node(
    node_name: Optional[str] = typer.Argument(
        None,
        help="Name of the n8n node to test (e.g., claudecode). Optional when --workflow is used.",
    ),
    resource: str = typer.Option(None, "--resource", "-r", help="Resource to test (e.g., order)"),
    operation: str = typer.Option(None, "--operation", "-o", help="Operation to test (e.g., list)"),
    timeout: int = typer.Option(60, "--timeout", "-t", help="Execution timeout in seconds"),
    no_cleanup: bool = typer.Option(False, "--no-cleanup", help="Keep workflow after test (don't delete)"),
    params: str = typer.Option(None, "--params", "-p", help="Extra node parameters as JSON string"),
    credentials: str = typer.Option(None, "--credentials", "-c", help="Node credentials as JSON string, e.g. '{\"claudeCodeApi\":{\"id\":\"abc\",\"name\":\"My Cred\"}}'"),
    node_type: str = typer.Option(None, "--node-type", help="Override full node type (e.g., n8n-nodes-claudecode.claudeCode)"),
    username: str = typer.Option(None, "--username", "-u", help="Username for browser automation nodes (required when node uses browser_session credential)"),
    password: str = typer.Option(None, "--password", help="Password for browser automation nodes (required when node uses browser_session credential)"),
    workflow_id: Optional[str] = typer.Option(
        None, "--workflow",
        help="Run static health checks on an existing workflow by ID. Skips temp workflow creation/execution.",
    ),
    node_filter: Optional[str] = typer.Option(
        None, "--node",
        help="In --workflow mode, restrict checks to the node with this exact name.",
    ),
    strict: bool = typer.Option(
        False, "--strict",
        help="In --workflow mode, promote warn-level findings to fail and exit non-zero on any warning.",
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit health findings as JSON (instead of a table).",
    ),
):
    """
    Test an n8n node, or run static health checks on an existing workflow.

    Two modes:

    1. PACKAGE MODE (default): Provide NODE_NAME to test a node package. Creates a
       temporary workflow with a Webhook trigger -> node, activates, triggers, polls
       for completion, and verifies success. Before activation, runs the static
       health-check engine on the temp workflow — config bugs surface immediately
       instead of failing at runtime.

    2. WORKFLOW MODE (--workflow <id>): Runs static health checks on an EXISTING
       workflow. No execution. Validates loadOptions, required params, credentials,
       typeVersion, sub-workflow refs, webhook uniqueness, expression node refs,
       connectivity, and pinData orphans.

    Requires:
    - n8n API credentials configured with `n8n auth login`
    - For package mode: the node package must already be installed on the n8n server

    Example:
        n8n nodes test claudecode -p '{"prompt":"What is 2+2?","model":"haiku","outputFormat":"text"}'
        n8n nodes test brickowl --resource order --operation list --timeout 120
        n8n nodes test --workflow U7cK5XlQqmgG9CWlrB6wM
        n8n nodes test --workflow U7cK5XlQqmgG9CWlrB6wM --node "Incoming Slack Message" --strict --json
    """
    # ---- Workflow-mode short-circuit ----
    if workflow_id:
        api = get_n8n_api_client()
        _run_workflow_health_mode(api, workflow_id, node_filter, strict, as_json)
        return

    if not node_name:
        print_error(
            "NODE_NAME is required in package mode. "
            "Pass a node name, or use --workflow <id> for static health analysis."
        )
        raise typer.Exit(2)

    workflow_id = None
    start_time = time.time()

    try:
        api = get_n8n_api_client()

        # Generate a unique webhook path for this test
        webhook_path = f"test-{uuid.uuid4().hex[:12]}"
        label = f"{resource}/{operation}" if resource and operation else "default"
        workflow_name = f"Test: {node_name} {label}"

        # Resolve the full node type from the server if not overridden
        if node_type:
            resolved_node_type = node_type
        else:
            print_info("Resolving node type from server...")
            resolved_node_type = api.resolve_node_type(node_name)
            if not resolved_node_type:
                resolved_node_type = f"n8n-nodes-{node_name}.{node_name}"
                print_info(f"Node not found on server, using default: {resolved_node_type}")
            else:
                print_info(f"Resolved node type: {resolved_node_type}")

        # Check for known UI visibility issues
        package_name = resolved_node_type.rsplit(".", 1)[0]
        node_js_name = resolved_node_type.rsplit(".", 1)[1] if "." in resolved_node_type else node_name
        try:
            ui_issues = _check_ui_visibility(package_name, node_js_name)
            if ui_issues:
                print_error("Node has issues that prevent it from appearing in the n8n UI:")
                for issue in ui_issues:
                    print_error(f"  - {issue}")
                raise typer.Exit(1)
        except subprocess.TimeoutExpired:
            print_info("Skipping UI visibility check (SSH timeout)")

        # Build node parameters — use lowercase values to match n8n option values
        node_params = {}
        if resource:
            node_params["resource"] = resource.lower()
        if operation:
            node_params["operation"] = operation.lower()
        if params:
            node_params.update(json_mod.loads(params))

        nodes = [
            {
                "id": "webhook-trigger",
                "name": "Webhook Trigger",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 0],
                "parameters": {
                    "path": webhook_path,
                    "httpMethod": "POST",
                    "responseMode": "lastNode",
                },
                "webhookId": webhook_path,
            },
            {
                "id": "node-under-test",
                "name": f"{node_name.capitalize()} Node",
                "type": resolved_node_type,
                "typeVersion": 1,
                "position": [200, 0],
                "parameters": node_params,
            },
        ]

        # Auto-discover credentials if not explicitly provided
        created_cred_ids = []  # Track credentials we create so we can clean up
        if credentials:
            nodes[1]["credentials"] = json_mod.loads(credentials)
        else:
            try:
                cred_types = api.get_node_credential_types(resolved_node_type)
                if cred_types:
                    all_creds = api.list_credentials()
                    resolved_creds = {}
                    for ct in cred_types:
                        matching = [c for c in all_creds if c["type"] == ct]
                        if matching:
                            cred = matching[0]
                            resolved_creds[ct] = {"id": cred["id"], "name": cred["name"]}
                            print_info(f"Auto-discovered credential: {cred['name']} ({ct})")
                        elif "browsersession" in ct.lower():
                            # Browser automation node — require username/password
                            if not username or not password:
                                print_error(
                                    f"Node requires browser session credential '{ct}' but none exists on the server.\n"
                                    f"Provide --username and --password to create one for testing."
                                )
                                raise typer.Exit(1)
                            print_info(f"Creating browser session credential: {ct}")
                            cred_data = {"username": username, "password": password}
                            created = api.create_credential(f"Test {ct}", ct, cred_data)
                            created_cred_ids.append(created["id"])
                            resolved_creds[ct] = {"id": created["id"], "name": created["name"]}
                            print_success(f"Created credential: {created['name']} (id: {created['id']})")
                    if resolved_creds:
                        nodes[1]["credentials"] = resolved_creds
            except N8nApiError:
                pass  # Non-fatal — node may not need credentials or they'll fail at runtime

        connections = {
            "Webhook Trigger": {
                "main": [[{"node": f"{node_name.capitalize()} Node", "type": "main", "index": 0}]]
            }
        }

        # Create and activate workflow
        print_info(f"Creating test workflow: {workflow_name}")
        workflow = api.create_workflow(workflow_name, nodes, connections)
        workflow_id = workflow["id"]
        print_info(f"Workflow created: {workflow_id}")

        # Pre-activation health check: surface config bugs before we waste an activation cycle.
        print_info("Running pre-activation health checks...")
        try:
            preflight = health_mod.run_health_checks(workflow, api)
        except Exception as e:
            print_warning(f"Health check engine errored (continuing): {e}")
            preflight = []
        if preflight:
            _print_findings_table(preflight)
        if health_mod.has_failures(preflight):
            print_error("Pre-activation health check failed — aborting before activation.")
            _cleanup(api, workflow_id, no_cleanup=no_cleanup, created_cred_ids=created_cred_ids)
            raise typer.Exit(1)

        print_info("Activating workflow...")
        api.activate_workflow(workflow_id)

        # Give n8n a moment to register the webhook
        time.sleep(1)

        # Trigger via webhook (may return 500 if node fails — that's expected, we poll for details)
        print_info(f"Triggering webhook: {webhook_path}")
        try:
            webhook_response = api.trigger_webhook(webhook_path, data={"test": True})
        except N8nApiError:
            pass  # Node execution error returns 500 via webhook — poll for details below

        # Poll for execution result
        print_info("Polling for execution result...")
        poll_start = time.time()
        execution = None

        while time.time() - poll_start < timeout:
            executions = api.get_executions(workflow_id=workflow_id, include_data=True, limit=1)
            if executions:
                latest = executions[0]
                status = latest.get("status", "")
                if latest.get("finished") or status in ("success", "error", "crashed"):
                    execution = latest
                    break
            time.sleep(2)

        if not execution:
            raise N8nApiError(f"Execution did not complete within {timeout}s timeout")

        # Extract result data
        execution_id = execution.get("id")
        status = execution.get("status", "unknown")
        duration = time.time() - start_time

        # Get output data from the node under test
        output_data = None
        if execution.get("data") and execution["data"].get("resultData"):
            run_data = execution["data"]["resultData"].get("runData", {})
            for node_key in run_data:
                if node_key != "Webhook Trigger":
                    node_runs = run_data[node_key]
                    if node_runs and node_runs[0].get("data"):
                        main_data = node_runs[0]["data"].get("main", [])
                        if main_data and main_data[0]:
                            output_data = main_data[0]

        # Extract error message if execution failed
        error_message = None
        if execution.get("data") and execution["data"].get("resultData"):
            error_obj = execution["data"]["resultData"].get("error")
            if error_obj and isinstance(error_obj, dict):
                error_message = error_obj.get("message")
                error_extra = error_obj.get("extra")
                if error_extra and error_message:
                    error_message = f"{error_message} (details: {error_extra})"

        result = {
            "workflowId": workflow_id,
            "executionId": execution_id,
            "status": status,
            "duration": round(duration, 2),
            "output": output_data,
        }
        if error_message:
            result["error"] = error_message

        if status != "success":
            detail = f": {error_message}" if error_message else ""
            print_error(f"Execution failed with status: {status}{detail}")
            _cleanup(api, workflow_id, no_cleanup=True, created_cred_ids=created_cred_ids)
            print_info(f"Workflow preserved for debugging: {workflow_id}")
            print_json(result)
            raise typer.Exit(1)

        print_success(f"Test passed! Execution completed in {duration:.2f}s")
        print_json(result)

        _cleanup(api, workflow_id, no_cleanup, created_cred_ids=created_cred_ids)
        if not no_cleanup:
            print_info(f"Test workflow deleted: {workflow_id}")
        workflow_id = None

    except N8nApiError as e:
        print_error(str(e))
        if workflow_id:
            _cleanup(api, workflow_id, no_cleanup=True, created_cred_ids=created_cred_ids)
            print_info(f"Workflow preserved for debugging: {workflow_id}")
        raise typer.Exit(1)

    except typer.Exit:
        raise

    except Exception as e:
        print_error(f"Unexpected error: {e}")
        if workflow_id:
            _cleanup(api, workflow_id, no_cleanup=True, created_cred_ids=created_cred_ids)
            print_info(f"Workflow preserved for debugging: {workflow_id}")
        raise typer.Exit(1)
