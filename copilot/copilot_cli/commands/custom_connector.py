"""Custom connector commands for managing user-created Power Platform connectors.

Custom connectors are user-created connectors in the environment. These can be
created, modified, and deleted. They wrap custom APIs and enable integration
with services not covered by managed connectors.
"""
import sys
import typer
import json
import yaml
from pathlib import Path
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, safe_symbol


app = typer.Typer(help="Create, manage, and inspect custom connectors")

COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "register": [
        "custom"
    ],
    "remove": [
        "custom"
    ],
    "update": [
        "custom"
    ],
    "validate": [
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


def is_custom_connector(connector: dict) -> bool:
    """
    Check if a connector is a custom connector (not a managed/Microsoft connector).

    Custom connectors can be identified by:
    1. properties.isCustomApi == True (Power Apps API)
    2. _dataverse.connectortype == 1 (Dataverse)
    3. properties.environment == True (indicates custom/environment-scoped connector)

    Args:
        connector: The connector definition

    Returns:
        True if the connector is a custom connector, False otherwise
    """
    props = connector.get("properties", {})
    dataverse = connector.get("_dataverse", {})

    # Check Power Apps isCustomApi flag
    if props.get("isCustomApi") is True:
        return True

    # Check Dataverse connectortype (1 = custom)
    if dataverse.get("connectortype") == 1:
        return True

    # Check environment flag (custom connectors have environment property)
    if props.get("environment") is True:
        return True

    return False


def format_connector_for_display(connector: dict, truncate: bool = False) -> dict:
    """Format a custom connector for display.

    Args:
        connector: The connector dict from the API
        truncate: If True, truncate long values for table display
    """
    props = connector.get("properties", {})
    dataverse = connector.get("_dataverse", {})

    description = props.get("description") or ""
    if truncate and len(description) > 60:
        description = description[:57] + "..."

    # Extract authentication types
    auth_types = extract_auth_types(connector)
    auth_types_str = ", ".join(auth_types) if auth_types else "Unknown"

    return {
        "name": props.get("displayName") or connector.get("name", ""),
        "id": connector.get("name", ""),  # connectorinternalid (e.g., shared_pub-5fasana-...)
        "logical_name": dataverse.get("name", ""),  # Dataverse logical name (e.g., pub_5fasana)
        "auth_types": auth_types_str,
        "description": description,
        "source": connector.get("_source", ""),
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


def validate_openapi_definition(openapi_def: dict) -> tuple[bool, str]:
    """
    Validate that the OpenAPI definition is in the correct format.

    Args:
        openapi_def: Parsed OpenAPI definition dict

    Returns:
        tuple: (is_valid, error_message)
    """
    # Check for OpenAPI 2.0 (Swagger)
    swagger_version = openapi_def.get("swagger")
    if not swagger_version or not swagger_version.startswith("2."):
        openapi_version = openapi_def.get("openapi", "")
        if openapi_version.startswith("3."):
            return False, (
                "OpenAPI 3.0 is not supported by Power Platform. "
                "Please convert to OpenAPI 2.0 (Swagger) format. "
                "You can use tools like swagger-cli or API Transformer for conversion."
            )
        return False, "OpenAPI definition must be in OpenAPI 2.0 (Swagger) format."

    # Check required fields
    required_fields = ["swagger", "info", "host", "basePath", "schemes"]
    missing = [f for f in required_fields if f not in openapi_def]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    # Check info section
    info = openapi_def.get("info", {})
    if not info.get("title"):
        return False, "info.title is required"
    if not info.get("version"):
        return False, "info.version is required"

    # Check size (must be < 1MB)
    json_str = json.dumps(openapi_def)
    size_mb = len(json_str.encode('utf-8')) / (1024 * 1024)
    if size_mb >= 1.0:
        return False, f"OpenAPI definition is too large ({size_mb:.2f} MB). Must be less than 1 MB."

    # Check OAuth accessCode definitions for required URLs
    security_defs = openapi_def.get("securityDefinitions", {})
    oauth_errors = []
    for sec_name, sec_def in security_defs.items():
        if not isinstance(sec_def, dict):
            continue
        if sec_def.get("type") != "oauth2" or sec_def.get("flow") != "accessCode":
            continue

        missing_fields = []
        if not sec_def.get("authorizationUrl"):
            missing_fields.append("authorizationUrl")
        if not sec_def.get("tokenUrl"):
            missing_fields.append("tokenUrl")
        if not (sec_def.get("refreshUrl") or sec_def.get("x-ms-refresh-url")):
            missing_fields.append("refreshUrl (or x-ms-refresh-url)")

        if missing_fields:
            oauth_errors.append(
                f"OAuth definition '{sec_name}' is missing required fields: {', '.join(missing_fields)}"
            )

    if oauth_errors:
        return False, "; ".join(oauth_errors)

    return True, ""


@app.command("validate")
def custom_connector_validate(
    swagger_file: str = typer.Argument(
        ...,
        help="Path to OpenAPI 2.0 (Swagger) definition file to validate",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed validation information",
    ),
):
    """
    Validate an OpenAPI 2.0 schema for Power Platform custom connector compatibility.

    This command checks:
    - OpenAPI 2.0 (Swagger) format (not OpenAPI 3.0)
    - Required fields: swagger, info, host, basePath, schemes
    - Info section has title and version
    - File size is under 1MB limit
    - OAuth configuration (if present)
    - Operation IDs and paths

    Examples:
        copilot custom-connector validate ./api.json
        copilot custom-connector validate ./connector.yaml --verbose
    """
    try:
        # Read and parse file
        swagger_path = Path(swagger_file)
        if not swagger_path.exists():
            typer.echo(f"Error: File not found: {swagger_file}", err=True)
            raise typer.Exit(1)

        try:
            file_content = swagger_path.read_text()

            # Try JSON first, then YAML
            try:
                openapi_def = json.loads(file_content)
            except json.JSONDecodeError:
                try:
                    openapi_def = yaml.safe_load(file_content)
                except yaml.YAMLError as yaml_err:
                    typer.echo(f"{safe_symbol('cross')} Invalid JSON/YAML format: {yaml_err}", err=True)
                    raise typer.Exit(1)
        except Exception as e:
            typer.echo(f"{safe_symbol('cross')} Error reading file: {e}", err=True)
            raise typer.Exit(1)

        # Run validation
        is_valid, error_msg = validate_openapi_definition(openapi_def)

        if verbose:
            typer.echo(f"\nValidating: {swagger_file}")
            typer.echo("-" * 50)

            # Show spec info
            info = openapi_def.get("info", {})
            typer.echo(f"Title: {info.get('title', 'N/A')}")
            typer.echo(f"Version: {info.get('version', 'N/A')}")
            typer.echo(f"Host: {openapi_def.get('host', 'N/A')}")
            typer.echo(f"Base Path: {openapi_def.get('basePath', 'N/A')}")
            typer.echo(f"Schemes: {', '.join(openapi_def.get('schemes', []))}")

            # Check OAuth
            security_defs = openapi_def.get("securityDefinitions", {})
            oauth_defs = [name for name, sec in security_defs.items() if sec.get("type") == "oauth2"]
            if oauth_defs:
                typer.echo(f"OAuth Definitions: {', '.join(oauth_defs)}")
                for oauth_name in oauth_defs:
                    oauth_def = security_defs[oauth_name]
                    typer.echo(f"  {oauth_name}:")
                    typer.echo(f"    Flow: {oauth_def.get('flow', 'N/A')}")
                    if oauth_def.get("tokenUrl"):
                        typer.echo(f"    Token URL: {oauth_def.get('tokenUrl')}")
                    if oauth_def.get("authorizationUrl"):
                        typer.echo(f"    Auth URL: {oauth_def.get('authorizationUrl')}")
                    scopes = oauth_def.get("scopes", {})
                    if scopes:
                        typer.echo(f"    Scopes: {', '.join(scopes.keys())}")

            # Count operations
            paths = openapi_def.get("paths", {})
            total_ops = 0
            methods_count = {}
            for path, methods in paths.items():
                for method in methods:
                    if method in ["get", "post", "put", "patch", "delete"]:
                        total_ops += 1
                        methods_count[method.upper()] = methods_count.get(method.upper(), 0) + 1

            typer.echo(f"Paths: {len(paths)}")
            typer.echo(f"Operations: {total_ops}")
            if methods_count:
                method_str = ", ".join(f"{m}: {c}" for m, c in sorted(methods_count.items()))
                typer.echo(f"  Methods: {method_str}")

            # Check file size
            size_bytes = len(json.dumps(openapi_def).encode('utf-8'))
            size_kb = size_bytes / 1024
            size_mb = size_kb / 1024
            typer.echo(f"Size: {size_kb:.1f} KB ({size_mb:.2f} MB)")

            typer.echo("-" * 50)

        if is_valid:
            typer.secho(f"{safe_symbol('check')} OpenAPI schema is valid for Power Platform", fg=typer.colors.GREEN)

            # Additional warnings for verbose mode
            if verbose:
                paths = openapi_def.get("paths", {})
                warnings = []

                # Check for missing operation IDs
                for path, methods in paths.items():
                    for method, details in methods.items():
                        if method in ["get", "post", "put", "patch", "delete"]:
                            if not details.get("operationId"):
                                warnings.append(f"Missing operationId: {method.upper()} {path}")

                # Check for internal visibility operations
                internal_count = 0
                for path, methods in paths.items():
                    for method, details in methods.items():
                        if method in ["get", "post", "put", "patch", "delete"]:
                            if details.get("x-ms-visibility") == "internal":
                                internal_count += 1

                if internal_count > 0:
                    warnings.append(f"{internal_count} operation(s) have internal visibility (won't appear as agent tools)")

                if warnings:
                    typer.echo("\nWarnings:")
                    for w in warnings:
                        typer.secho(f"  {safe_symbol('warning')}  {w}", fg=typer.colors.YELLOW)
        else:
            typer.secho(f"{safe_symbol('cross')} Validation failed: {error_msg}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("list")
def custom_connector_list(
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
    List all custom connectors in the environment.

    Custom connectors are user-created connectors that wrap custom APIs.
    This queries both Dataverse and Power Apps API for complete coverage.

    Examples:
        copilot custom-connector list --table
        copilot custom-connector list --filter "name:ilike:%asana%"
        copilot custom-connector list --limit 50
        copilot custom-connector list --raw
        copilot custom-connector list --properties "name,id,auth_types"
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

    try:
        client = get_client()
        connectors = client.list_connectors(custom_only=True)

        if not connectors:
            # Return empty JSON array for programmatic use, message for table output
            use_table = table or output == "table"
            if use_table:
                typer.echo("No custom connectors found in this environment.")
            else:
                print_json([])
            return

        # Raw output includes all metadata (filter on raw data)
        if raw:
            if filter:
                try:
                    validate_filters(filter)
                    connectors = apply_filters(connectors, filter)
                except FilterValidationError as e:
                    typer.echo(f"Error: {e}", err=True)
                    raise typer.Exit(1)

            if not connectors:
                print_json([])
                return

            # Apply limit
            connectors = connectors[:limit]
            print_json(connectors)
            return

        use_table = table or output == "table"

        # Format for display first, then apply filters
        # This ensures filter field names match output field names
        formatted = [format_connector_for_display(c, truncate=use_table) for c in connectors]

        # Apply filters using standard field:op:value syntax
        if filter:
            try:
                validate_filters(filter)
                formatted = apply_filters(formatted, filter)
            except FilterValidationError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(1)

        if not formatted:
            print_json([])
            return

        # Apply limit
        formatted = formatted[:limit]

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
                    columns=["name", "source", "auth_types", "id"],
                    headers=["Name", "Source", "Auth Types", "ID"],
                )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def custom_connector_get(
    connector_id: str = typer.Argument(
        ...,
        help="The connector's unique identifier (e.g., shared_pub-5fasana-...)",
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
    Get details for a custom connector including available operations.

    By default, shows only operations that can be used as Copilot agent tools.
    Deprecated and internal-visibility operations are hidden by default.

    Examples:
        copilot custom-connector get shared_pub-5fasana-... --table
        copilot custom-connector get <connector-id> --raw
        copilot custom-connector get <connector-id> --openapi
        copilot custom-connector get <connector-id> --openapi --output ./api-spec.json
    """
    try:
        client = get_client()

        # Helper function to find a custom connector by name or ID
        def find_custom_connector_by_name(name_or_id: str) -> dict | None:
            """Search for a custom connector by display name or ID."""
            custom_connectors = client.list_connectors(custom_only=True)
            matching = [
                c for c in custom_connectors
                if c.get("properties", {}).get("displayName", "").lower() == name_or_id.lower()
                or c.get("name", "").lower() == name_or_id.lower()
            ]
            if matching:
                # If we have multiple matches, prefer the one from Dataverse
                for c in matching:
                    if c.get("_source") == "dataverse":
                        return c
                return matching[0]
            return None

        # First, try to get the connector by ID
        connector = None
        try:
            connector = client.get_connector(connector_id)
        except Exception:
            # If lookup by ID fails, try to find by display name
            pass

        # If direct lookup failed, try to find by name
        if connector is None:
            connector = find_custom_connector_by_name(connector_id)
            if connector is None:
                typer.echo(
                    f"Error: No custom connector found with name or ID '{connector_id}'.",
                    err=True
                )
                typer.echo(
                    "Use 'copilot custom-connector list' to see available custom connectors.",
                    err=True
                )
                raise typer.Exit(1)
            # The list API doesn't return swagger, so fetch full details using the connector ID
            full_connector_id = connector.get("name", "")
            if full_connector_id:
                try:
                    connector = client.get_connector(full_connector_id)
                except Exception:
                    pass  # Keep the limited connector data if full fetch fails

        # Verify this is a custom connector, not a managed (Microsoft) connector
        if not is_custom_connector(connector):
            # The connector_id might be a display name - try to find a matching custom connector
            matching_custom = find_custom_connector_by_name(connector_id)

            if matching_custom:
                # Found a custom connector with matching name
                connector = matching_custom
            else:
                # No custom connector found with this name/ID
                typer.echo(
                    f"Error: '{connector_id}' is a managed (Microsoft) connector, not a custom connector.",
                    err=True
                )
                typer.echo(
                    f"Use 'copilot connector get {connector_id}' to view managed connectors.",
                    err=True
                )
                typer.echo(
                    "Use 'copilot custom-connector list' to see available custom connectors.",
                    err=True
                )
                raise typer.Exit(1)

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

        if table:
            # Table format with text headers
            typer.echo(f"\nConnector: {props.get('displayName', connector_id)}")
            typer.echo(f"ID: {connector.get('name', connector_id)}")

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
                "description": props.get("description", ""),
                "operations": operations,
            }
            # Include script/code fields if present
            if props.get("scriptOperations"):
                result["scriptOperations"] = props["scriptOperations"]
            if props.get("scriptDefinitionUrl"):
                result["scriptDefinitionUrl"] = props["scriptDefinitionUrl"]
            print_json(result)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def _normalize_json_schema_for_swagger(schema: dict) -> dict:
    """Normalize JSON Schema (draft-07) to Swagger 2.0 compatible subset.

    Converts features unsupported by Swagger 2.0:
    - {"type": ["string", "null"]} → {"type": "string", "x-nullable": true}
    - Strips: $defs, const, anyOf, oneOf (with warnings)
    """
    if not isinstance(schema, dict):
        return schema

    result = {}
    for key, value in schema.items():
        # Strip unsupported keywords
        if key in ("$defs", "const", "anyOf", "oneOf", "$schema", "$id"):
            continue

        # Convert nullable union types: ["string", "null"] → "string" + x-nullable
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            if len(non_null) == 1:
                result["type"] = non_null[0]
                if "null" in value:
                    result["x-nullable"] = True
            else:
                # Multiple non-null types — use first one (Swagger 2.0 limitation)
                result["type"] = non_null[0] if non_null else "string"
            continue

        # Recurse into nested schemas
        if key == "properties" and isinstance(value, dict):
            result["properties"] = {
                k: _normalize_json_schema_for_swagger(v)
                for k, v in value.items()
            }
            continue

        if key == "items" and isinstance(value, dict):
            result["items"] = _normalize_json_schema_for_swagger(value)
            continue

        result[key] = value

    return result


def _generate_expanded_mcp_openapi(
    name: str,
    description: str,
    host: str,
    base_path: str,
    mcp_path: str,
    scheme: str,
    url: str,
    tools_snapshot: str = None,
) -> dict:
    """Generate a Swagger 2.0 spec with one POST operation per MCP tool.

    Connects to the MCP server to discover tools via initialize + tools/list,
    or reads from a pre-captured snapshot file.
    """
    # Discover tools
    if tools_snapshot:
        snapshot_path = Path(tools_snapshot)
        if not snapshot_path.exists():
            raise ClientError(f"Tools snapshot file not found: {tools_snapshot}")
        tools = json.loads(snapshot_path.read_text())
        if isinstance(tools, dict) and "tools" in tools:
            tools = tools["tools"]
        typer.echo(f"Loaded {len(tools)} tools from snapshot: {tools_snapshot}", err=True)
    else:
        typer.echo(f"Connecting to MCP server: {url}", err=True)
        from .mcp import McpSession, _get_mcp_token_for_url
        token = _get_mcp_token_for_url(url)
        session = McpSession(url, token=token)
        session.initialize()
        result = session.request("tools/list")
        tools = result.get("tools", [])
        typer.echo(f"Discovered {len(tools)} MCP tools", err=True)

    if not tools:
        raise ClientError("MCP server returned no tools. Cannot generate expanded spec.")

    # Standard response schema for all MCP tool results
    tool_response_schema = {
        "description": "MCP tool execution result",
        "schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "text": {"type": "string"},
                        },
                    },
                },
                "isError": {"type": "boolean"},
            },
        },
    }

    # Build one path per tool
    paths = {}
    for tool in tools:
        tool_name = tool["name"]
        tool_desc = tool.get("description", "")
        # Strip XML tags from description for summary
        summary = tool_desc
        if "<usecase>" in summary:
            summary = summary.split("<usecase>")[1].split("</usecase>")[0]

        # Build path: /{connectionId}/mcp/tools/{tool_name}
        tool_path = f"{mcp_path}/tools/{tool_name}"

        operation = {
            "operationId": tool_name,
            "summary": summary[:120] if summary else tool_name,
            "description": tool_desc,
            "responses": {
                "200": tool_response_schema,
                "502": {"description": "MCP server error"},
            },
        }

        # Add body parameter from inputSchema if present
        input_schema = tool.get("inputSchema")
        if input_schema and input_schema.get("properties"):
            normalized = _normalize_json_schema_for_swagger(input_schema)
            operation["parameters"] = [
                {
                    "name": "body",
                    "in": "body",
                    "required": bool(normalized.get("required")),
                    "schema": normalized,
                }
            ]

        paths[tool_path] = {"post": operation}

    openapi_def = {
        "swagger": "2.0",
        "info": {
            "title": name,
            "description": description or f"MCP server: {name} (expanded tools)",
            "version": "1.0.0",
        },
        "host": host,
        "basePath": base_path,
        "schemes": [scheme],
        "paths": paths,
    }

    # Discover OAuth requirements from MCP server's well-known endpoint
    try:
        import httpx as _httpx
        resource_url = f"{scheme}://{host}/.well-known/oauth-protected-resource"
        resp = _httpx.get(resource_url, timeout=10)
        if resp.status_code == 200:
            oauth_info = resp.json()
            auth_servers = oauth_info.get("authorization_servers", [])
            scopes = oauth_info.get("scopes_supported", [])
            if auth_servers and scopes:
                auth_server = auth_servers[0].rstrip("/")
                # Azure AD v2.0 endpoints: the auth server URL may be
                # .../v2.0 but the authorize/token paths are under /oauth2/v2.0/
                if "/v2.0" in auth_server:
                    tenant_base = auth_server.replace("/v2.0", "")
                    auth_endpoint = f"{tenant_base}/oauth2/v2.0/authorize"
                    token_endpoint = f"{tenant_base}/oauth2/v2.0/token"
                    # Azure AD v2.0 requires offline_access for refresh tokens
                    if "offline_access" not in scopes:
                        scopes = scopes + ["offline_access"]
                else:
                    auth_endpoint = f"{auth_server}/oauth2/authorize"
                    token_endpoint = f"{auth_server}/oauth2/token"

                openapi_def["securityDefinitions"] = {
                    "oauth2": {
                        "type": "oauth2",
                        "flow": "accessCode",
                        "authorizationUrl": auth_endpoint,
                        "tokenUrl": token_endpoint,
                        "x-ms-refresh-url": token_endpoint,
                        "scopes": {s: s for s in scopes},
                    }
                }
                openapi_def["security"] = [{"oauth2": scopes}]
                typer.echo(f"OAuth configured: {len(scopes)} scopes from {auth_server}", err=True)
    except Exception:
        pass  # Non-OAuth MCP server, no security definitions needed

    typer.echo(f"Generated expanded OpenAPI spec: {len(tools)} operations", err=True)
    return openapi_def


@app.command("create")
def custom_connector_create(
    name: str = typer.Option(..., "--name", "-n", help="Display name for the connector"),
    swagger_file: Optional[str] = typer.Option(None, "--swagger-file", "-f", help="Path to OpenAPI 2.0 (Swagger) definition file"),
    connector_type: Optional[str] = typer.Option(None, "--type", "-T", help="Connector type: 'mcp' for MCP server (auto-generates OpenAPI spec from --url)"),
    url: Optional[str] = typer.Option(None, "--url", "-u", help="MCP server URL (used with --type mcp to auto-generate the OpenAPI spec)"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Connector description"),
    icon_brand_color: Optional[str] = typer.Option("#007ee5", "--icon-brand-color", help="Icon brand color (hex format)"),
    environment: Optional[str] = typer.Option(None, "--environment", "--env", help="Environment ID (defaults to configured environment)"),
    oauth_client_id: Optional[str] = typer.Option(None, "--oauth-client-id", help="OAuth 2.0 Client ID (required for OAuth connectors)"),
    oauth_client_secret: Optional[str] = typer.Option(None, "--oauth-client-secret", help="OAuth 2.0 Client Secret (required for OAuth connectors)"),
    oauth_redirect_url: Optional[str] = typer.Option(None, "--oauth-redirect-url", help="Custom OAuth redirect URL (overrides default Power Platform redirect URL)"),
    oauth_identity_provider: Optional[str] = typer.Option(None, "--oauth-identity-provider", help="OAuth identity provider preset: oauth2|aad|google|github|facebook. Defaults to oauth2."),
    script: Optional[str] = typer.Option(None, "--script", "-x", help="Path to C# script file (.csx) for custom code transformations"),
    script_operations: Optional[str] = typer.Option(None, "--script-operations", help="Comma-separated list of operationIds that use the script (defaults to all operations)"),
    expand_tools: bool = typer.Option(False, "--expand-tools", help="For MCP connectors: expand each MCP tool into an individual connector operation (requires --type mcp --url)"),
    tools_snapshot: Optional[str] = typer.Option(None, "--tools-snapshot", help="Path to a pre-captured MCP tools/list JSON response (for offline/CI use with --expand-tools)"),
):
    """
    Create a new custom connector from an OpenAPI 2.0 (Swagger) definition.

    The OpenAPI definition must be in OpenAPI 2.0 format (not 3.0).

    For MCP (Model Context Protocol) servers, use --type mcp with --url to
    auto-generate the OpenAPI spec. The generated spec includes the required
    x-ms-agentic-protocol extension for Copilot Studio MCP integration.

    For OAuth connectors, provide --oauth-client-id and --oauth-client-secret.
    Without these, the connector will be created but connections cannot authenticate.

    For custom code (request/response transformations), use --script to specify
    a C# script file (.csx). The script can modify requests before they're sent
    to the API and responses before they're returned.

    After creating the connector, use 'copilot connections create' to create a
    connection and authenticate.

    Examples:
      # MCP server connector (single InvokeMCP operation with x-ms-agentic-protocol)
      copilot custom-connector create --name "My MCP Server" --type mcp \\
        --url "https://mcp.example.com/sse"

      # MCP server with expanded tools (one operation per MCP tool + C# session script)
      copilot custom-connector create --name "My MCP Server" --type mcp \\
        --url "https://mcp.example.com/sse" --expand-tools \\
        --script ./mcp_connector_code.csx

      # Expanded tools with offline snapshot (for CI)
      copilot custom-connector create --name "My MCP Server" --type mcp \\
        --url "https://mcp.example.com/sse" --expand-tools \\
        --tools-snapshot ./tools_list.json --script ./mcp_connector_code.csx

      # Basic connector (non-OAuth)
      copilot custom-connector create --name "My API" --swagger-file ./api.json

      # OAuth connector with credentials
      copilot custom-connector create --name "My API" --swagger-file ./api.json \\
        --oauth-client-id "client123" --oauth-client-secret "secret456"

      # Then create a connection
      copilot connections create --connector-id <connector-id> --name "My Connection" --oauth
    """
    try:
        # Validate type option
        is_mcp = connector_type and connector_type.lower() == "mcp"

        if is_mcp:
            if not url:
                typer.echo("Error: --url is required when --type mcp is specified.", err=True)
                raise typer.Exit(1)

            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = parsed.netloc
            base_path = "/"
            mcp_path = parsed.path or "/mcp"
            if mcp_path == "/":
                mcp_path = "/mcp"

            if expand_tools:
                # Expanded mode: discover tools and generate one operation per tool
                openapi_def = _generate_expanded_mcp_openapi(
                    name=name,
                    description=description,
                    host=host,
                    base_path=base_path,
                    mcp_path=mcp_path,
                    scheme=parsed.scheme or "https",
                    url=url,
                    tools_snapshot=tools_snapshot,
                )
            else:
                # Standard mode: single InvokeMCP operation with x-ms-agentic-protocol
                if expand_tools is False and tools_snapshot:
                    typer.echo("Warning: --tools-snapshot is ignored without --expand-tools", err=True)
                openapi_def = {
                    "swagger": "2.0",
                    "info": {
                        "title": name,
                        "description": description or f"MCP server: {name}",
                        "version": "1.0.0",
                    },
                    "host": host,
                    "basePath": base_path,
                    "schemes": [parsed.scheme or "https"],
                    "paths": {
                        mcp_path: {
                            "post": {
                                "summary": f"{name} MCP Server",
                                "description": description or f"Invoke the {name} MCP server. Tools and resources are dynamically discovered at runtime.",
                                "x-ms-agentic-protocol": "mcp-streamable-1.0",
                                "operationId": "InvokeMCP",
                                "responses": {
                                    "200": {"description": "Success"}
                                },
                            }
                        }
                    },
                }
                typer.echo(f"Generated MCP OpenAPI spec for {host}{mcp_path}", err=True)

        elif swagger_file:
            # Read and parse OpenAPI file
            swagger_path = Path(swagger_file)
            if not swagger_path.exists():
                typer.echo(f"Error: File not found: {swagger_file}", err=True)
                raise typer.Exit(1)

            try:
                file_content = swagger_path.read_text()

                # Try JSON first, then YAML
                try:
                    openapi_def = json.loads(file_content)
                except json.JSONDecodeError:
                    try:
                        openapi_def = yaml.safe_load(file_content)
                    except yaml.YAMLError as yaml_err:
                        typer.echo(f"Error: Invalid JSON/YAML format: {yaml_err}", err=True)
                        raise typer.Exit(1)
            except Exception as e:
                typer.echo(f"Error reading file: {e}", err=True)
                raise typer.Exit(1)
        else:
            typer.echo("Error: Either --swagger-file or --type mcp --url must be provided.", err=True)
            raise typer.Exit(1)

        # Validate OpenAPI definition (skip for MCP - the spec is auto-generated and minimal)
        if not is_mcp:
            is_valid, error_msg = validate_openapi_definition(openapi_def)
            if not is_valid:
                typer.echo(f"Error: {error_msg}", err=True)
                raise typer.Exit(1)

        # Check if connector uses OAuth and validate credentials
        security_defs = openapi_def.get("securityDefinitions", {})
        uses_oauth = any(sec.get("type") == "oauth2" for sec in security_defs.values())

        if uses_oauth:
            if not oauth_client_id or not oauth_client_secret:
                typer.echo("Error: This connector uses OAuth 2.0 authentication.", err=True)
                typer.echo("You must provide --oauth-client-id and --oauth-client-secret.", err=True)
                raise typer.Exit(1)

        # Validate script file if provided
        script_file = None
        if script:
            script_path = Path(script)
            if not script_path.exists():
                typer.echo(f"Error: Script file not found: {script}", err=True)
                raise typer.Exit(1)
            if not script_path.suffix.lower() in ['.csx', '.cs']:
                typer.echo(f"Warning: Script file should be a C# script (.csx or .cs): {script}", err=True)
            script_file = str(script_path.resolve())

        # Parse script operations if provided
        ops_list = None
        if script_operations:
            ops_list = [op.strip() for op in script_operations.split(',') if op.strip()]
            if not ops_list:
                typer.echo("Error: --script-operations requires at least one operation ID", err=True)
                raise typer.Exit(1)

        # Create connector
        client = get_client()
        result = client.create_custom_connector(
            name=name,
            openapi_definition=openapi_def,
            description=description,
            icon_brand_color=icon_brand_color or "#007ee5",
            environment_id=environment,
            oauth_client_id=oauth_client_id,
            oauth_client_secret=oauth_client_secret,
            oauth_redirect_url=oauth_redirect_url,
            oauth_identity_provider=oauth_identity_provider,
            script_file=script_file,
            script_operations=ops_list,
        )

        connector_id = result["connector_id"]
        environment_id = result["environment_id"]

        print_success(f"Custom connector '{name}' created successfully!")
        typer.echo(f"Connector ID: {connector_id}")
        typer.echo(f"Environment: {environment_id}")
        if script_file:
            typer.echo(f"Custom Code: Enabled ({Path(script_file).name})")

        # Auto-register in Dataverse (required for connection references and agent tools)
        typer.echo("Registering in Dataverse...", err=True)
        try:
            entity_id = client.register_connector_in_dataverse(
                connector_id=connector_id,
                display_name=name,
                openapi_definition=openapi_def,
                description=description,
                icon_brand_color=icon_brand_color or "#007ee5",
            )
            if entity_id:
                typer.echo(f"Dataverse Entity ID: {entity_id}")
        except Exception as reg_err:
            typer.echo(f"Warning: Dataverse registration failed: {reg_err}", err=True)
            typer.echo(f"  You can register manually: copilot custom-connector register {connector_id} --swagger-file <path> --force", err=True)

        typer.echo()

        # Show next steps
        typer.echo("Next Steps:")

        if is_mcp:
            typer.echo(f"1. Create a connection: copilot connections create --connector-id {connector_id} --name \"{name} Connection\"")
            typer.echo(f"2. Add to agent: copilot agent tool add -a <agent-id> --toolType connector --id \"{connector_id}:InvokeMCP\" --connection-reference-id <ref-id> --name \"{name}\"")
        elif uses_oauth:
            # Note: Power Platform strips the "shared_" prefix from connector_id for OAuth redirect URL
            redirect_connector_id = connector_id.replace("shared_", "", 1) if connector_id.startswith("shared_") else connector_id
            typer.echo()
            typer.echo("1. Register this redirect URL in your OAuth app settings:")
            typer.echo(f"   https://global.consent.azure-apim.net/redirect/{redirect_connector_id}")
            typer.echo()
            typer.echo("   Or use wildcard (if supported): https://global.consent.azure-apim.net/redirect/*")
            typer.echo()
            typer.echo("2. Create a connection:")
            typer.echo(f"   copilot connections create --connector-id {connector_id} --name \"My Connection\" --oauth")
        else:
            typer.echo(f"1. Test the connector: copilot custom-connector get {connector_id}")
            typer.echo(f"2. Create a connection: copilot connections create --connector-id {connector_id} --name \"My Connection\"")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
def custom_connector_update(
    connector_id: str = typer.Argument(..., help="The connector's unique identifier (e.g., shared_pub-5fasana-...)"),
    swagger_file: Optional[str] = typer.Option(None, "--swagger-file", "-f", help="Path to OpenAPI 2.0 (Swagger) definition file"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Connector description"),
    icon_brand_color: Optional[str] = typer.Option(None, "--icon-brand-color", help="Icon brand color (hex format)"),
    environment: Optional[str] = typer.Option(None, "--environment", "--env", help="Environment ID (defaults to configured environment)"),
    oauth_client_id: Optional[str] = typer.Option(None, "--oauth-client-id", help="OAuth 2.0 Client ID"),
    oauth_client_secret: Optional[str] = typer.Option(None, "--oauth-client-secret", help="OAuth 2.0 Client Secret"),
    oauth_redirect_url: Optional[str] = typer.Option(None, "--oauth-redirect-url", help="Custom OAuth redirect URL"),
    oauth_identity_provider: Optional[str] = typer.Option(None, "--oauth-identity-provider", help="OAuth identity provider preset: oauth2|aad|google|github|facebook"),
    script: Optional[str] = typer.Option(None, "--script", "-x", help="Path to C# script file (.csx) for custom code transformations"),
    script_operations: Optional[str] = typer.Option(None, "--script-operations", help="Comma-separated list of operationIds that use the script"),
):
    """
    Update an existing custom connector.

    You can update the OpenAPI definition, description, custom code script, or
    authentication settings. Only provided options will be updated; other settings
    are preserved.

    To add or update custom code, use --script to specify a C# script file (.csx).
    The script can modify requests before they're sent to the API and responses
    before they're returned.

    Examples:
      # Update OpenAPI definition
      copilot custom-connector update shared_myapi-... --swagger-file ./api-v2.json

      # Add custom code script to existing connector
      copilot custom-connector update shared_myapi-... --script ./code.csx

      # Update script for specific operations only
      copilot custom-connector update shared_myapi-... --script ./code.csx --script-operations "CreateTask,UpdateTask"

      # Update description only
      copilot custom-connector update shared_myapi-... --description "Updated API connector"
    """
    try:
        # Parse OpenAPI file if provided
        openapi_def = None
        if swagger_file:
            swagger_path = Path(swagger_file)
            if not swagger_path.exists():
                typer.echo(f"Error: File not found: {swagger_file}", err=True)
                raise typer.Exit(1)

            try:
                file_content = swagger_path.read_text()

                # Try JSON first, then YAML
                try:
                    openapi_def = json.loads(file_content)
                except json.JSONDecodeError:
                    try:
                        openapi_def = yaml.safe_load(file_content)
                    except yaml.YAMLError as yaml_err:
                        typer.echo(f"Error: Invalid JSON/YAML format: {yaml_err}", err=True)
                        raise typer.Exit(1)
            except Exception as e:
                typer.echo(f"Error reading file: {e}", err=True)
                raise typer.Exit(1)

            # Validate OpenAPI definition
            is_valid, error_msg = validate_openapi_definition(openapi_def)
            if not is_valid:
                typer.echo(f"Error: {error_msg}", err=True)
                raise typer.Exit(1)

        # Validate script file if provided
        script_file = None
        if script:
            script_path = Path(script)
            if not script_path.exists():
                typer.echo(f"Error: Script file not found: {script}", err=True)
                raise typer.Exit(1)
            if not script_path.suffix.lower() in ['.csx', '.cs']:
                typer.echo(f"Warning: Script file should be a C# script (.csx or .cs): {script}", err=True)
            script_file = str(script_path.resolve())

        # Parse script operations if provided
        ops_list = None
        if script_operations:
            ops_list = [op.strip() for op in script_operations.split(',') if op.strip()]
            if not ops_list:
                typer.echo("Error: --script-operations requires at least one operation ID", err=True)
                raise typer.Exit(1)

        # Check if any update options provided
        if not any([swagger_file, description, icon_brand_color, script, oauth_client_id, oauth_client_secret, oauth_identity_provider]):
            typer.echo("Error: No update options provided. Use --help to see available options.", err=True)
            raise typer.Exit(1)

        # Resolve connector name/ID to actual custom connector ID
        client = get_client()

        # Helper function to find a custom connector by name or ID
        def find_custom_connector_by_name(name_or_id: str) -> dict | None:
            """Search for a custom connector by display name or ID."""
            custom_connectors = client.list_connectors(custom_only=True)
            matching = [
                c for c in custom_connectors
                if c.get("properties", {}).get("displayName", "").lower() == name_or_id.lower()
                or c.get("name", "").lower() == name_or_id.lower()
            ]
            if matching:
                # If we have multiple matches, prefer the one from Dataverse
                for c in matching:
                    if c.get("_source") == "dataverse":
                        return c
                return matching[0]
            return None

        # First, try to get the connector by ID to verify it exists
        connector = None
        try:
            connector = client.get_connector(connector_id)
        except Exception:
            # If lookup by ID fails, try to find by display name
            pass

        # If direct lookup failed or returned a managed connector, try to find by name
        if connector is None or not is_custom_connector(connector):
            custom_connector = find_custom_connector_by_name(connector_id)
            if custom_connector:
                # Use the resolved custom connector ID
                resolved_id = custom_connector.get("name", "")
                if resolved_id:
                    connector_id = resolved_id
                    connector = custom_connector
            elif connector is not None and not is_custom_connector(connector):
                # Found a managed connector but no matching custom connector
                typer.echo(
                    f"Error: '{connector_id}' is a managed (Microsoft) connector, not a custom connector.",
                    err=True
                )
                typer.echo(
                    "Use 'copilot custom-connector list' to see available custom connectors.",
                    err=True
                )
                raise typer.Exit(1)
            else:
                typer.echo(
                    f"Error: No custom connector found with name or ID '{connector_id}'.",
                    err=True
                )
                typer.echo(
                    "Use 'copilot custom-connector list' to see available custom connectors.",
                    err=True
                )
                raise typer.Exit(1)

        # Update connector
        result = client.update_custom_connector(
            connector_id=connector_id,
            openapi_definition=openapi_def,
            description=description,
            icon_brand_color=icon_brand_color,
            environment_id=environment,
            oauth_client_id=oauth_client_id,
            oauth_client_secret=oauth_client_secret,
            oauth_redirect_url=oauth_redirect_url,
            oauth_identity_provider=oauth_identity_provider,
            script_file=script_file,
            script_operations=ops_list,
        )

        typer.echo(f"Display Name: {result.get('display_name', 'N/A')}")
        print_success(f"Connector '{connector_id}' updated successfully!")
        if result.get("script_uploaded"):
            typer.echo(f"Custom Code: Updated ({Path(script_file).name})")

        # Warn about connection refresh when swagger is updated
        if swagger_file:
            typer.echo("")
            typer.secho(
                "WARNING: Existing connections may cache the old schema.",
                fg=typer.colors.YELLOW,
                bold=True
            )
            typer.echo("   To use new/modified operations, you may need to:")
            typer.echo("   1. Delete and recreate connections for this connector")
            typer.echo("   2. Update connection references with the new connection ID")
            typer.echo("")
            typer.echo("   Commands:")
            typer.echo(f"   copilot connections list --connector-id {connector_id} --table")
            typer.echo(f"   copilot connections delete <connection-id> -c {connector_id} --force")
            typer.echo(f"   copilot connections create -c {connector_id} -n \"<name>\" --oauth")
            typer.echo(f"   copilot connection-references update <ref-id> --connection-id <new-connection-id>")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("register")
def custom_connector_register(
    connector_id: str = typer.Argument(
        ...,
        help="The connector's unique identifier (e.g., shared_asana-20custom-...)",
    ),
    swagger_file: str = typer.Option(
        ...,
        "--swagger-file",
        "-f",
        help="Path to the original OpenAPI 2.0 (Swagger) definition file used to create the connector",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Skip confirmation prompt",
    ),
):
    """
    Register a custom connector in Dataverse.

    Custom connectors created via Power Apps API are not automatically registered
    in Dataverse. This command creates a record in the Dataverse connector table
    so that connection references can properly link to the connector via
    CustomConnectorId.

    This is required for connector operations to be properly discovered by
    Copilot Studio agents. Without Dataverse registration, you may see
    "ConnectorOperationNotFound" errors.

    IMPORTANT: You must provide the ORIGINAL OpenAPI schema file that was used
    to create the connector. The schema stored in Power Apps is modified and
    cannot be used directly.

    Examples:
        copilot custom-connector register shared_asana-20custom-... --swagger-file ./connector.json
        copilot custom-connector register <connector-id> -f ./api.json --force
    """
    try:
        client = get_client()

        # Read and parse the original OpenAPI file
        swagger_path = Path(swagger_file)
        if not swagger_path.exists():
            typer.echo(f"Error: File not found: {swagger_file}", err=True)
            raise typer.Exit(1)

        try:
            file_content = swagger_path.read_text()
            try:
                swagger = json.loads(file_content)
            except json.JSONDecodeError:
                try:
                    swagger = yaml.safe_load(file_content)
                except yaml.YAMLError as yaml_err:
                    typer.echo(f"Error: Invalid JSON/YAML format: {yaml_err}", err=True)
                    raise typer.Exit(1)
        except Exception as e:
            typer.echo(f"Error reading file: {e}", err=True)
            raise typer.Exit(1)

        # Get connector details from Power Apps API
        typer.echo(f"Looking up connector: {connector_id}...")
        connector = client.get_connector(connector_id)

        props = connector.get("properties", {})
        display_name = props.get("displayName", connector_id)
        description = props.get("description", "")

        # Check if already registered in Dataverse
        dataverse = connector.get("_dataverse", {})
        existing_entity_id = dataverse.get("connectorid")

        if existing_entity_id:
            typer.echo(f"Connector '{display_name}' is already registered in Dataverse.")
            typer.echo(f"Entity ID: {existing_entity_id}")
            return

        source = connector.get("_source", "unknown")
        if source != "powerapps":
            typer.echo(f"Connector source: {source}")
            typer.echo("Only Power Apps connectors need to be registered in Dataverse.")
            typer.echo("This connector may already be properly registered.")
            if not force:
                typer.echo("Use --force to attempt registration anyway.")
                raise typer.Exit(0)

        # Confirm registration
        if not force:
            typer.echo(f"\nConnector: {display_name}")
            typer.echo(f"ID: {connector_id}")
            typer.echo(f"Source: {source}")
            typer.echo()
            typer.echo("This will register the connector in Dataverse, enabling proper")
            typer.echo("connection reference linking for Copilot Studio agents.")
            typer.echo()
            if not typer.confirm("Continue?", default=False):
                typer.echo("Cancelled.")
                raise typer.Exit(0)

        # Register in Dataverse
        typer.echo("\nRegistering connector in Dataverse...")
        entity_id = client.register_connector_in_dataverse(
            connector_id=connector_id,
            display_name=display_name,
            openapi_definition=swagger,
            description=description,
        )

        if entity_id:
            print_success(f"Connector '{display_name}' registered successfully!")
            typer.echo(f"Dataverse Entity ID: {entity_id}")
            typer.echo()
            typer.echo("Next steps:")
            typer.echo("1. Recreate the connection reference to link it properly:")
            typer.echo(f"   copilot connection-references list --table")
            typer.echo(f"   copilot connection-references remove <ref-id> --force")
            typer.echo(f"   copilot connection-references create --name \"<name>\" --connection-id <conn-id>")
        else:
            typer.echo("Failed to register connector in Dataverse.", err=True)
            typer.echo("This may be a permissions issue or the connector schema may be invalid.", err=True)
            raise typer.Exit(1)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("delete")
@app.command("remove")
def custom_connector_delete(
    connector_id: str = typer.Argument(
        ...,
        help="Connector ID (e.g., shared_asana-20test-5fd251...) or display name (e.g., 'My Custom Connector')",
    ),
    environment: Optional[str] = typer.Option(
        None,
        "--environment",
        "--env",
        help="Power Platform environment ID. Uses DATAVERSE_ENVIRONMENT_ID if not specified.",
    ),
    cascade: bool = typer.Option(
        False,
        "--cascade",
        help="Also delete all connections, connection references, and agent tools associated with this connector",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Delete a custom connector by ID or name.

    This permanently removes a custom connector from the Power Platform environment.
    You can specify either the connector ID (shared_...) or the display name. If
    multiple connectors match the name, all matches are shown and each is deleted.

    Warning: Deleting a connector may break flows or agents that depend on it.

    Use --cascade to recursively delete everything associated with this connector:
      1. Agent connector tools using connections for this connector
      2. Connection references pointing to connections for this connector
      3. Connections created for this connector
      4. The connector itself

    Examples:
        copilot custom-connector delete shared_asana-20test-5fd251d00ef0afcb57-5fe2f45645c919b585
        copilot custom-connector delete "My Custom Connector"
        copilot custom-connector delete "My Connector" --cascade
        copilot custom-connector delete <connector-id> --force
        copilot custom-connector delete <connector-id> --env Default-xxx
        copilot custom-connector delete <connector-id> --cascade
    """
    try:
        client = get_client()

        # Resolve environment ID if not provided
        if not environment:
            from ..config import get_config
            config = get_config()
            environment = config.environment_id
            if not environment:
                typer.echo("Error: Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID.", err=True)
                raise typer.Exit(1)

        # Resolve connector_id: if it doesn't look like an API ID, search by name
        is_api_id = connector_id.startswith("shared_") or "/" in connector_id
        matched_connectors = []

        if not is_api_id:
            typer.echo(f"Searching for connectors matching '{connector_id}'...")
            all_connectors = client.list_connectors(custom_only=True, environment_id=environment)
            seen_ids = set()
            for c in all_connectors:
                c_name = c.get("properties", {}).get("displayName", "")
                c_id = c.get("name", "")
                if c_name.lower() == connector_id.lower() and c_id not in seen_ids:
                    matched_connectors.append(c)
                    seen_ids.add(c_id)

            if not matched_connectors:
                typer.echo(f"Error: No custom connectors found with name '{connector_id}'.", err=True)
                raise typer.Exit(1)

            if len(matched_connectors) > 1:
                typer.echo(f"Found {len(matched_connectors)} connectors matching '{connector_id}':")
                for i, c in enumerate(matched_connectors, 1):
                    c_props = c.get("properties", {})
                    c_id = c.get("name", c.get("connectorinternalid", ""))
                    typer.echo(f"  {i}. {c_props.get('displayName', '?')} ({c_id})")
                typer.echo(f"\nAll {len(matched_connectors)} will be deleted.")

        if matched_connectors:
            # Delete each matched connector
            for c in matched_connectors:
                c_props = c.get("properties", {})
                c_id = c.get("name", c.get("connectorinternalid", ""))
                c_name = c_props.get("displayName", c_id)
                if not c_id:
                    typer.echo(f"  Skipping connector with no ID: {c_name}", err=True)
                    continue
                typer.echo(f"\n--- Deleting connector: {c_name} ({c_id}) ---")
                _delete_single_connector(client, c_id, c_name, environment, cascade, force)

            return

        # Direct ID path: get connector details to show what will be deleted
        connector_name = connector_id
        try:
            connector = client.get_connector(connector_id, environment)
            props = connector.get("properties", {})
            connector_name = props.get("displayName", connector_id)

            # Valid connector found
            typer.echo(f"Verified connector: {connector_name}")

        except Exception as e:
            # Handle specific error cases
            error_msg = str(e)

            # Check for 404 Not Found (often buried in the error message)
            if "404" in error_msg or "NotFound" in error_msg:
                typer.echo(f"Error: Connector '{connector_id}' not found in environment '{environment}'.", err=True)
                if not force:
                    typer.echo("Aborting. Use --force to attempt deletion anyway.", err=True)
                    raise typer.Exit(1)
                typer.echo("Warning: Connector not found, but proceeding due to --force.", err=True)
                connector_name = connector_id

            # Check for 403 Forbidden
            elif "403" in error_msg or "Forbidden" in error_msg or "Access Denied" in error_msg:
                typer.echo(f"Error: Permission denied for connector '{connector_id}'.", err=True)
                typer.echo("This is likely due to a Data Loss Prevention (DLP) policy blocking access.", err=True)
                if not force:
                    typer.echo("Aborting. Use --force to attempt deletion anyway.", err=True)
                    raise typer.Exit(1)
                typer.echo("Warning: Permission denied, but proceeding due to --force.", err=True)
                connector_name = connector_id

            else:
                # Unknown error
                typer.echo(f"Warning: Could not verify connector details: {e}", err=True)
                if not force:
                    typer.echo("Aborting. Use --force to attempt deletion anyway.", err=True)
                    raise typer.Exit(1)
                connector_name = connector_id

        _delete_single_connector(client, connector_id, connector_name, environment, cascade, force)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def _delete_single_connector(
    client, connector_id: str, connector_name: str, environment: str,
    cascade: bool, force: bool,
):
    """Delete a single connector with optional cascade and confirmation."""
    # Confirm deletion unless --force
    if not force:
        typer.echo(f"\nConnector: {connector_name}")
        typer.echo(f"ID: {connector_id}")
        typer.echo()
        typer.echo("Warning: This will permanently delete the connector.")
        typer.echo("   Any flows or agents using this connector may break.")
        typer.echo()
        if not typer.confirm("Continue?", default=False):
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    # Handle cascade deletion
    if cascade:
        typer.echo("\nCascading deletion requested. Checking for associated resources...")

        # 1. Find and delete all agent connector tools using this connector
        all_connector_tools = client.list_tools(category='connector')
        # Filter tools that use this connector (connector_id appears in connectionReference path)
        matching_tools = [
            tool for tool in all_connector_tools
            if connector_id in (tool.get("data") or "")
        ]

        if matching_tools:
            typer.echo(f"Found {len(matching_tools)} agent tool(s) using this connector. Deleting...")
            for tool in matching_tools:
                tool_id = tool.get("botcomponentid")
                tool_name = tool.get("name") or tool.get("schemaname") or tool_id
                try:
                    client.remove_tool(tool_id)
                    typer.echo(f"  Deleted tool: {tool_name}")
                except Exception as e:
                    typer.echo(f"  Failed to delete tool {tool_name}: {e}", err=True)
        else:
            typer.echo("No agent tools found using this connector.")

        # 2. Delete all connection references for this connector (by connector_id)
        refs = client.list_connection_references(connector_id=connector_id)
        if refs:
            typer.echo(f"Found {len(refs)} connection reference(s). Deleting...")
            for ref in refs:
                ref_id = ref.get("connectionreferenceid")
                ref_name = ref.get("connectionreferencedisplayname", "Unnamed")
                try:
                    client.delete_connection_reference(ref_id)
                    typer.echo(f"  Deleted reference: {ref_name}")
                except Exception as e:
                    if "404" in str(e):
                        typer.echo(f"  {safe_symbol('check')} Reference already removed by Dataverse: {ref_name}")
                    else:
                        typer.echo(f"  Failed to delete reference {ref_name}: {e}", err=True)
        else:
            typer.echo("No connection references found for this connector.")

        # 3. Get all connections for this connector and delete them
        connections = client.list_connections(connector_id, environment)
        if connections:
            typer.echo(f"Found {len(connections)} connection(s). Deleting...")
            for conn in connections:
                conn_id = conn.get("name")
                conn_name = conn.get("properties", {}).get("displayName", conn_id)
                try:
                    client.delete_connection(conn_id, connector_id, environment)
                    typer.echo(f"  Deleted connection: {conn_name}")
                except Exception as e:
                    typer.echo(f"  Failed to delete connection {conn_name}: {e}", err=True)
        else:
            typer.echo("No connections found for this connector.")

        typer.echo("\nProceeding to delete connector...")

    # Delete the connector from both Dataverse and Power Apps API
    results = client.delete_custom_connector(connector_id, environment, display_name=connector_name)

    print_success(f"Connector '{connector_name}' deleted successfully!")
    typer.echo(f"Connector ID: {connector_id}")

    # Show deletion results from each source
    dataverse_status = results.get("dataverse", "unknown")
    powerapps_status = results.get("powerapps", "unknown")
    typer.echo(f"  Dataverse: {dataverse_status}")
    typer.echo(f"  Power Apps API: {powerapps_status}")

    # Show ghost cleanup results if any
    ghost_cleanup = results.get("ghost_cleanup", [])
    if ghost_cleanup:
        typer.echo(f"  Ghost cleanup: removed {len(ghost_cleanup)} additional entries")
        for ghost_entry in ghost_cleanup:
            typer.echo(f"    - {ghost_entry}")
