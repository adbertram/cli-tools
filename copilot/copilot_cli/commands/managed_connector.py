"""Managed connector commands for listing Microsoft Power Platform connectors.

Managed connectors are built-in connectors published by Microsoft and third parties.
These are read-only - you cannot create, modify, or delete them.
"""
import typer
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="List and inspect managed (Microsoft) connectors")

COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}


def extract_auth_types(connector: dict) -> list[str]:
    """
    Extract supported authentication types from a connector.

    Power Platform connectors can define auth types in two ways:
    1. connectionParameterSets.values[] - Multiple auth types, each with a name
    2. connectionParameters - Single auth type, determined by parameter names

    Args:
        connector: The connector definition

    Returns:
        List of authentication type names (e.g., ["OAuth", "ServicePrincipal", "ApiKey"])
    """
    props = connector.get("properties", {})
    auth_types = []

    # Check for multi-auth via connectionParameterSets
    param_sets = props.get("connectionParameterSets", {})
    if param_sets and isinstance(param_sets, dict):
        values = param_sets.get("values", [])
        if values:
            for value in values:
                name = value.get("name", "")
                if name:
                    # Normalize common auth type names for display
                    normalized = _normalize_auth_type_name(name)
                    if normalized and normalized not in auth_types:
                        auth_types.append(normalized)
            return auth_types

    # Fall back to single auth via connectionParameters
    conn_params = props.get("connectionParameters", {})
    if conn_params and isinstance(conn_params, dict):
        param_keys = set(conn_params.keys())

        # Detect auth type from parameter structure
        if "token" in param_keys or "Token" in param_keys:
            # Check if it's OAuth by looking at the token definition
            token_def = conn_params.get("token") or conn_params.get("Token", {})
            if isinstance(token_def, dict):
                token_type = token_def.get("type", "")
                if token_type == "oauthSetting":
                    auth_types.append("OAuth")
                else:
                    auth_types.append("OAuth")  # Default for token param
            else:
                auth_types.append("OAuth")

        if "api_key" in param_keys or "apiKey" in param_keys or "api-key" in param_keys:
            auth_types.append("ApiKey")

        if ("username" in param_keys or "Username" in param_keys) and \
           ("password" in param_keys or "Password" in param_keys):
            auth_types.append("Basic")

        # Check for service principal parameters
        if any(k.lower() in ["clientid", "client_id", "tenantid", "tenant_id"]
               for k in param_keys):
            if "ServicePrincipal" not in auth_types:
                auth_types.append("ServicePrincipal")

    return auth_types if auth_types else ["Unknown"]


def _normalize_auth_type_name(name: str) -> str:
    """
    Normalize authentication type names for consistent display.

    Args:
        name: Raw auth type name from the connector definition

    Returns:
        Normalized display name
    """
    name_lower = name.lower()

    # OAuth variants
    if name_lower in ["oauth", "oauth2", "oauthsetting"]:
        return "OAuth"
    if name_lower in ["certoauth", "cert-oauth", "certificateoauth"]:
        return "CertOAuth"
    if name_lower in ["serviceprincipaloauth", "oauthsp", "sp-oauth"]:
        return "ServicePrincipal"

    # API Key variants
    if name_lower in ["apikey", "api_key", "api-key", "adminkey", "key"]:
        return "ApiKey"

    # Basic auth
    if name_lower in ["basic", "basicauth", "basic-auth"]:
        return "Basic"

    # Anonymous
    if name_lower in ["anonymous", "none", "noauth"]:
        return "Anonymous"

    # Return original with first letter capitalized if unknown
    return name.capitalize() if name else ""


def format_connector_for_display(connector: dict, truncate: bool = False) -> dict:
    """Format a managed connector for display.

    Args:
        connector: The connector dict from the API
        truncate: If True, truncate long values for table display
    """
    props = connector.get("properties", {})

    description = props.get("description") or ""
    if truncate and len(description) > 60:
        description = description[:57] + "..."

    # Extract authentication types
    auth_types = extract_auth_types(connector)
    auth_types_str = ", ".join(auth_types) if auth_types else "Unknown"

    return {
        "name": props.get("displayName") or connector.get("name", ""),
        "id": connector.get("name", ""),
        "publisher": props.get("publisher") or "",
        "tier": props.get("tier") or "N/A",
        "auth_types": auth_types_str,
        "description": description,
    }


def extract_operations(
    connector: dict,
    include_deprecated: bool = False,
    include_internal: bool = False,
    truncate: bool = False,
) -> list:
    """
    Extract operations (actions/triggers) from connector swagger definition.

    Args:
        connector: The connector definition with swagger
        include_deprecated: If True, include deprecated operations
        include_internal: If True, include internal-visibility operations
                         (internal ops cannot be used as Copilot agent tools)
        truncate: If True, truncate long values for table display

    Returns:
        List of operation dicts with id, name, description, type, deprecated, visibility
    """
    operations = []
    swagger = connector.get("properties", {}).get("swagger", {})
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

                # Skip deprecated unless explicitly requested
                if is_deprecated and not include_deprecated:
                    continue

                # Skip internal unless explicitly requested
                # Internal operations cannot be used as Copilot agent tools
                if is_internal and not include_internal:
                    continue

                # Determine if trigger or action
                is_trigger = details.get("x-ms-trigger") is not None
                op_type = "Trigger" if is_trigger else "Action"

                # Get description
                description = details.get("description") or details.get("summary") or ""
                if truncate and len(description) > 80:
                    description = description[:77] + "..."

                operations.append({
                    "id": op_id,
                    "name": details.get("summary") or op_id,
                    "type": op_type,
                    "method": method.upper(),
                    "deprecated": is_deprecated,
                    "visibility": visibility,
                    "description": description,
                })

    # Sort: Actions first, then Triggers, then by name
    operations.sort(key=lambda x: (0 if x["type"] == "Action" else 1, x["id"].lower()))

    return operations


@app.command("list")
def managed_connector_list(
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%sharepoint%)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of connectors to return",
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
    raw: bool = typer.Option(
        False,
        "--raw",
        "-r",
        help="Output raw JSON including all metadata",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List all managed (Microsoft) connectors available in the environment.

    Managed connectors are built-in connectors published by Microsoft and
    third-party ISVs. These are read-only and available across all environments.

    Examples:
        copilot managed-connector list --table
        copilot managed-connector list --filter "name:ilike:%sharepoint%"
        copilot managed-connector list --filter "publisher:ilike:%microsoft%" --table
        copilot managed-connector list --limit 50
        copilot managed-connector list --raw
        copilot managed-connector list --properties "name,id,publisher"
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

    try:
        client = get_client()
        connectors = client.list_connectors(managed_only=True)

        if not connectors:
            print_json([])
            return

        # Apply filters using standard field:op:value syntax
        if filter:
            try:
                validate_filters(filter)
                connectors = apply_filters(connectors, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if not connectors:
            print_json([])
            return

        # Apply limit
        connectors = connectors[:limit]

        # Raw output includes all metadata
        if raw:
            print_json(connectors)
            return

        use_table = table or output == "table"
        formatted = [format_connector_for_display(c, truncate=use_table) for c in connectors]

        # Sort by name
        formatted.sort(key=lambda x: x["name"].lower())

        # Apply properties filter if specified
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            formatted = [
                {k: v for k, v in item.items() if k in property_list}
                for item in formatted
            ]
        if use_table:
            if properties:
                property_list = [p.strip() for p in properties.split(",")]
                print_table(formatted, columns=property_list, headers=property_list)
            else:
                print_table(
                    formatted,
                    columns=["name", "publisher", "tier", "auth_types", "id"],
                    headers=["Name", "Publisher", "Tier", "Auth Types", "ID"],
                )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def managed_connector_get(
    connector_id: str = typer.Argument(
        ...,
        help="The connector's unique identifier (e.g., shared_asana, shared_office365)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display operations as a formatted table",
    ),
    include_deprecated: bool = typer.Option(
        False,
        "--include-deprecated",
        "-d",
        help="Include deprecated operations (hidden by default)",
    ),
    include_internal: bool = typer.Option(
        False,
        "--include-internal",
        "-i",
        help="Include internal operations (cannot be used as agent tools)",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        "-r",
        help="Output raw JSON connector definition (ignores --table)",
    ),
    openapi: bool = typer.Option(
        False,
        "--openapi",
        "--swagger",
        help="Output the full OpenAPI/Swagger definition (JSON format)",
    ),
    output_file: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write OpenAPI definition to file (use with --openapi)",
    ),
):
    """
    Get details for a managed connector including available operations.

    By default, shows only operations that can be used as Copilot agent tools.
    Deprecated and internal-visibility operations are hidden by default.

    Examples:
        copilot managed-connector get shared_asana --table
        copilot managed-connector get shared_asana --table --include-deprecated
        copilot managed-connector get shared_office365 --raw
        copilot managed-connector get shared_asana --openapi
        copilot managed-connector get shared_asana --openapi --output ./asana-spec.json
    """
    import json
    from pathlib import Path

    try:
        client = get_client()
        connector = client.get_connector(connector_id)

        # OpenAPI/Swagger output
        if openapi:
            swagger = connector.get("properties", {}).get("swagger", {})
            if not swagger:
                typer.echo("Error: No OpenAPI/Swagger definition found for this connector.", err=True)
                raise typer.Exit(1)

            if output_file:
                # Write to file
                output_path = Path(output_file)
                try:
                    output_path.write_text(json.dumps(swagger, indent=2))
                    props = connector.get("properties", {})
                    typer.echo(f"OpenAPI definition for '{props.get('displayName', connector_id)}' written to: {output_file}")
                except Exception as e:
                    typer.echo(f"Error writing to file: {e}", err=True)
                    raise typer.Exit(1)
            else:
                # Output to stdout
                print_json(swagger)
            return

        # Raw output - full JSON
        if raw:
            print_json(connector)
            return

        # Extract and display operations
        operations = extract_operations(connector, include_deprecated, include_internal)
        props = connector.get("properties", {})

        # Extract auth types
        auth_types = extract_auth_types(connector)

        if table:
            # Table format - show header info and table of operations
            typer.echo(f"\nConnector: {props.get('displayName', connector_id)}")
            typer.echo(f"ID: {connector.get('name', connector_id)}")
            typer.echo(f"Publisher: {props.get('publisher', 'N/A')}")
            typer.echo(f"Auth Types: {', '.join(auth_types)}")

            if not operations:
                typer.echo("\nNo usable operations found.")
                typer.echo("Use --include-deprecated and/or --include-internal to see hidden operations.")
                return

            # Count hidden operations
            all_ops = extract_operations(connector, True, True)
            deprecated_count = len([o for o in all_ops if o["deprecated"]])
            internal_count = len([o for o in all_ops if o["visibility"] == "internal"])

            hidden_parts = []
            if deprecated_count > 0 and not include_deprecated:
                hidden_parts.append(f"{deprecated_count} deprecated")
            if internal_count > 0 and not include_internal:
                hidden_parts.append(f"{internal_count} internal")

            hidden_msg = f" ({', '.join(hidden_parts)} hidden)" if hidden_parts else ""
            typer.echo(f"\nOperations: {len(operations)}{hidden_msg}")

            display_ops = []
            for op in operations:
                row = {
                    "id": op["id"],
                    "name": op["name"][:40] + "..." if len(op["name"]) > 40 else op["name"],
                    "type": op["type"],
                    "method": op["method"],
                }
                if include_deprecated:
                    row["deprecated"] = "Yes" if op["deprecated"] else "No"
                if include_internal:
                    row["visibility"] = op["visibility"]
                display_ops.append(row)

            columns = ["id", "name", "type", "method"]
            headers = ["Operation ID", "Name", "Type", "Method"]
            if include_deprecated:
                columns.append("deprecated")
                headers.append("Deprecated")
            if include_internal:
                columns.append("visibility")
                headers.append("Visibility")

            print_table(display_ops, columns=columns, headers=headers)
        else:
            # JSON format - structured output with connector info and operations
            result = {
                "name": props.get("displayName", connector_id),
                "id": connector.get("name", connector_id),
                "publisher": props.get("publisher", "N/A"),
                "tier": props.get("tier", "N/A"),
                "auth_types": auth_types,
                "operations": operations,
            }
            print_json(result)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
