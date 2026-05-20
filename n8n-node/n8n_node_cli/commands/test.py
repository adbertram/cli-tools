"""Test command - test an n8n node by executing it in a temporary workflow."""
import time
import uuid
import typer

from ..n8n_api import get_n8n_api_client, N8nApiError
from cli_tools_shared.output import print_json, print_error, print_info, print_success


def _cleanup(api, workflow_id, no_cleanup):
    """Deactivate and optionally delete a workflow."""
    try:
        api.deactivate_workflow(workflow_id)
    except N8nApiError:
        pass
    if not no_cleanup:
        try:
            api.delete_workflow(workflow_id)
        except N8nApiError:
            pass


def test_node(
    node_name: str = typer.Argument(..., help="Name of the n8n node to test (e.g., claudecode)"),
    resource: str = typer.Option(None, "--resource", "-r", help="Resource to test (e.g., order)"),
    operation: str = typer.Option(None, "--operation", "-o", help="Operation to test (e.g., list)"),
    timeout: int = typer.Option(60, "--timeout", "-t", help="Execution timeout in seconds"),
    no_cleanup: bool = typer.Option(False, "--no-cleanup", help="Keep workflow after test (don't delete)"),
    params: str = typer.Option(None, "--params", "-p", help="Extra node parameters as JSON string"),
    credentials: str = typer.Option(None, "--credentials", "-c", help="Node credentials as JSON string, e.g. '{\"claudeCodeApi\":{\"id\":\"abc\",\"name\":\"My Cred\"}}'"),
    node_type: str = typer.Option(None, "--node-type", help="Override full node type (e.g., n8n-nodes-claudecode.claudeCode)"),
):
    """
    Test an n8n node by creating a temporary workflow and executing it.

    Creates a workflow with a Webhook trigger connected to the specified node,
    activates it, triggers via webhook, polls for completion, and verifies success.

    Requires:
    - The n8n node must already be installed on the n8n server
    - n8n API credentials configured with `n8n-node auth login`

    Example:
        n8n-node test claudecode -p '{"prompt":"What is 2+2?","model":"haiku","outputFormat":"text"}'
        n8n-node test brickowl --resource order --operation list --timeout 120
    """
    import json as json_mod

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
        if credentials:
            nodes[1]["credentials"] = json_mod.loads(credentials)
        else:
            try:
                cred_types = api.get_node_credential_types(resolved_node_type)
                if cred_types:
                    all_creds = api.list_credentials()
                    resolved_creds = {}
                    for cred_type in cred_types:
                        matching = [c for c in all_creds if c["type"] == cred_type]
                        if matching:
                            cred = matching[0]
                            resolved_creds[cred_type] = {"id": cred["id"], "name": cred["name"]}
                            print_info(f"Auto-discovered credential: {cred['name']} ({cred_type})")
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
            _cleanup(api, workflow_id, no_cleanup=True)  # Always preserve on failure
            print_info(f"Workflow preserved for debugging: {workflow_id}")
            print_json(result)
            raise typer.Exit(1)

        print_success(f"Test passed! Execution completed in {duration:.2f}s")
        print_json(result)

        _cleanup(api, workflow_id, no_cleanup)
        if not no_cleanup:
            print_info(f"Test workflow deleted: {workflow_id}")
        workflow_id = None

    except N8nApiError as e:
        print_error(str(e))
        if workflow_id:
            _cleanup(api, workflow_id, no_cleanup=True)
            print_info(f"Workflow preserved for debugging: {workflow_id}")
        raise typer.Exit(1)

    except typer.Exit:
        raise

    except Exception as e:
        print_error(f"Unexpected error: {e}")
        if workflow_id:
            _cleanup(api, workflow_id, no_cleanup=True)
            print_info(f"Workflow preserved for debugging: {workflow_id}")
        raise typer.Exit(1)
