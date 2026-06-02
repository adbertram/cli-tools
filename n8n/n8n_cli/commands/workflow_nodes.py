"""Workflow node commands - add and connect nodes within workflows."""
import json
import uuid
import typer
from typing import Optional

from ..n8n_api import get_n8n_api_client, parse_node_resources, N8nApiError
from cli_tools_shared.output import print_json, print_table, print_error, print_success, print_info, handle_error

app = typer.Typer(help="Add and connect nodes in workflows", no_args_is_help=True)

# Fields accepted by the n8n PUT /workflows/{id} endpoint
_WRITABLE_FIELDS = {"name", "nodes", "connections", "settings", "staticData"}

# Settings properties allowed by the n8n API (additionalProperties: false)
_ALLOWED_SETTINGS = {
    "saveExecutionProgress", "saveManualExecutions", "saveDataErrorExecution",
    "saveDataSuccessExecution", "executionTimeout", "errorWorkflow", "timezone",
    "executionOrder", "callerPolicy", "callerIds", "timeSavedPerExecution",
    "availableInMCP",
}


def _writable_payload(workflow: dict) -> dict:
    """Return a copy of the workflow dict with only writable fields for PUT."""
    payload = {k: v for k, v in workflow.items() if k in _WRITABLE_FIELDS}
    if "settings" in payload and isinstance(payload["settings"], dict):
        payload["settings"] = {
            k: v for k, v in payload["settings"].items() if k in _ALLOWED_SETTINGS
        }
    return payload


def _find_node_by_name(nodes: list, name: str) -> Optional[dict]:
    """Find a node in a workflow's node list by display name."""
    for node in nodes:
        if node.get("name") == name:
            return node
    return None


def _get_rightmost_x(nodes: list) -> int:
    """Get the rightmost X position from all nodes."""
    if not nodes:
        return 0
    return max(n.get("position", [0, 0])[0] for n in nodes)


def _get_downstream_nodes(workflow: dict, source_name: str) -> list:
    """Get names of all nodes connected downstream from source_name (BFS)."""
    connections = workflow.get("connections", {})
    visited = set()
    queue = [source_name]

    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        if current in connections:
            for output_group in connections[current].get("main", []):
                for conn in output_group:
                    queue.append(conn["node"])

    visited.discard(source_name)
    return list(visited)


def _shift_nodes_right(nodes: list, node_names: list, amount: int = 200):
    """Shift specified nodes to the right by amount pixels."""
    for node in nodes:
        if node.get("name") in node_names:
            pos = node.get("position", [0, 0])
            node["position"] = [pos[0] + amount, pos[1]]


def _auto_resolve_credentials(api, node_def: dict) -> dict:
    """Match node credential types against available credentials on the server.

    Returns:
        Dict mapping credential type names to {"id": ..., "name": ...}
    """
    cred_types = node_def.get("credentials", [])
    if not cred_types:
        return {}

    try:
        server_creds = api.list_credentials()
    except N8nApiError:
        return {}

    result = {}
    for cred_spec in cred_types:
        if not isinstance(cred_spec, dict):
            continue
        cred_type_name = cred_spec.get("name", "")
        # Find a matching credential on the server
        for sc in server_creds:
            if sc.get("type") == cred_type_name:
                result[cred_type_name] = {"id": sc["id"], "name": sc["name"]}
                break

    return result


@app.command("add")
def node_add(
    workflow_id: str = typer.Argument(..., help="Workflow ID"),
    node_type: str = typer.Argument(..., help="Node type name (e.g., 'slack', 'n8n-nodes-base.slack')"),
    resource: Optional[str] = typer.Option(None, "--resource", "-r", help="Pre-set the resource parameter"),
    operation: Optional[str] = typer.Option(None, "--operation", "-o", help="Pre-set the operation parameter"),
    after: Optional[str] = typer.Option(None, "--after", help="Connect after this node (by display name)"),
    between: Optional[str] = typer.Option(None, "--between", help="Insert between two nodes: 'NodeA,NodeB'"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Custom display name for the node"),
    params: Optional[str] = typer.Option(None, "--params", help="Additional parameters as JSON string"),
    position: Optional[str] = typer.Option(None, "--position", help="Manual position as 'x,y'"),
    credential: Optional[str] = typer.Option(None, "--credential", "-c", help="Credential name or ID to attach to the node"),
):
    """
    Add a node to an existing workflow.

    Resolves the node type from the server, auto-positions it, and optionally
    connects it to existing nodes.

    Examples:
        n8n workflows node add WF_ID slack -r message -o post --after "Manual Trigger"
        n8n workflows node add WF_ID slack --between "HTTP Request,Set Fields"
        n8n workflows node add WF_ID airtable --name "Read Records" --params '{"baseId":"app123"}'
        n8n workflows node add WF_ID emailReadImap --credential "Example IMAP"
    """
    try:
        api = get_n8n_api_client()

        # 1. Get the workflow
        workflow = api.get_workflow(workflow_id)
        if not workflow:
            print_error(f"Workflow '{workflow_id}' not found")
            raise typer.Exit(1)

        nodes = workflow.get("nodes", [])
        connections = workflow.get("connections", {})

        # 2. Resolve node type from server
        node_def = api.get_node_definition(node_type)
        if not node_def:
            print_error(f"No node found matching '{node_type}'")
            raise typer.Exit(1)

        full_type = node_def.get("name", "")
        display_name = name or node_def.get("displayName", full_type)
        type_version = node_def.get("defaultVersion")
        if type_version is None:
            ver = node_def.get("version", 1)
            type_version = max(ver) if isinstance(ver, list) else ver

        # Ensure unique name in workflow
        existing_names = {n.get("name") for n in nodes}
        final_name = display_name
        counter = 1
        while final_name in existing_names:
            counter += 1
            final_name = f"{display_name} {counter}"

        # 3. Build parameters
        node_params = {}
        if resource:
            node_params["resource"] = resource
        if operation:
            node_params["operation"] = operation
        if params:
            try:
                extra = json.loads(params)
                node_params.update(extra)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON in --params: {e}")
                raise typer.Exit(1)

        # 4. Calculate position
        node_a_name = None
        node_b_name = None

        if between:
            parts = [p.strip() for p in between.split(",", 1)]
            if len(parts) != 2:
                print_error("--between requires two node names separated by comma: 'NodeA,NodeB'")
                raise typer.Exit(1)
            node_a_name, node_b_name = parts

            node_a = _find_node_by_name(nodes, node_a_name)
            node_b = _find_node_by_name(nodes, node_b_name)
            if not node_a:
                print_error(f"Node '{node_a_name}' not found in workflow")
                raise typer.Exit(1)
            if not node_b:
                print_error(f"Node '{node_b_name}' not found in workflow")
                raise typer.Exit(1)

            pos_a = node_a.get("position", [0, 0])
            pos_b = node_b.get("position", [0, 0])

            if position:
                px, py = position.split(",", 1)
                node_position = [int(px.strip()), int(py.strip())]
            else:
                # Place at midpoint, shift B and downstream right
                node_position = [
                    (pos_a[0] + pos_b[0]) // 2,
                    (pos_a[1] + pos_b[1]) // 2,
                ]
                downstream = _get_downstream_nodes(workflow, node_a_name)
                # Include node_b itself
                if node_b_name not in downstream:
                    downstream.append(node_b_name)
                _shift_nodes_right(nodes, downstream, 200)

        elif after:
            after_node = _find_node_by_name(nodes, after)
            if not after_node:
                print_error(f"Node '{after}' not found in workflow")
                raise typer.Exit(1)

            after_pos = after_node.get("position", [0, 0])

            if position:
                px, py = position.split(",", 1)
                node_position = [int(px.strip()), int(py.strip())]
            else:
                node_position = [after_pos[0] + 200, after_pos[1]]
                # Shift any downstream nodes
                downstream = _get_downstream_nodes(workflow, after)
                _shift_nodes_right(nodes, downstream, 200)

        elif position:
            px, py = position.split(",", 1)
            node_position = [int(px.strip()), int(py.strip())]
        else:
            # Default: rightmost + 200
            node_position = [_get_rightmost_x(nodes) + 200, 300]

        # 5. Resolve credentials
        credentials = {}
        if credential:
            # Explicit credential specified — look it up and match to node's credential type
            cred_types = node_def.get("credentials", [])
            if not cred_types:
                print_error(f"Node type '{full_type}' does not accept credentials")
                raise typer.Exit(1)

            try:
                server_creds = api.list_credentials()
            except N8nApiError as e:
                print_error(f"Failed to list credentials: {e}")
                raise typer.Exit(1)

            # Find the credential by name or ID
            matched_cred = None
            for sc in server_creds:
                if sc.get("id") == credential or sc.get("name") == credential:
                    matched_cred = sc
                    break

            if not matched_cred:
                print_error(f"Credential '{credential}' not found on server")
                raise typer.Exit(1)

            # Match the credential's type to one of the node's accepted credential types
            cred_type_names = [ct.get("name", "") for ct in cred_types if isinstance(ct, dict)]
            if matched_cred.get("type") not in cred_type_names:
                print_error(
                    f"Credential '{matched_cred['name']}' (type: {matched_cred.get('type')}) "
                    f"is not compatible with node '{full_type}'. "
                    f"Expected types: {', '.join(cred_type_names)}"
                )
                raise typer.Exit(1)

            credentials[matched_cred["type"]] = {
                "id": matched_cred["id"],
                "name": matched_cred["name"],
            }
        else:
            # Auto-resolve credentials
            cred_map = _auto_resolve_credentials(api, node_def)
            for cred_type_name, cred_info in cred_map.items():
                credentials[cred_type_name] = cred_info

        # 6. Build the node
        new_node = {
            "id": str(uuid.uuid4()),
            "name": final_name,
            "type": full_type,
            "typeVersion": type_version,
            "position": node_position,
            "parameters": node_params,
        }
        if credentials:
            new_node["credentials"] = credentials

        nodes.append(new_node)

        # 7. Handle connections
        if after:
            if after not in connections:
                connections[after] = {"main": [[]]}
            main_outputs = connections[after].get("main", [[]])
            if not main_outputs:
                main_outputs = [[]]
                connections[after]["main"] = main_outputs
            main_outputs[0].append({
                "node": final_name,
                "type": "main",
                "index": 0,
            })

        if between and node_a_name and node_b_name:
            # Remove A→B connection
            if node_a_name in connections:
                for output_group in connections[node_a_name].get("main", []):
                    connections[node_a_name]["main"] = [
                        [c for c in group if c.get("node") != node_b_name]
                        for group in connections[node_a_name].get("main", [])
                    ]
                    break

            # Add A→new connection
            if node_a_name not in connections:
                connections[node_a_name] = {"main": [[]]}
            main_outputs = connections[node_a_name].get("main", [[]])
            if not main_outputs:
                main_outputs = [[]]
                connections[node_a_name]["main"] = main_outputs
            main_outputs[0].append({
                "node": final_name,
                "type": "main",
                "index": 0,
            })

            # Add new→B connection
            connections[final_name] = {"main": [[{
                "node": node_b_name,
                "type": "main",
                "index": 0,
            }]]}

        # 8. Update the workflow
        workflow["nodes"] = nodes
        workflow["connections"] = connections
        api.update_workflow(workflow_id, _writable_payload(workflow))

        print_success(f"Added node '{final_name}' ({full_type} v{type_version}) to workflow {workflow_id}")
        if credentials:
            for ctype, cinfo in credentials.items():
                print_info(f"  Credential: {ctype} → {cinfo['name']}")
        if after:
            print_info(f"  Connected after: {after}")
        if between:
            print_info(f"  Inserted between: {node_a_name} → {node_b_name}")

        print_json(new_node)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def node_update(
    workflow_id: str = typer.Argument(..., help="Workflow ID"),
    node_name: str = typer.Argument(..., help="Node display name or node ID"),
    params: Optional[str] = typer.Option(None, "--params", "-p", help="Parameters to merge as JSON string"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="New display name for the node"),
    credential: Optional[str] = typer.Option(None, "--credential", "-c", help="Credential name or ID to attach"),
):
    """
    Update an existing node's parameters, name, or credentials.

    Merges provided parameters into the node's existing parameters (deep merge).

    Examples:
        n8n workflows node update WF_ID "Assistant" --params '{"options": {"systemMessage": "new prompt"}}'
        n8n workflows node update WF_ID "My Node" --name "Renamed Node"
        n8n workflows node update WF_ID "My Node" --credential "New API Key"
    """
    try:
        api = get_n8n_api_client()

        # 1. Get the workflow
        workflow = api.get_workflow(workflow_id)
        if not workflow:
            print_error(f"Workflow '{workflow_id}' not found")
            raise typer.Exit(1)

        nodes = workflow.get("nodes", [])

        # 2. Find the node by name or ID
        target = _find_node_by_name(nodes, node_name)
        if not target:
            # Try matching by ID
            for n in nodes:
                if n.get("id") == node_name:
                    target = n
                    break
        if not target:
            print_error(f"Node '{node_name}' not found in workflow")
            raise typer.Exit(1)

        # 3. Merge parameters
        if params:
            try:
                new_params = json.loads(params)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON in --params: {e}")
                raise typer.Exit(1)
            _deep_merge(target.setdefault("parameters", {}), new_params)

        # 4. Rename if requested
        if name:
            existing_names = {n.get("name") for n in nodes if n is not target}
            if name in existing_names:
                print_error(f"Node name '{name}' already exists in workflow")
                raise typer.Exit(1)
            old_name = target["name"]
            target["name"] = name
            # Update connection references
            connections = workflow.get("connections", {})
            if old_name in connections:
                connections[name] = connections.pop(old_name)
            for src, type_map in connections.items():
                for conn_type, outputs in type_map.items():
                    for output_group in outputs:
                        for conn in output_group:
                            if conn.get("node") == old_name:
                                conn["node"] = name

        # 5. Update credential if requested
        if credential:
            node_def = api.get_node_definition(target.get("type", ""))
            if not node_def:
                print_error(f"Cannot resolve node type '{target.get('type')}' for credential matching")
                raise typer.Exit(1)
            cred_types = node_def.get("credentials", [])
            if not cred_types:
                print_error(f"Node type '{target.get('type')}' does not accept credentials")
                raise typer.Exit(1)
            try:
                server_creds = api.list_credentials()
            except N8nApiError as e:
                print_error(f"Failed to list credentials: {e}")
                raise typer.Exit(1)
            matched_cred = None
            for sc in server_creds:
                if sc.get("id") == credential or sc.get("name") == credential:
                    matched_cred = sc
                    break
            if not matched_cred:
                print_error(f"Credential '{credential}' not found on server")
                raise typer.Exit(1)
            cred_type_names = [ct.get("name", "") for ct in cred_types if isinstance(ct, dict)]
            if matched_cred.get("type") not in cred_type_names:
                print_error(
                    f"Credential '{matched_cred['name']}' (type: {matched_cred.get('type')}) "
                    f"is not compatible. Expected types: {', '.join(cred_type_names)}"
                )
                raise typer.Exit(1)
            target.setdefault("credentials", {})[matched_cred["type"]] = {
                "id": matched_cred["id"],
                "name": matched_cred["name"],
            }

        # 6. Update the workflow
        api.update_workflow(workflow_id, _writable_payload(workflow))
        print_success(f"Updated node '{target['name']}' in workflow {workflow_id}")
        print_json(target)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


def _deep_merge(base: dict, override: dict):
    """Recursively merge override into base dict."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


@app.command("connect")
def node_connect(
    workflow_id: str = typer.Argument(..., help="Workflow ID"),
    from_node: str = typer.Option(..., "--from", help="Source node name"),
    to_node: str = typer.Option(..., "--to", help="Target node name"),
    output_index: int = typer.Option(0, "--output-index", help="Source output index"),
    input_index: int = typer.Option(0, "--input-index", help="Target input index"),
    connection_type: str = typer.Option(
        "main",
        "--type",
        "-t",
        help="Connection type: main, ai_tool, ai_languageModel, ai_memory",
    ),
):
    """
    Connect two existing nodes in a workflow.

    Creates a connection from the source node's output to the target node's input.

    Examples:
        n8n workflows node connect WF_ID --from "Slack" --to "Set Fields"
        n8n workflows node connect WF_ID --from "Router" --to "Branch 2" --output-index 1
        n8n workflows node connect WF_ID --from "My Tool" --to "AI Agent" --type ai_tool
    """
    try:
        api = get_n8n_api_client()

        # 1. Get the workflow
        workflow = api.get_workflow(workflow_id)
        if not workflow:
            print_error(f"Workflow '{workflow_id}' not found")
            raise typer.Exit(1)

        nodes = workflow.get("nodes", [])
        connections = workflow.get("connections", {})

        # 2. Validate both nodes exist
        if not _find_node_by_name(nodes, from_node):
            print_error(f"Source node '{from_node}' not found in workflow")
            raise typer.Exit(1)
        if not _find_node_by_name(nodes, to_node):
            print_error(f"Target node '{to_node}' not found in workflow")
            raise typer.Exit(1)

        # 3. Add connection with the specified type
        if from_node not in connections:
            connections[from_node] = {}

        type_outputs = connections[from_node].get(connection_type, [])

        # Ensure the output_index slot exists
        while len(type_outputs) <= output_index:
            type_outputs.append([])
        connections[from_node][connection_type] = type_outputs

        type_outputs[output_index].append({
            "node": to_node,
            "type": connection_type,
            "index": input_index,
        })

        # 4. Update the workflow
        workflow["connections"] = connections
        api.update_workflow(workflow_id, _writable_payload(workflow))

        print_success(f"Connected '{from_node}' → '{to_node}' ({connection_type}) in workflow {workflow_id}")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
