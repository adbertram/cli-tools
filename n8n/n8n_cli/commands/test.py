"""Test command - test an n8n node by executing it in a temporary workflow.

Also exposes static health analysis (--workflow mode) that walks an existing
workflow's nodes and reports broken loadOptions, missing required parameters,
deleted credentials, version mismatches, dead webhook paths, and more.
"""
import json as json_mod
import re
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


# A compiled credential-test method shows up as
#
#     async haloPSAApiCredentialTest(credential) {          // methods.credentialTest inline
#     async function oracleDBConnectionTest(credential) {   // sibling methods/ module,
#     exports.oracleDBConnectionTest = oracleDBConnectionTest;  //   pulled in by the node
#     postgresConnectionTest: credentialTest_1.postgres,    //     map key of an import
#
# while the binding that names it reads `testedBy: 'haloPSAApiCredentialTest'`.
# A definition is searched for by NAME, so the pattern stays small even on a
# package the size of `n8n-nodes-base` (429 nodes, 38 bindings).
def _definition_patterns(name: str) -> tuple[re.Pattern, ...]:
    escaped = re.escape(name)
    return (
        re.compile(rf"^\s*(?:async\s+)?function\s+{escaped}\s*\("),
        re.compile(rf"^\s*(?:async\s+)?{escaped}\s*[:(]"),
        re.compile(rf"^exports\.{escaped}\b"),
        re.compile(rf"^\s*(?:const|let|var)\s+{escaped}\s*="),
        re.compile(rf"^\s*{escaped}\s*=[^=]"),
    )


def _definition_scan_pattern(names) -> str:
    """POSIX ERE matching any line that defines one of `names`."""
    group = "|".join(re.escape(name) for name in sorted(names))
    return (
        "^(async[[:space:]]+)?function[[:space:]]+({n})[[:space:]]*\\("
        "|^[[:space:]]*(async[[:space:]]+)?({n})[[:space:]]*[:(]"
        "|^exports\\.({n})\\b"
        "|^[[:space:]]*(const|let|var)[[:space:]]+({n})[[:space:]]*="
        "|^[[:space:]]*({n})[[:space:]]*=[^=]"
    ).format(n=group)


# Both scans read the package's compiled NODE modules only, delivery-side `.js`
# only: a `.node.json` codex file is supported metadata that n8n itself ships
# hundreds of, a source map embeds whole files on one line, and a `.d.ts`
# declares what the `.js` beside it already defines. The patterns go to the
# server inside single quotes because they carry a `$` the shell would expand.
_BINDING_SCAN_COMMAND = (
    "sudo grep -rhE --include='*.js' 'testedBy' {nodes_dir} 2>/dev/null"
)
_DEFINITION_SCAN_COMMAND = (
    "sudo grep -rhE --include='*.js' '{pattern}' {nodes_dir} 2>/dev/null"
)
_TESTED_BY_RE = re.compile(r"""testedBy\s*:\s*['"]([^'"]+)['"]""")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][\w$]*$")


def _scan_installed_package(package_name: str) -> tuple[set[str], set[str]]:
    """Read the installed package's compiled JS for credential-test bindings.

    Returns `(bindings, defined)`: every method name a `testedBy` string binds
    to, and the ones the package defines a method for.
    """
    nodes_dir = f"{N8N_NODES_DIR}/node_modules/{package_name}/dist/nodes"
    binding_scan = run_on_server_raw(_BINDING_SCAN_COMMAND.format(nodes_dir=nodes_dir), timeout=30)

    bindings: set[str] = set()
    for line in binding_scan.stdout.splitlines():
        bindings.update(_TESTED_BY_RE.findall(line))
    if not bindings:
        return set(), set()

    # Only an identifier can name a method, and only an identifier goes into the
    # pattern built below. A binding that is neither is left out of the search, so
    # it comes back as one that cannot resolve.
    searchable = sorted(name for name in bindings if _IDENTIFIER_RE.match(name))
    if not searchable:
        return bindings, set()

    definition_scan = run_on_server_raw(
        _DEFINITION_SCAN_COMMAND.format(
            pattern=_definition_scan_pattern(searchable), nodes_dir=nodes_dir,
        ),
        timeout=30,
    )
    defined = {
        name
        for line in definition_scan.stdout.splitlines()
        for name in searchable
        if any(pattern.match(line) for pattern in _definition_patterns(name))
    }
    return bindings, defined


def _check_credential_test_bindings(package_name: str) -> list[str]:
    """Report the credential-test bindings that cannot resolve.

    n8n resolves a string `testedBy` against the node's own `methods.credentialTest`
    map (`CredentialsTester.getCredentialTestFunction`), so a binding whose method
    the package never defines can never resolve and credential testing answers
    "No testing function found for this credential." That dangling case is the
    only thing reported here: `testedBy` itself is a supported field of the
    credentials entry (it is what makes n8n show a credential test), so neither it
    nor the `.node.json` codex metadata beside a node blocks testing.

    Returns:
        List of messages, one per dangling binding. Empty list means the package's
        bindings all resolve.
    """
    bindings, defined = _scan_installed_package(package_name)

    return [
        f"Credential test binding 'testedBy: {name}' names a method that "
        f"{package_name} defines nowhere, so n8n cannot resolve it on this node — a "
        f"string testedBy is looked up in the node's own methods.credentialTest map, "
        f"and its credential test then falls through to whichever other node declares "
        f"one. Define the method, or drop testedBy from the credentials entry."
        for name in sorted(bindings - defined)
    ]


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

        # Report a credential-test binding the package cannot resolve. The
        # `testedBy` field and the `.node.json` codex metadata beside a node are
        # both supported parts of an n8n package, so only a dangling binding is
        # worth a word — and because that affects one node's credential test and
        # not the node's execution, it never blocks the test run.
        package_name = resolved_node_type.rsplit(".", 1)[0]
        try:
            binding_issues = _check_credential_test_bindings(package_name)
            if binding_issues:
                print_warning("Node has credential-test bindings that cannot resolve:")
                for issue in binding_issues:
                    print_warning(f"  - {issue}")
        except subprocess.TimeoutExpired:
            print_info("Skipping credential-test binding check (SSH timeout)")

        # Build node parameters. n8n matches `resource` and `operation` against the
        # node schema's option values by exact string equality, so the requested
        # values are transmitted verbatim — never lowercased. A value the schema
        # does not declare is caught by the pre-activation health check below
        # (`option_values_exact`) instead of being silently rewritten.
        node_params = {}
        if resource:
            node_params["resource"] = resource
        if operation:
            node_params["operation"] = operation
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
