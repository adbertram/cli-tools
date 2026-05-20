"""Tool commands for managing all tool types available to Copilot Studio agents."""
import typer
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, handle_error

# Import subcommand modules
from . import restapi, mcp


app = typer.Typer(help="Manage agent tools (REST APIs, MCP servers, connectors)")

COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "mcp": [
        "custom"
    ],
    "remove": [
        "custom"
    ],
    "restapi": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}

# Register type-specific subcommands
app.add_typer(restapi.app, name="restapi", help="Manage REST API tools")
app.add_typer(mcp.app, name="mcp", help="Manage MCP servers")


# Solution component types for dependency lookup
# See: https://learn.microsoft.com/en-us/power-apps/developer/data-platform/reference/entities/solutioncomponent
COMPONENT_TYPE_CONNECTOR = 372  # Custom Connector (connectors table)
COMPONENT_TYPE_AI_MODEL = None  # Will be looked up dynamically for msdyn_aimodel

# AIPlugin subtype mapping
AIPLUGIN_SUBTYPE_LABELS = {
    0: "Dataverse",
    1: "Certified Connector",
    2: "QA",
    3: "Flow",
    4: "Prompt",
    5: "Conversational",
    6: "Custom Api",
    7: "Rest Api",
    8: "Custom Connector",
}


def is_custom_connector(connector: dict) -> bool:
    """Check if a connector is custom (user-created) vs managed (Microsoft)."""
    props = connector.get("properties", {})
    return props.get("isCustomApi", False)


def extract_connector_operations(
    connector: dict,
    include_deprecated: bool = False,
    include_internal: bool = False,
    include_triggers: bool = False,
    is_installed: bool = False,
) -> list:
    """
    Extract operations (actions/triggers) from connector swagger definition.

    Args:
        connector: The connector definition with swagger
        include_deprecated: If True, include deprecated operations
        include_internal: If True, include internal-visibility operations
        include_triggers: If True, include triggers (not supported in Copilot agents)
        is_installed: Whether the connector has an active connection

    Returns:
        List of operation dicts with connector info and operation details
    """
    operations = []
    props = connector.get("properties", {})
    connector_id = connector.get("name", "")
    connector_name = props.get("displayName") or connector_id
    publisher = props.get("publisher", "")
    is_custom = is_custom_connector(connector)

    swagger = props.get("swagger", {})
    paths = swagger.get("paths", {})

    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ["get", "post", "put", "patch", "delete"]:
                op_id = details.get("operationId")
                if not op_id:
                    continue

                is_deprecated = details.get("deprecated", False)
                visibility = details.get("x-ms-visibility", "normal")
                is_internal = visibility == "internal"

                # Determine if trigger or action
                is_trigger = details.get("x-ms-trigger") is not None
                op_type = "Trigger" if is_trigger else "Action"

                # Skip deprecated unless explicitly requested
                if is_deprecated and not include_deprecated:
                    continue

                # Skip internal unless explicitly requested
                if is_internal and not include_internal:
                    continue

                # Skip triggers unless explicitly requested (triggers not supported in Copilot agents)
                if is_trigger and not include_triggers:
                    continue

                op_name = details.get("summary") or op_id

                operations.append({
                    "name": f"{connector_name} - {op_name}",
                    "type": "Connector",
                    "publisher": publisher,
                    "installed": is_installed,
                    "managed": not is_custom,
                    "id": f"{connector_id}:{op_id}",
                    "op_type": op_type,
                    "_component_type": None,
                })

    return operations


def format_unified_tool(tool: dict, tool_type: str) -> dict:
    """Format a tool for unified display with installed and managed status."""
    if tool_type == "prompt":
        is_managed = tool.get("ismanaged", False)
        return {
            "name": tool.get("msdyn_name", ""),
            "type": "Prompt",
            "publisher": tool.get("_ownerid_value@OData.Community.Display.V1.FormattedValue", ""),
            "installed": not is_managed,
            "managed": is_managed,
            "id": tool.get("msdyn_aimodelid", ""),
            "_component_type": "msdyn_aimodel",  # Entity name for dynamic lookup
        }
    elif tool_type == "mcp":
        props = tool.get("properties", {})
        is_custom = props.get("isCustomApi", False)
        return {
            "name": props.get("displayName") or tool.get("name", ""),
            "type": "MCP",
            "publisher": props.get("publisher", ""),
            "installed": is_custom,
            "managed": not is_custom,
            "id": tool.get("name", ""),
            "_component_type": None,
        }
    return {}


@app.command("list")
def tool_list(
    tool_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-T",
        help="Filter by tool type: prompt, mcp, connector",
    ),
    installed_only: bool = typer.Option(
        False,
        "--installed",
        "-i",
        help="Show only tools installed in your environment",
    ),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%asana%)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of tools to return",
    ),
    include_connector_actions: bool = typer.Option(
        False,
        "--include-connector-actions",
        help="Show individual connector actions instead of connectors. Requires --connector-id.",
    ),
    connector_id: Optional[str] = typer.Option(
        None,
        "--connector-id",
        "-c",
        help="Connector ID to fetch actions from (required with --include-connector-actions)",
    ),
    include_deprecated: bool = typer.Option(
        False,
        "--include-deprecated",
        "-d",
        help="Include deprecated operations (hidden by default). Only with --include-connector-actions.",
    ),
    include_internal: bool = typer.Option(
        False,
        "--include-internal",
        "-I",
        help="Include internal operations (hidden by default). Only with --include-connector-actions.",
    ),
    include_unsupported_triggers: bool = typer.Option(
        False,
        "--include-unsupported-triggers",
        help="Include triggers (not supported in Copilot agents). Only with --include-connector-actions.",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output format: json (default) or table",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List agent tools available in your environment.

    Shows AI Builder prompts, MCP servers, and connectors that can be added
    to Copilot Studio agents.

    Tool Types:
      - prompt: AI Builder prompts for text analysis and generation
      - mcp: Model Context Protocol servers
      - connector: Power Platform connectors (Asana, SharePoint, etc.)

    Connector Actions:
      By default, connectors are shown as top-level entries. Use
      --include-connector-actions with --connector-id to see individual
      actions (operations) available within a specific connector.

    Examples:
        copilot tool list --table                    # All tools
        copilot tool list --installed --table        # Only installed tools
        copilot tool list --type prompt --table      # AI Builder prompts only
        copilot tool list --type connector --table   # Connectors only
        copilot tool list --filter "name:ilike:%asana%"  # Search by name
        copilot tool list --properties "name,type,id"  # Select specific fields

        # Show individual actions for a specific connector
        copilot tool list --type connector --include-connector-actions --connector-id shared_asana --table
    """
    valid_types = ["prompt", "mcp", "connector"]
    if tool_type and tool_type.lower() not in valid_types:
        typer.echo(f"Error: Invalid tool type '{tool_type}'. Must be one of: {', '.join(valid_types)}", err=True)
        raise typer.Exit(1)

    # Validate --include-connector-actions requires --connector-id
    if include_connector_actions and not connector_id:
        typer.echo("Error: --include-connector-actions requires --connector-id to specify which connector to fetch actions from.", err=True)
        raise typer.Exit(1)

    # Validate --connector-id only makes sense with connector type
    if connector_id and tool_type and tool_type.lower() != "connector":
        typer.echo("Error: --connector-id can only be used with --type connector", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        all_tools = []

        # Determine which types to fetch
        types_to_fetch = [tool_type.lower()] if tool_type else valid_types

        # Pre-fetch connectors once if needed by multiple types (mcp + connector)
        need_connectors = "connector" in types_to_fetch or "mcp" in types_to_fetch
        cached_connectors = client.list_connectors() if need_connectors else []

        # Pre-fetch connections once if connector type is needed
        installed_connector_ids = set()
        if "connector" in types_to_fetch:
            connections = client.list_connections()
            installed_connector_ids = {
                conn.get("properties", {}).get("apiId", "").split("/")[-1]
                for conn in connections
            }

        # Fetch each tool type
        if "prompt" in types_to_fetch:
            prompts = client.list_prompts()
            for p in prompts:
                formatted = format_unified_tool(p, "prompt")
                if not installed_only or formatted["installed"]:
                    all_tools.append(formatted)

        if "mcp" in types_to_fetch:
            # Filter cached connectors for MCP servers (same logic as client.list_mcp_servers)
            for connector in cached_connectors:
                name = connector.get("name", "")
                props = connector.get("properties", {})
                display_name = props.get("displayName", "")
                description = (props.get("description", "") or "").lower()
                is_mcp = (
                    "mcpserver" in name.lower()
                    or ("mcp" in name.lower() and name.startswith("shared_"))
                    or "mcp" in display_name.lower()
                    or "model context protocol" in description
                )
                if is_mcp:
                    formatted = format_unified_tool(connector, "mcp")
                    if not installed_only or formatted["installed"]:
                        all_tools.append(formatted)

        if "connector" in types_to_fetch:
            if include_connector_actions and connector_id:
                # Fetch a single connector with swagger/actions and show its operations
                connector = client.get_connector(connector_id)
                is_installed = connector_id in installed_connector_ids
                operations = extract_connector_operations(
                    connector,
                    include_deprecated=include_deprecated,
                    include_internal=include_internal,
                    include_triggers=include_unsupported_triggers,
                    is_installed=is_installed,
                )
                for op in operations:
                    if not installed_only or op["installed"]:
                        all_tools.append(op)
            else:
                # Default: Show connectors as top-level entries (fast)
                for c in cached_connectors:
                    props = c.get("properties", {})
                    is_custom = is_custom_connector(c)
                    conn_id = c.get("name", "")
                    is_installed = conn_id in installed_connector_ids
                    formatted = {
                        "name": props.get("displayName") or conn_id,
                        "type": "Connector",
                        "publisher": props.get("publisher", ""),
                        "installed": is_installed,
                        "managed": not is_custom,
                        "id": conn_id,
                        "_component_type": None,
                    }
                    if not installed_only or formatted["installed"]:
                        all_tools.append(formatted)

        if not all_tools:
            print_json([])
            return

        # Apply filters using standard field:op:value syntax
        if filter:
            from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
            try:
                validate_filters(filter)
                all_tools = apply_filters(all_tools, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if not all_tools:
            print_json([])
            return

        # Apply limit
        all_tools = all_tools[:limit]

        # Fetch dependencies for installed tools (only those with component type)
        for tool in all_tools:
            component_type = tool.get("_component_type")
            if tool.get("installed") and component_type is not None:
                try:
                    if isinstance(component_type, int):
                        deps = client.get_dependencies(tool["id"], component_type)
                    else:
                        deps = client.get_dependencies_for_entity(tool["id"], component_type)
                    tool["deps"] = len(deps)
                except Exception:
                    tool["deps"] = "-"
            else:
                tool["deps"] = "-"
            # Remove internal field
            tool.pop("_component_type", None)

        # Sort by type then name
        type_order = {"Connector": 0, "Prompt": 1, "MCP": 2}
        all_tools.sort(key=lambda x: (
            type_order.get(x["type"], 99),
            x["name"].lower()
        ))

        # Apply properties filter if specified
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            all_tools = [
                {k: v for k, v in item.items() if k in property_list}
                for item in all_tools
            ]

        use_table = table or output == "table"
        if use_table:
            if properties:
                property_list = [p.strip() for p in properties.split(",")]
                print_table(all_tools, columns=property_list, headers=property_list)
            else:
                print_table(
                    all_tools,
                    columns=["name", "type", "publisher", "installed", "deps", "id"],
                    headers=["Name", "Type", "Publisher", "Installed", "Deps", "ID"],
                )
        else:
            print_json(all_tools)

    except typer.Abort:
        typer.echo("Aborted.")
        raise typer.Exit(0)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def tool_get(
    tool_id: str = typer.Argument(
        ...,
        help="The tool's unique identifier",
    ),
    tool_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-T",
        help="Tool type: prompt, connector, restapi. Required if auto-detection fails.",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    Get details for a specific tool.

    Retrieves detailed information about a tool by its ID. The tool type
    can be auto-detected or specified explicitly.

    Supported tool types:
      - prompt: AI Builder prompts
      - connector: Power Platform connectors
      - restapi: REST API tools

    Examples:
        copilot tool get <tool-id>
        copilot tool get <tool-id> --type prompt
        copilot tool get <tool-id> --type connector --table
    """
    valid_types = ["prompt", "connector", "restapi"]
    if tool_type and tool_type.lower() not in valid_types:
        typer.echo(f"Error: Invalid tool type '{tool_type}'. Must be one of: {', '.join(valid_types)}", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        detected_type = tool_type.lower() if tool_type else None
        tool_info = None

        # Try to auto-detect tool type if not specified
        if not detected_type:
            # Try prompt first
            try:
                tool_info = client.get_prompt(tool_id)
                detected_type = "prompt"
            except Exception:
                pass

            # Try connector
            if not detected_type:
                try:
                    tool_info = client.get_connector(tool_id)
                    detected_type = "connector"
                except Exception:
                    pass

            # Try REST API
            if not detected_type:
                try:
                    tool_info = client.get_rest_api(tool_id)
                    detected_type = "restapi"
                except Exception:
                    pass

            if not detected_type:
                typer.echo(
                    f"Error: Could not find tool with ID '{tool_id}'. "
                    "Please specify --type to indicate the tool type.",
                    err=True
                )
                raise typer.Exit(1)
        else:
            # Fetch tool info based on specified type
            if detected_type == "prompt":
                tool_info = client.get_prompt(tool_id)
            elif detected_type == "connector":
                tool_info = client.get_connector(tool_id)
            elif detected_type == "restapi":
                tool_info = client.get_rest_api(tool_id)

        if table:
            # Format for table display based on type
            if detected_type == "prompt":
                formatted = {
                    "name": tool_info.get("msdyn_name", ""),
                    "type": "Prompt",
                    "id": tool_info.get("msdyn_aimodelid", ""),
                    "managed": "Yes" if tool_info.get("ismanaged", False) else "No",
                }
            elif detected_type == "connector":
                props = tool_info.get("properties", {})
                formatted = {
                    "name": props.get("displayName") or tool_info.get("name", ""),
                    "type": "Connector",
                    "id": tool_info.get("name", ""),
                    "publisher": props.get("publisher", ""),
                }
            elif detected_type == "restapi":
                formatted = {
                    "name": tool_info.get("displayname") or tool_info.get("name", ""),
                    "type": "REST API",
                    "id": tool_info.get("connectorid", ""),
                }
            else:
                formatted = {"id": tool_id, "type": detected_type}

            print_table(
                [formatted],
                columns=list(formatted.keys()),
                headers=[k.title() for k in formatted.keys()],
            )
        else:
            print_json(tool_info)

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("remove")
def tool_remove(
    tool_id: str = typer.Argument(
        ...,
        help="The tool's unique identifier (GUID for prompts/REST APIs)",
    ),
    tool_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-T",
        help="Tool type: prompt, restapi. Required if auto-detection fails.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Remove a tool from the environment.

    Permanently deletes a custom tool (prompt or REST API) from the environment.
    This action cannot be undone.

    Supported tool types:
      - prompt: AI Builder prompts (custom only, not system prompts)
      - restapi: REST API tools (custom connectors)

    Note: Managed connectors from Microsoft cannot be deleted.

    Examples:
        copilot tool remove 12345678-1234-1234-1234-123456789abc --type prompt
        copilot tool remove abcdef01-2345-6789-abcd-ef0123456789 --type restapi
        copilot tool remove <id> --type prompt --force
    """
    valid_types = ["prompt", "restapi"]
    if tool_type and tool_type.lower() not in valid_types:
        typer.echo(f"Error: Invalid tool type '{tool_type}'. Must be one of: {', '.join(valid_types)}", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        tool_name = None
        detected_type = tool_type.lower() if tool_type else None

        # Try to auto-detect tool type if not specified
        if not detected_type:
            # Try prompt first
            try:
                tool_info = client.get_prompt(tool_id)
                detected_type = "prompt"
                tool_name = tool_info.get("msdyn_name", tool_id)
                # Check if managed
                if tool_info.get("ismanaged", False):
                    typer.echo("Error: Cannot delete system/managed prompts.", err=True)
                    raise typer.Exit(1)
            except Exception:
                pass

            # Try REST API
            if not detected_type:
                try:
                    tool_info = client.get_rest_api(tool_id)
                    detected_type = "restapi"
                    tool_name = tool_info.get("displayname") or tool_info.get("name", tool_id)
                except Exception:
                    pass

            if not detected_type:
                typer.echo(
                    f"Error: Could not find tool with ID '{tool_id}'. "
                    "Please specify --type to indicate the tool type.",
                    err=True
                )
                raise typer.Exit(1)
        else:
            # Get tool info for confirmation message
            if detected_type == "prompt":
                tool_info = client.get_prompt(tool_id)
                tool_name = tool_info.get("msdyn_name", tool_id)
                if tool_info.get("ismanaged", False):
                    typer.echo("Error: Cannot delete system/managed prompts.", err=True)
                    raise typer.Exit(1)
            elif detected_type == "restapi":
                tool_info = client.get_rest_api(tool_id)
                tool_name = tool_info.get("displayname") or tool_info.get("name", tool_id)

        # Confirm deletion
        type_display = "Prompt" if detected_type == "prompt" else "REST API"
        if not force:
            typer.confirm(
                f"Are you sure you want to delete {type_display} '{tool_name}'? This cannot be undone.",
                abort=True,
            )

        # Delete the tool
        # Use component type for REST APIs (372), entity name for prompts
        component_type = COMPONENT_TYPE_CONNECTOR if detected_type == "restapi" else "msdyn_aimodel"
        try:
            if detected_type == "prompt":
                client.delete_prompt(tool_id)
            elif detected_type == "restapi":
                # First, delete any auto-generated AIPlugin wrappers that reference this connector
                try:
                    aiplugins = client.get(f"aiplugins?$filter=_connector_value eq {tool_id}&$select=aipluginid,humanname")
                    for plugin in aiplugins.get("value", []):
                        plugin_id = plugin.get("aipluginid")
                        plugin_name = plugin.get("humanname", plugin_id)
                        client.delete(f"aiplugins({plugin_id})")
                        typer.echo(f"Deleted associated AIPlugin '{plugin_name}'")
                except Exception:
                    pass  # Continue with REST API deletion even if AIPlugin cleanup fails
                client.delete_rest_api(tool_id)
            print_success(f"Deleted {type_display} '{tool_name}'")
        except Exception as delete_error:
            error_msg = str(delete_error)
            # Check if it's a dependency error
            if "referenced by" in error_msg.lower() or "cannot be deleted" in error_msg.lower():
                typer.echo(f"Error: Cannot delete {type_display} '{tool_name}' - it has dependencies.\n", err=True)
                # Fetch and display dependencies
                try:
                    if isinstance(component_type, int):
                        deps = client.get_dependencies(tool_id, component_type)
                    else:
                        deps = client.get_dependencies_for_entity(tool_id, component_type)
                    if deps:
                        typer.echo("Dependent components:", err=True)
                        for dep in deps:
                            dep_type_code = dep.get("dependentcomponenttype")
                            dep_type = dep.get("dependentcomponenttype@OData.Community.Display.V1.FormattedValue")
                            dep_id = dep.get("dependentcomponentobjectid", "")
                            # If formatted value is None, look up the component type name
                            if not dep_type or dep_type == "None":
                                try:
                                    type_info = client.get(f"solutioncomponentdefinitions?$filter=solutioncomponenttype eq {dep_type_code}&$select=name")
                                    type_defs = type_info.get("value", [])
                                    dep_type = type_defs[0].get("name") if type_defs else f"Type {dep_type_code}"
                                except Exception:
                                    dep_type = f"Type {dep_type_code}"
                            typer.echo(f"  - {dep_type}: {dep_id}", err=True)
                        typer.echo("\nRemove this tool from these components before deleting.", err=True)
                except Exception:
                    pass  # If dependency lookup fails, just show original error
                raise typer.Exit(1)
            else:
                raise delete_error

    except typer.Abort:
        typer.echo("Aborted.")
        raise typer.Exit(0)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
def tool_update(
    tool_id: str = typer.Argument(
        ...,
        help="The tool's unique identifier (connection reference ID for connectors)",
    ),
    tool_type: Optional[str] = typer.Option(
        None,
        "--type",
        "-T",
        help="Tool type: connector. Required if auto-detection fails.",
    ),
    connection_id: Optional[str] = typer.Option(
        None,
        "--connection-id",
        "-c",
        help="New connection ID to associate with this tool (for connector tools)",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="New display name for the tool",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    Update an existing tool's configuration.

    Currently supports updating connection references for connector-based tools.
    This allows you to change which connection (authenticated instance) a tool uses.

    Supported tool types:
      - connector: Connection references used by connector-based tools

    Examples:
        # Update the connection used by a connection reference
        copilot tool update <connection-ref-id> --connection-id <new-connection-id>

        # Update with explicit type
        copilot tool update <id> --type connector --connection-id <conn-id>

        # Update display name
        copilot tool update <id> --name "My Asana Connection"

        # Update both connection and name
        copilot tool update <id> -c <conn-id> -n "New Name"
    """
    valid_types = ["connector"]
    if tool_type and tool_type.lower() not in valid_types:
        typer.echo(f"Error: Invalid tool type '{tool_type}'. Must be one of: {', '.join(valid_types)}", err=True)
        raise typer.Exit(1)

    if not connection_id and not name:
        typer.echo("Error: At least one update field is required (--connection-id or --name)", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        detected_type = tool_type.lower() if tool_type else None
        tool_info = None

        # Try to auto-detect tool type if not specified
        if not detected_type:
            # Try connection reference first
            try:
                tool_info = client.get_connection_reference(tool_id)
                detected_type = "connector"
            except Exception:
                pass

            if not detected_type:
                typer.echo(
                    f"Error: Could not find tool with ID '{tool_id}'. "
                    "Please specify --type to indicate the tool type.",
                    err=True
                )
                raise typer.Exit(1)
        else:
            # Get tool info for validation
            if detected_type == "connector":
                tool_info = client.get_connection_reference(tool_id)

        # Perform the update based on tool type
        if detected_type == "connector":
            current_name = tool_info.get("connectionreferencedisplayname", tool_id)
            current_conn = tool_info.get("connectionid", "")

            # Show what will change
            typer.echo(f"Updating connection reference '{current_name}'...")
            if connection_id:
                typer.echo(f"  Connection: {current_conn or '(none)'} → {connection_id}")
            if name:
                typer.echo(f"  Name: {current_name} → {name}")

            # Perform the update
            updated = client.update_connection_reference(
                connection_reference_id=tool_id,
                connection_id=connection_id,
                display_name=name,
            )

            print_success(f"Updated connection reference '{updated.get('connectionreferencedisplayname', tool_id)}'")

            # Display the updated tool info
            display_data = {
                "name": updated.get("connectionreferencedisplayname", ""),
                "logical_name": updated.get("connectionreferencelogicalname", ""),
                "id": updated.get("connectionreferenceid", ""),
                "connector_id": updated.get("connectorid", ""),
                "connection_id": updated.get("connectionid", ""),
            }

            if table:
                print_table(
                    [display_data],
                    columns=["name", "logical_name", "connector_id", "connection_id", "id"],
                    headers=["Name", "Logical Name", "Connector", "Connection ID", "Reference ID"],
                )
            else:
                print_json(display_data)

    except typer.Abort:
        typer.echo("Aborted.")
        raise typer.Exit(0)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
