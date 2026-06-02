"""Connection commands for managing Power Platform connections."""
import typer
from typing import Optional, List, Dict, Any

from ..client import get_client, ClientError
from ..config import get_config
from cli_tools_shared.output import print_json, print_table, print_success, handle_error, safe_symbol
from . import connections_onedrive
from . import connections_operations
from .custom_connector import is_custom_connector


from typer.core import TyperGroup


class _ConnectionsGroup(TyperGroup):
    """Custom Click group: intercepts `<guid> operations ...` before normal resolution."""

    def resolve_command(self, ctx, args):
        # Detect: <guid> operations <subcmd> ...
        # If the first arg isn't a known command but 'operations' appears second,
        # treat the first arg as connection_id and forward to the operations sub-app.
        if len(args) >= 2 and args[1] == "operations":
            cmd_name = args[0]
            # Only intercept if it's NOT a known command (i.e., it's a GUID)
            if cmd_name not in self.commands:
                connections_operations.set_connection_id(cmd_name)
                # Remove the connection_id, leave "operations ..."
                args.pop(0)
                return super().resolve_command(ctx, args)
        return super().resolve_command(ctx, args)


app = typer.Typer(
    help="Manage Power Platform connections (authenticated credentials)",
    cls=_ConnectionsGroup,
)
app.add_typer(connections_onedrive.app, name="onedrive")
app.add_typer(connections_operations.app, name="operations")

COMMAND_CREDENTIALS = {
    "auth": [
        "custom"
    ],
    "bind": [
        "custom"
    ],
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
    "onedrive": [
        "custom"
    ],
    "operations": [
        "custom"
    ],
    "remove": [
        "custom"
    ],
    "test": [
        "custom"
    ]
}


def extract_connector_auth_types(connector: dict) -> List[Dict[str, Any]]:
    """
    Extract available authentication types from a connector definition.

    Args:
        connector: The connector definition from the API

    Returns:
        List of auth type dicts with 'name', 'display_name', and 'is_oauth' keys.
        Empty list if single-auth connector (use connectionParameters instead).
    """
    props = connector.get("properties", {})
    auth_types = []

    # Check for multi-auth via connectionParameterSets
    param_sets = props.get("connectionParameterSets", {})
    if param_sets and isinstance(param_sets, dict):
        values = param_sets.get("values", [])
        for value in values:
            name = value.get("name", "")
            if name:
                ui_def = value.get("uiDefinition", {})
                display_name = ui_def.get("displayName", name)

                # Determine if this is an OAuth-based auth type
                parameters = value.get("parameters", {})
                is_oauth = False
                for param_def in parameters.values():
                    if isinstance(param_def, dict):
                        if param_def.get("type") == "oauthSetting":
                            is_oauth = True
                            break

                auth_types.append({
                    "name": name,
                    "display_name": display_name,
                    "is_oauth": is_oauth,
                })

    return auth_types


def _get_oauth_configuration_issues(connector: dict) -> List[str]:
    """Return missing visible OAuth configuration fields for a connector."""
    props = connector.get("properties", {})
    conn_params = props.get("connectionParameters", {})
    token_def = conn_params.get("token") or conn_params.get("Token", {})
    oauth_settings = token_def.get("oAuthSettings", {}) if isinstance(token_def, dict) else {}
    custom_params = oauth_settings.get("customParameters", {})

    issues: List[str] = []
    if not oauth_settings.get("clientId"):
        issues.append("client ID")

    security_defs = props.get("swagger", {}).get("securityDefinitions", {})
    requires_auth_urls = any(
        isinstance(sec_def, dict)
        and sec_def.get("type") == "oauth2"
        and sec_def.get("flow") == "accessCode"
        for sec_def in security_defs.values()
    )
    if requires_auth_urls and not custom_params.get("authorizationUrl", {}).get("value"):
        issues.append("authorization URL")
    if not custom_params.get("tokenUrl", {}).get("value"):
        issues.append("token URL")
    if requires_auth_urls and not custom_params.get("refreshUrl", {}).get("value"):
        issues.append("refresh URL")

    return issues


def get_auth_type_parameters(connector: dict, auth_type_name: str) -> Dict[str, Dict[str, Any]]:
    """
    Get the parameter definitions for a specific auth type.

    Args:
        connector: The connector definition from the API
        auth_type_name: The name of the auth type (e.g., "ServicePrincipalOauth")

    Returns:
        Dict mapping parameter names to their definitions, including:
        - type: Parameter type (string, securestring, oauthSetting)
        - display_name: Human-readable name
        - description: Parameter description
        - required: Whether the parameter is required
        - hidden: Whether the parameter is hidden in UI
    """
    props = connector.get("properties", {})
    param_sets = props.get("connectionParameterSets", {})

    if not param_sets:
        return {}

    values = param_sets.get("values", [])
    for value in values:
        if value.get("name") == auth_type_name:
            raw_params = value.get("parameters", {})
            result = {}

            for param_name, param_def in raw_params.items():
                if not isinstance(param_def, dict):
                    continue

                ui_def = param_def.get("uiDefinition", {})
                constraints = ui_def.get("constraints", {})

                # Parse required/hidden as booleans (they come as strings)
                required = constraints.get("required", "false")
                if isinstance(required, str):
                    required = required.lower() == "true"

                hidden = constraints.get("hidden", "false")
                if isinstance(hidden, str):
                    hidden = hidden.lower() == "true"

                result[param_name] = {
                    "type": param_def.get("type", "string"),
                    "display_name": ui_def.get("displayName", param_name),
                    "description": ui_def.get("description", ""),
                    "required": required,
                    "hidden": hidden,
                }

            return result

    return {}


def get_required_user_parameters(connector: dict, auth_type_name: str) -> Dict[str, Dict[str, Any]]:
    """
    Get only the user-facing required parameters for an auth type.

    These are parameters where required=true AND hidden=false.

    Args:
        connector: The connector definition from the API
        auth_type_name: The name of the auth type

    Returns:
        Dict mapping parameter names to their definitions (filtered to required, non-hidden)
    """
    all_params = get_auth_type_parameters(connector, auth_type_name)
    return {
        name: definition
        for name, definition in all_params.items()
        if definition.get("required") and not definition.get("hidden")
    }


def _create_oauth_connection(
    client,
    connector_id: str,
    name: str,
    environment: str,
    is_custom: bool = False,
    client_id: str = "",
    client_secret: str = "",
) -> None:
    """
    Helper to create an OAuth connection with browser-based auth flow.

    For custom connectors, updates the connector's OAuth credentials first
    (client_id/client_secret are required for the token exchange).

    Args:
        client: The Copilot client instance
        connector_id: Connector ID
        name: Connection display name
        environment: Environment ID
        is_custom: Whether this is a custom connector (not Microsoft-managed)
        client_id: OAuth client ID (required for custom connectors)
        client_secret: OAuth client secret (required for custom connectors)
    """
    import time

    # Custom connectors: update OAuth credentials on the connector before creating connection
    if is_custom and client_id and client_secret:
        typer.echo("Updating connector OAuth credentials...")
        client.update_custom_connector(
            connector_id=connector_id,
            oauth_client_id=client_id,
            oauth_client_secret=client_secret,
            environment_id=environment,
        )
        typer.echo("OAuth credentials set on connector.")

    # Show OAuth redirect URL configuration requirement for custom connectors
    # Managed connectors have redirect URLs pre-configured by Microsoft
    if is_custom:
        redirect_connector_id = connector_id.replace("shared_", "", 1) if connector_id.startswith("shared_") else connector_id
        typer.echo()
        typer.echo("OAuth Redirect URL Configuration Required")
        typer.echo()
        typer.echo("Power Platform will use this redirect URL for OAuth:")
        typer.echo()
        typer.echo(f"  https://global.consent.azure-apim.net/redirect/{redirect_connector_id}")
        typer.echo()
        typer.echo("You must register this EXACT URL in your OAuth app settings.")
        typer.echo()

        if not typer.confirm("Have you registered the redirect URL?", default=False):
            typer.echo()
            typer.echo("Connection creation cancelled.")
            typer.echo("Register the redirect URL in your OAuth app and try again.")
            raise typer.Exit(0)

    typer.echo()

    # OAuth flow - create connection and get consent link
    result = client.create_oauth_connection(
        connector_id=connector_id,
        connection_name=name,
        environment_id=environment,
    )

    connection_id = result.get("name", "")

    print_success(f"Connection '{name}' created.")
    typer.echo(f"Connection ID: {connection_id}")
    typer.echo(f"Connector: {connector_id}")
    typer.echo("")

    # Get the consent link and open browser
    typer.echo("Getting OAuth consent link...")
    consent_link = client.get_consent_link(connector_id, connection_id, environment)

    if not consent_link:
        typer.echo("Error: Could not get consent link from API.", err=True)
        typer.echo(f"Complete authentication manually at:")
        typer.echo(f"  https://make.powerapps.com/environments/{environment}/connections")
        raise typer.Exit(1)

    typer.echo(f"Consent URL: {consent_link}")
    typer.echo("")
    typer.echo("Opening browser for OAuth authentication...")
    _open_url_wsl_aware(consent_link)

    # Poll for connection status
    typer.echo("")
    typer.echo("Waiting for authentication to complete...")
    typer.echo("(Complete the OAuth flow in your browser, then return here)")
    typer.echo("")

    max_attempts = 60  # 5 minutes at 5-second intervals
    poll_interval = 5

    for attempt in range(max_attempts):
        time.sleep(poll_interval)

        try:
            conn = client.get_connection(connection_id, environment)
            statuses = conn.get("properties", {}).get("statuses", [])
            if statuses:
                status = statuses[0].get("status", "Unknown")
                if status.lower() == "connected":
                    typer.echo("")
                    print_success(f"Authentication complete! Connection '{name}' is now connected.")
                    return

            # Show progress
            elapsed = (attempt + 1) * poll_interval
            typer.echo(f"  Still waiting... ({elapsed}s elapsed)", nl=False)
            typer.echo("\r", nl=False)

        except Exception:
            # Ignore polling errors, keep trying
            pass

    typer.echo("")
    typer.echo("Timed out waiting for authentication.")
    typer.echo(f"Check connection status: copilot connections list -c {connector_id} --table")


def format_connection_for_display(connection: dict, connector_id: str = "", truncate: bool = False) -> dict:
    """Format a connection for display.

    Args:
        connection: The connection dict from the API
        connector_id: Optional connector ID to include
        truncate: If True, truncate long values for table display
    """
    props = connection.get("properties", {})
    statuses = props.get("statuses", [])

    # Extract status info
    status_str = "Unknown"
    error_msg = ""
    if statuses:
        first_status = statuses[0] if isinstance(statuses, list) else statuses
        status_str = first_status.get("status", "Unknown")
        if first_status.get("error"):
            err = first_status["error"]
            if isinstance(err, dict):
                error_msg = err.get("message", "")
                if truncate and len(error_msg) > 50:
                    error_msg = error_msg[:50]
            else:
                error_msg = str(err)
                if truncate and len(error_msg) > 50:
                    error_msg = error_msg[:50]

    display_name = props.get("displayName") or connection.get("name", "")
    if truncate and len(display_name) > 40:
        display_name = display_name[:37] + "..."

    created = props.get("createdTime", "")
    if truncate and created:
        created = created[:10]

    # Extract connector name from apiId if connector_id not provided
    # apiId format: /providers/Microsoft.PowerApps/apis/shared_asana
    if not connector_id:
        api_id = props.get("apiId", "")
        if api_id:
            parts = api_id.split("/")
            connector_id = parts[-1] if parts else ""

    # Extract auth type from connectionParametersSet (for multi-auth connectors)
    # If not present, it's using the default auth (typically OAuth for personal connections)
    auth_type = "OAuth"  # Default for single-auth OAuth connectors
    conn_param_set = props.get("connectionParametersSet", {})
    if conn_param_set:
        auth_type = conn_param_set.get("name", "OAuth")

    return {
        "name": display_name,
        "id": connection.get("name", ""),
        "connector": connector_id,
        "auth_type": auth_type,
        "status": status_str,
        "created": created,
        "error": error_msg,
    }


@app.command("get")
def connections_get(
    connection_id: str = typer.Argument(
        ...,
        help="The connection's unique identifier (GUID)",
    ),
    environment: Optional[str] = typer.Option(
        None,
        "--environment",
        "--env",
        help="Power Platform environment ID. Uses DATAVERSE_ENVIRONMENT_ID if not specified.",
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
):
    """
    Get details for a specific connection by ID.

    Returns the full connection object including connector ID, display name,
    authentication status, and creation time.

    Examples:
        copilot connections get 12345678-1234-1234-1234-123456789abc
        copilot connections get abc123 --env Default-xxx
        copilot connections get abc123 --table
    """
    try:
        client = get_client()

        # Get environment ID from config if not provided
        if not environment:
            config = get_config()
            environment = config.environment_id

        connection = client.get_connection(connection_id, environment)

        use_table = table or output == "table"
        if use_table:
            formatted = format_connection_for_display(connection, truncate=True)
            print_table(
                [formatted],
                columns=["name", "connector", "auth_type", "id", "status", "created"],
                headers=["Name", "Connector", "Auth Type", "Connection ID", "Status", "Created"],
            )
        else:
            formatted = format_connection_for_display(connection)
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("list")
def connections_list(
    connector_id: Optional[str] = typer.Option(
        None,
        "--connector-id",
        "-c",
        help="Filter to a specific connector (e.g., shared_asana, shared_office365). If not provided, lists all connections.",
    ),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%connection%)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of connections to return",
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
    List connections in the environment.

    Connections are authenticated credentials that allow Power Platform
    to access external services on your behalf. Each connection stores
    OAuth tokens, API keys, or other authentication details.

    By default, lists all connections in the environment. Use --connector-id
    to filter to a specific connector.

    Examples:
        copilot connections list --table
        copilot connections list --connector-id shared_asana --table
        copilot connections list -c shared_office365 --table
        copilot connections list --filter "name:ilike:%connection%"
        copilot connections list --limit 50
        copilot connections list --properties "name,id,status"
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

    try:
        client = get_client()
        connections = client.list_connections(connector_id)

        if not connections:
            if connector_id:
                typer.echo(f"No connections found for connector '{connector_id}'.")
                typer.echo("\nThis could mean:")
                typer.echo("  - No connections have been created for this connector")
                typer.echo("  - The connector ID might be incorrect")
                typer.echo("\nUse 'copilot managed-connector list --table' or 'copilot custom-connector list --table' to see available connectors.")
            else:
                typer.echo("No connections found in the environment.")
            return

        use_table = table or output == "table"
        formatted = [format_connection_for_display(c, connector_id or "", truncate=use_table) for c in connections]

        # Apply filters using standard field:op:value syntax
        if filter:
            try:
                validate_filters(filter)
                formatted = apply_filters(formatted, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit
        formatted = formatted[:limit]

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
                    columns=["name", "connector", "auth_type", "id", "status", "created"],
                    headers=["Name", "Connector", "Auth Type", "Connection ID", "Status", "Created"],
                )
        else:
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def _extract_connector_id_from_api_id(api_id: str) -> str:
    """Extract the connector ID from a full apiId path.

    Example: '/providers/Microsoft.PowerApps/apis/shared_office365' -> 'shared_office365'
    """
    return api_id.rsplit("/", 1)[-1] if api_id else ""


def _get_stored_status(props: dict) -> tuple:
    """Extract stored status and error from connection properties.

    Returns:
        (status_str, error_str)
    """
    statuses = props.get("statuses", [])
    if not statuses:
        return "Unknown", ""
    first_status = statuses[0] if isinstance(statuses, list) else statuses
    status = first_status.get("status", "Unknown")
    error = ""
    if first_status.get("error"):
        err = first_status["error"]
        if isinstance(err, dict):
            error = err.get("message", str(err))
        else:
            error = str(err)
    return status, error


@app.command("test")
def connections_test(
    connector_id: Optional[str] = typer.Option(
        None,
        "--connector-id",
        "-c",
        help="The connector's unique identifier (e.g., shared_asana, shared_office365)",
    ),
    connection_id: Optional[str] = typer.Option(
        None,
        "--connection-id",
        help="Test a specific connection ID. If not provided, tests all connections for the connector.",
    ),
    all_connectors: bool = typer.Option(
        False,
        "--all",
        help="Test all connections across all connectors (no --connector-id required).",
    ),
    live: bool = typer.Option(
        True,
        "--live/--no-live",
        help="Use live probe (testConnection API) instead of stored status. Default: --live.",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    Test authentication for connector connections.

    By default, performs a live probe against the Power Platform testConnection
    API to verify that credentials are actually valid (not just stored as
    "Connected"). Use --no-live to fall back to reading stored status only.

    Use --all to test every connection in the environment at once.

    Connection statuses:
      - Connected: Connection is authenticated and ready to use
      - Error: Connection has an authentication or configuration issue
      - Unauthenticated: Connection needs to be authenticated

    Examples:
        copilot connections test -c shared_office365
        copilot connections test -c shared_office365 --no-live
        copilot connections test --all --table
        copilot connections test -c shared_asana --connection-id abc123
    """
    if not connector_id and not all_connectors:
        typer.echo("Error: Either --connector-id/-c or --all is required.")
        raise typer.Exit(1)

    try:
        client = get_client()

        if all_connectors:
            typer.echo("Finding all connections in the environment...")
            connections = client.list_connections()
        else:
            typer.echo(f"Finding connections for connector: {connector_id}...")
            connections = client.list_connections(connector_id)

        if not connections:
            if all_connectors:
                typer.echo("No connections found in the environment.")
            else:
                typer.echo(f"No connections found for connector '{connector_id}'.")
                typer.echo("\nThis could mean:")
                typer.echo("  - No connections have been created for this connector")
                typer.echo("  - The connector ID might be incorrect")
                typer.echo("\nUse 'copilot managed-connector list --table' or 'copilot custom-connector list --table' to see available connectors.")
            return

        # If specific connection requested, filter to that one
        if connection_id:
            connections = [c for c in connections if c.get("name") == connection_id]
            if not connections:
                typer.echo(f"Connection '{connection_id}' not found for connector '{connector_id}'.")
                raise typer.Exit(1)

        mode_label = "live probe" if live else "stored status"
        typer.echo(f"Found {len(connections)} connection(s). Checking via {mode_label}...\n")

        results = []
        for conn in connections:
            conn_id = conn.get("name", "")
            props = conn.get("properties", {})
            display_name = props.get("displayName") or conn_id
            conn_connector_id = connector_id or _extract_connector_id_from_api_id(
                props.get("apiId", "")
            )

            # Get stored status (always populated for reference)
            current_status, status_error = _get_stored_status(props)

            # Determine health
            test_result = None
            if live:
                try:
                    test_result = client.test_connection(conn_connector_id, conn_id)
                    is_healthy = test_result.get("success", False)
                    if is_healthy:
                        auth_result = "OK"
                    else:
                        auth_result = f"FAILED ({test_result.get('stored_status', 'Unknown')})"
                        if not status_error and test_result.get("error"):
                            status_error = test_result["error"]
                except Exception as exc:
                    is_healthy = False
                    auth_result = f"PROBE ERROR: {exc}"
                    test_result = {"success": False, "error": str(exc)}
            else:
                is_healthy = current_status.lower() == "connected"
                auth_result = "OK" if is_healthy else current_status

            result = {
                "connection_id": conn_id,
                "display_name": display_name,
                "connector_id": conn_connector_id,
                "stored_status": current_status,
                "auth_result": auth_result,
                "healthy": is_healthy,
                "error": status_error,
            }
            if test_result is not None:
                result["test_result"] = test_result

            results.append(result)

            # Print progress
            status_icon = "+" if is_healthy else "x"
            display_name_short = display_name[:50] if len(display_name) > 50 else display_name
            typer.echo(f"  {status_icon} {display_name_short} ({auth_result})")

        typer.echo("")

        # Summary
        healthy_count = sum(1 for r in results if r["healthy"])
        unhealthy_count = len(results) - healthy_count

        if table:
            print_table(
                results,
                columns=["display_name", "connector_id", "stored_status", "auth_result", "error"],
                headers=["Connection Name", "Connector", "Stored Status", "Auth Check", "Error"],
            )
        else:
            print_json(results)

        if unhealthy_count > 0:
            typer.echo(
                f"\nSummary: {healthy_count} healthy, {unhealthy_count} unhealthy "
                f"out of {len(results)} connection(s)"
            )
            raise typer.Exit(1)
        else:
            typer.echo(f"\nSummary: All {len(results)} connection(s) are healthy")

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
def connections_create(
    connector_id: str = typer.Option(
        ...,
        "--connector-id",
        "-c",
        help="The connector's unique identifier (e.g., shared_asana, shared_commondataserviceforapps)",
    ),
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Display name for the connection",
    ),
    auth_type: Optional[str] = typer.Option(
        None,
        "--auth-type",
        "-a",
        help="Authentication type (required if connector supports multiple). Use 'copilot managed-connector get <id>' to see available types.",
    ),
    client_id: Optional[str] = typer.Option(
        None,
        "--client-id",
        help="Azure AD application (client) ID. Required for custom OAuth connectors and ServicePrincipalOauth.",
    ),
    client_secret: Optional[str] = typer.Option(
        None,
        "--client-secret",
        help="Azure AD application client secret. Required for custom OAuth connectors and ServicePrincipalOauth.",
    ),
    tenant_id: Optional[str] = typer.Option(
        None,
        "--tenant-id",
        help="Azure AD tenant ID for ServicePrincipalOauth auth type.",
    ),
    parameters: Optional[str] = typer.Option(
        None,
        "--parameters",
        "-p",
        help="JSON string of connection parameters. Required parameters depend on the auth type.",
    ),
    environment: Optional[str] = typer.Option(
        None,
        "--environment",
        "--env",
        help="Power Platform environment ID. Uses DATAVERSE_ENVIRONMENT_ID if not specified.",
    ),
):
    """
    Create a new connection for a connector.

    Connections authenticate access to external services. The authentication type
    and required parameters depend on the connector.

    Multi-Auth Connectors (--auth-type required):
      Some connectors like Dataverse support multiple auth types. Use --auth-type
      to specify which one:
        - Oauth: Interactive browser-based login
        - ServicePrincipalOauth: Service principal with client ID/secret
        - CertOauth: Certificate-based authentication

      To see available auth types for a connector:
        copilot managed-connector get <connector-id>

    Single-Auth Connectors:
      Connectors with only one auth type don't require --auth-type.
      OAuth connectors will automatically initiate browser-based auth.

    Custom OAuth Connectors:
      Custom connectors using OAuth require --client-id and --client-secret.
      These are the Azure AD app registration credentials the connector uses
      for the OAuth token exchange.

    Examples:
        # Dataverse with service principal (using dedicated flags)
        copilot connections create -c shared_commondataserviceforapps -n "Dataverse SP" \\
            --auth-type ServicePrincipalOauth \\
            --client-id "xxx" --client-secret "yyy" --tenant-id "zzz"

        # Dataverse with interactive OAuth
        copilot connections create -c shared_commondataserviceforapps -n "Dataverse OAuth" \\
            --auth-type Oauth

        # Single-auth OAuth connector (Asana — managed, no credentials needed)
        copilot connections create -c shared_asana -n "My Asana"

        # Custom OAuth connector (requires credentials)
        copilot connections create -c shared_mycustomconnector-xxx -n "My Custom Connector" \\
            --client-id "5e418d02-..." --client-secret "your-secret"

        # Azure AI Search (API key)
        copilot connections create -c shared_azureaisearch -n "My Search" \\
            --parameters '{"endpoint": "https://mysearch.search.windows.net", "api_key": "xxx"}'
    """
    import json

    try:
        client = get_client()

        # Get environment ID from config if not provided
        if not environment:
            config = get_config()
            environment = config.environment_id
            if not environment:
                typer.echo(
                    "Error: Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file or use --environment.",
                    err=True
                )
                raise typer.Exit(1)

        # Fetch connector to check auth types
        typer.echo(f"Fetching connector definition for {connector_id}...")
        try:
            connector = client.get_connector(connector_id, environment)
        except ClientError as e:
            typer.echo(f"Error: Could not fetch connector: {e}", err=True)
            raise typer.Exit(1)

        # Detect custom vs managed connector
        is_custom = is_custom_connector(connector)

        # Check available auth types
        available_auth_types = extract_connector_auth_types(connector)

        # If multiple auth types, require --auth-type
        if len(available_auth_types) > 1:
            if not auth_type:
                typer.echo(f"\nError: Connector '{connector_id}' supports multiple authentication types.", err=True)
                typer.echo("\nAvailable auth types:", err=True)
                for at in available_auth_types:
                    oauth_indicator = " (OAuth)" if at["is_oauth"] else ""
                    typer.echo(f"  - {at['name']}: {at['display_name']}{oauth_indicator}", err=True)
                typer.echo("\nUse --auth-type to specify which authentication method to use.", err=True)
                typer.echo(f"Example: copilot connections create -c {connector_id} -n \"{name}\" --auth-type {available_auth_types[0]['name']}", err=True)
                raise typer.Exit(1)

            # Validate provided auth type
            auth_type_names = [at["name"].lower() for at in available_auth_types]
            if auth_type.lower() not in auth_type_names:
                typer.echo(f"\nError: Invalid auth type '{auth_type}'.", err=True)
                typer.echo("\nAvailable auth types:", err=True)
                for at in available_auth_types:
                    oauth_indicator = " (OAuth)" if at["is_oauth"] else ""
                    typer.echo(f"  - {at['name']}: {at['display_name']}{oauth_indicator}", err=True)
                raise typer.Exit(1)

            # Find the exact auth type (case-insensitive match)
            selected_auth_type = next(
                at for at in available_auth_types
                if at["name"].lower() == auth_type.lower()
            )

            typer.echo(f"Using auth type: {selected_auth_type['name']} ({selected_auth_type['display_name']})")

            # Get required parameters for this auth type
            required_params = get_required_user_parameters(connector, selected_auth_type["name"])

            # Parse user-provided parameters
            params_dict = {}
            if parameters:
                try:
                    params_dict = json.loads(parameters)
                except json.JSONDecodeError as e:
                    typer.echo(f"Error: Invalid JSON in --parameters: {e}", err=True)
                    raise typer.Exit(1)

            # For ServicePrincipalOauth, use dedicated flags if provided
            if selected_auth_type["name"].lower() == "serviceprincipaloauth":
                if client_id and client_secret and tenant_id:
                    params_dict = {
                        "token:clientId": client_id,
                        "token:clientSecret": client_secret,
                        "token:TenantId": tenant_id,
                    }
                elif client_id or client_secret or tenant_id:
                    # Some but not all provided
                    missing = []
                    if not client_id:
                        missing.append("--client-id")
                    if not client_secret:
                        missing.append("--client-secret")
                    if not tenant_id:
                        missing.append("--tenant-id")
                    typer.echo(f"Error: ServicePrincipalOauth requires all three flags: {', '.join(missing)} missing.", err=True)
                    raise typer.Exit(1)

            # If OAuth-based auth type and no params provided at all, use browser OAuth flow
            # Skip this for ServicePrincipalOauth - it never uses browser flow
            if selected_auth_type["is_oauth"] and not required_params and not params_dict:
                # Custom connectors require OAuth credentials for token exchange
                if is_custom:
                    missing = []
                    if not client_id:
                        missing.append("--client-id")
                    if not client_secret:
                        missing.append("--client-secret")
                    if missing:
                        typer.echo(
                            f"Error: {', '.join(missing)} required for OAuth connections on custom connectors.\n"
                            "These are the Azure AD app registration credentials needed for the OAuth token exchange.\n"
                            "Get them from the app registration used by this connector.",
                            err=True,
                        )
                        raise typer.Exit(1)

                _create_oauth_connection(
                    client, connector_id, name, environment,
                    is_custom=is_custom, client_id=client_id or "", client_secret=client_secret or "",
                )
                return

            # If OAuth-based but has required params (like ServicePrincipalOauth), validate them
            if required_params:
                missing_params = []
                for param_name, param_def in required_params.items():
                    if param_name not in params_dict:
                        missing_params.append(f"  - {param_name}: {param_def['display_name']} ({param_def['description']})")

                if missing_params:
                    typer.echo(f"\nError: Missing required parameters for auth type '{selected_auth_type['name']}'.", err=True)
                    typer.echo("\nRequired parameters:", err=True)
                    for mp in missing_params:
                        typer.echo(mp, err=True)
                    typer.echo("\nProvide them via --parameters as JSON:", err=True)
                    example_params = {p: "<value>" for p in required_params.keys()}
                    typer.echo(f"  --parameters '{json.dumps(example_params)}'", err=True)
                    raise typer.Exit(1)

            # Create connection with the specified auth type and parameters
            # The API expects connectionParameterSet to specify the auth type
            result = client.create_connection_with_auth_type(
                connector_id=connector_id,
                connection_name=name,
                environment_id=environment,
                auth_type_name=selected_auth_type["name"],
                parameters=params_dict,
            )

            connection_id = result.get("name", "")
            props = result.get("properties", {})
            display_name = props.get("displayName", name)
            statuses = props.get("statuses", [])
            status = statuses[0].get("status", "Unknown") if statuses else "Unknown"

            print_success(f"Connection '{display_name}' created.")
            typer.echo(f"Connection ID: {connection_id}")
            typer.echo(f"Connector: {connector_id}")
            typer.echo(f"Auth Type: {selected_auth_type['name']}")
            typer.echo(f"Status: {status}")

            if status == "Unauthenticated" and selected_auth_type["is_oauth"]:
                typer.echo("")
                typer.echo("Note: Connection requires OAuth consent.")
                typer.echo("Complete setup in Power Platform:")
                typer.echo(f"  https://make.powerapps.com/environments/{environment}/connections")

            return

        # Single auth type or no connectionParameterSets - use existing logic
        # Parse parameters if provided
        params_dict = {}
        if parameters:
            try:
                params_dict = json.loads(parameters)
            except json.JSONDecodeError as e:
                typer.echo(f"Error: Invalid JSON in --parameters: {e}", err=True)
                raise typer.Exit(1)

        # Check if this is an OAuth connector (single auth type)
        is_oauth_connector = False
        if available_auth_types and len(available_auth_types) == 1:
            is_oauth_connector = available_auth_types[0]["is_oauth"]
        else:
            # Check connectionParameters for single-auth OAuth detection
            props = connector.get("properties", {})
            conn_params = props.get("connectionParameters", {})
            token_def = conn_params.get("token") or conn_params.get("Token", {})
            if isinstance(token_def, dict) and token_def.get("type") == "oauthSetting":
                is_oauth_connector = True

        if is_oauth_connector and not params_dict:
            # Custom connectors require OAuth credentials for token exchange
            if is_custom:
                missing = []
                if not client_id:
                    missing.append("--client-id")
                if not client_secret:
                    missing.append("--client-secret")
                if missing:
                    typer.echo(
                        f"Error: {', '.join(missing)} required for OAuth connections on custom connectors.\n"
                        "These are the Azure AD app registration credentials needed for the OAuth token exchange.\n"
                        "Get them from the app registration used by this connector.",
                        err=True,
                    )
                    raise typer.Exit(1)

            _create_oauth_connection(
                client, connector_id, name, environment,
                is_custom=is_custom, client_id=client_id or "", client_secret=client_secret or "",
            )
            return

        if connector_id == "shared_azureaisearch":
            # Azure AI Search has specific parameters
            endpoint = params_dict.get("endpoint") or params_dict.get("ConnectionEndpoint")
            api_key = params_dict.get("api_key") or params_dict.get("AdminKey")

            if not endpoint or not api_key:
                typer.echo(
                    "Error: Azure AI Search requires 'endpoint' and 'api_key' in --parameters",
                    err=True
                )
                typer.echo('Example: --parameters \'{"endpoint": "https://mysearch.search.windows.net", "api_key": "xxx"}\'')
                raise typer.Exit(1)

            result = client.create_azure_ai_search_connection(
                connection_name=name,
                search_endpoint=endpoint,
                api_key=api_key,
                environment_id=environment,
            )

            connection_id = result.get("name", "")
            display_name = result.get("properties", {}).get("displayName", name)
            statuses = result.get("properties", {}).get("statuses", [])
            status = statuses[0].get("status", "Unknown") if statuses else "Unknown"

            print_success(f"Connection '{display_name}' created successfully.")
            typer.echo(f"Connection ID: {connection_id}")
            typer.echo(f"Status: {status}")

        else:
            # Generic connection creation with parameters
            result = client.create_connection(
                connector_id=connector_id,
                connection_name=name,
                environment_id=environment,
                parameters=params_dict,
            )

            connection_id = result.get("name", "")
            props = result.get("properties", {})
            display_name = props.get("displayName", name)
            statuses = props.get("statuses", [])
            status = statuses[0].get("status", "Unknown") if statuses else "Unknown"

            print_success(f"Connection '{display_name}' created.")
            typer.echo(f"Connection ID: {connection_id}")
            typer.echo(f"Connector: {connector_id}")
            typer.echo(f"Status: {status}")

            if status == "Unauthenticated":
                typer.echo("")
                typer.echo("Note: Connection requires authentication.")
                typer.echo("Complete setup in Power Platform:")
                typer.echo(f"  https://make.powerapps.com/environments/{environment}/connections")

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("delete")
@app.command("remove")
def connections_delete(
    connection_id: str = typer.Argument(
        ...,
        help="The connection's unique identifier (GUID)",
    ),
    connector_id: str = typer.Option(
        ...,
        "--connector-id",
        "-c",
        help="The connector's unique identifier (e.g., shared_asana, shared_office365)",
    ),
    environment: Optional[str] = typer.Option(
        None,
        "--environment",
        "--env",
        help="Power Platform environment ID. Uses DATAVERSE_ENVIRONMENT_ID if not specified.",
    ),
    cascade: Optional[bool] = typer.Option(
        None,
        "--cascade/--no-cascade",
        help="--cascade deletes dependent resources. --no-cascade leaves orphans. Default: error if dependents exist.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Delete a connector connection.

    Permanently removes a connection from the Power Platform environment.
    This may break flows or agents that depend on this connection.

    By default, checks for dependent resources (connection references, agent
    connector tools) and refuses to delete if any exist. Use --cascade to also
    delete dependents, or --no-cascade to delete the connection and leave
    orphaned resources.

    Examples:
        copilot connections delete <guid> -c shared_asana
        copilot connections delete <guid> -c shared_office365 --force
        copilot connections delete <guid> -c shared_azureaisearch --env Default-xxx
        copilot connections delete <guid> -c shared_asana --cascade
        copilot connections delete <guid> -c shared_asana --no-cascade
    """
    try:
        client = get_client()

        # Get environment ID from config if not provided
        if not environment:
            config = get_config()
            environment = config.environment_id
            if not environment:
                typer.echo(
                    "Error: Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file or use --environment.",
                    err=True
                )
                raise typer.Exit(1)

        # Try to get connection details first
        try:
            connections = client.list_connections(connector_id, environment)
            conn = next((c for c in connections if c.get("name") == connection_id), None)
            if conn:
                display_name = conn.get("properties", {}).get("displayName", connection_id)
                typer.echo(f"Connection: {display_name}")
                typer.echo(f"ID: {connection_id}")
                typer.echo(f"Connector: {connector_id}")
        except Exception:
            pass

        # Always check for connection references
        typer.echo("\nChecking for connection references...")
        connection_refs_found = client.list_connection_references(connection_id=connection_id)
        if connection_refs_found:
            typer.echo(f"Found {len(connection_refs_found)} connection reference(s) pointing to this connection:")
            for ref in connection_refs_found:
                ref_name = ref.get("connectionreferencedisplayname", "Unnamed")
                ref_id = ref.get("connectionreferenceid", "")
                typer.echo(f"  - {ref_name} ({ref_id})")
        else:
            typer.echo("No connection references found for this connection.")

        # Check for agents using this connection for authentication
        typer.echo("\nChecking for agents using this connection for authentication...")
        agents_with_auth = []
        try:
            all_agents = client.list_bots()
            for agent in all_agents:
                auth_config = agent.get("authenticationconfiguration")
                if auth_config:
                    import json
                    try:
                        auth_data = json.loads(auth_config) if isinstance(auth_config, str) else auth_config
                        conn_name = auth_data.get("connectionName")
                        if conn_name == connection_id:
                            agent_name = agent.get("name", "Unnamed")
                            agent_id = agent.get("botid", "")
                            agents_with_auth.append({
                                "name": agent_name,
                                "id": agent_id
                            })
                    except (json.JSONDecodeError, AttributeError):
                        pass

            if agents_with_auth:
                typer.echo(f"Found {len(agents_with_auth)} agent(s) using this connection for authentication:")
                for agent in agents_with_auth:
                    typer.echo(f"  - {agent['name']} ({agent['id']})")
                typer.echo("\nWARNING: Deleting this connection will break authentication for these agents!")
                typer.echo("They will fail with error: 'SignInTopicNeededButNotFound'")
            else:
                typer.echo("No agents found using this connection for authentication.")
        except Exception as e:
            typer.echo(f"Warning: Could not check for agent authentication dependencies: {e}", err=True)

        # Always check for agent connector tools
        typer.echo("\nChecking for agent connector tools...")
        tools_found = client.list_tools(connection_id=connection_id)
        if tools_found:
            typer.echo(f"Found {len(tools_found)} agent connector tool(s) using this connection:")
            for tool in tools_found:
                tool_name = tool.get("name", "Unnamed")
                tool_id = tool.get("botcomponentid", "")
                bot_id = tool.get("_parentbotid_value", "")
                typer.echo(f"  - {tool_name} ({tool_id}) in agent {bot_id}")
        else:
            typer.echo("No agent connector tools found using this connection.")

        # Determine if dependent resources exist
        has_dependents = bool(connection_refs_found or tools_found)

        # Default (cascade=None): error if dependents exist
        if cascade is None and has_dependents:
            dep_parts = []
            if connection_refs_found:
                dep_parts.append(f"{len(connection_refs_found)} connection reference(s)")
            if tools_found:
                dep_parts.append(f"{len(tools_found)} agent connector tool(s)")
            dep_summary = " and ".join(dep_parts)
            typer.echo(
                f"\nError: Cannot delete connection - {dep_summary} depend on it.\n"
                f"\nOptions:\n"
                f"  --cascade      Delete the connection AND all dependent resources (recommended)\n"
                f"  --no-cascade   Delete only the connection, leaving orphaned resources\n"
                f"\nExample:\n"
                f"  copilot connections remove {connection_id} -c {connector_id} --cascade",
                err=True,
            )
            raise typer.Exit(1)

        if not force:
            typer.echo("\nWARNING: This may break flows or agents using this connection.")
            if agents_with_auth:
                typer.echo(f"WARNING: {len(agents_with_auth)} agent(s) use this connection for authentication and will fail!")
            if cascade is True and connection_refs_found:
                typer.echo(f"WARNING: This will also delete {len(connection_refs_found)} connection reference(s).")
            if cascade is True and tools_found:
                typer.echo(f"WARNING: This will also delete {len(tools_found)} agent connector tool(s).")
            if cascade is False and has_dependents:
                typer.echo("WARNING: Dependent resources will be left orphaned (--no-cascade).")
            confirm = typer.confirm("Are you sure you want to delete this connection?")
            if not confirm:
                typer.echo("Cancelled.")
                raise typer.Exit(0)

        # Delete dependent resources only when --cascade is explicitly set
        if cascade is True:
            # Delete agent tools first (before connection references, as tools depend on them)
            if tools_found:
                typer.echo(f"\nDeleting {len(tools_found)} agent connector tool(s)...")
                for tool in tools_found:
                    tool_id = tool.get("botcomponentid")
                    tool_name = tool.get("name", "Unnamed")
                    try:
                        client.remove_tool(tool_id)
                        typer.echo(f"  {safe_symbol('check')} Deleted agent tool: {tool_name}")
                    except Exception as e:
                        typer.echo(f"  {safe_symbol('cross')} Failed to delete agent tool {tool_name}: {e}", err=True)

            # Delete connection references
            if connection_refs_found:
                typer.echo(f"\nDeleting {len(connection_refs_found)} connection reference(s)...")
                for ref in connection_refs_found:
                    ref_id = ref.get("connectionreferenceid")
                    ref_name = ref.get("connectionreferencedisplayname", "Unnamed")
                    try:
                        client.delete_connection_reference(ref_id)
                        typer.echo(f"  {safe_symbol('check')} Deleted connection reference: {ref_name}")
                    except Exception as e:
                        if "404" in str(e):
                            typer.echo(f"  {safe_symbol('check')} Connection reference already removed by Dataverse: {ref_name}")
                        else:
                            typer.echo(f"  {safe_symbol('cross')} Failed to delete connection reference {ref_name}: {e}", err=True)

        # Delete the connection
        client.delete_connection(connection_id, connector_id, environment)
        print_success(f"Connection {connection_id} deleted successfully.")

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def _open_url_wsl_aware(url: str) -> None:
    """Open URL in browser, handling WSL where webbrowser.open() fails."""
    import subprocess
    import platform
    import os
    import webbrowser

    if "microsoft" in platform.uname().release.lower() or os.path.exists(
        "/proc/sys/fs/binfmt_misc/WSLInterop"
    ):
        # WSL — try Windows-native browser openers
        try:
            subprocess.run(["wslview", url], check=True, capture_output=True)
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
        try:
            subprocess.run(
                ["powershell.exe", "-c", f"Start-Process '{url}'"],
                check=True,
                capture_output=True,
            )
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    webbrowser.open(url)


@app.command("auth")
def connections_auth(
    connection_id: str = typer.Argument(
        ...,
        help="The connection's unique identifier (GUID)",
    ),
    connector_id: Optional[str] = typer.Option(
        None,
        "--connector-id",
        "-c",
        help="The connector's unique identifier. If not provided, will be discovered from the connection.",
    ),
    environment: Optional[str] = typer.Option(
        None,
        "--environment",
        "--env",
        help="Power Platform environment ID. Uses DATAVERSE_ENVIRONMENT_ID if not specified.",
    ),
    dataverse_url: Optional[str] = typer.Option(
        None,
        "--dataverse-url",
        help="Dataverse environment URL (e.g., https://yourorg.crm.dynamics.com). Uses DATAVERSE_URL from .env if not specified.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompts and don't wait for OAuth authentication to complete.",
    ),
):
    """
    Re-authenticate an existing OAuth connection.

    This command initiates the OAuth consent flow for an existing connection
    that has expired or is in an error state. It opens a browser window for
    the user to complete authentication.

    The command will:
    1. Verify the connection exists and is an OAuth-based connection
    2. Open the OAuth consent page in your browser
    3. Wait for authentication to complete (unless --force is used)

    Examples:
        # Re-authenticate a connection (auto-discovers connector)
        copilot connections auth 12345678-1234-1234-1234-123456789abc

        # Re-authenticate with explicit connector ID
        copilot connections auth 12345678-1234-1234-1234-123456789abc \\
            -c shared_podio-20items-2c-20comments-20-26-20files-20api-acfe62f0142ebcd5

        # Re-authenticate with explicit Dataverse URL (no .env needed)
        copilot connections auth 12345678-1234-1234-1234-123456789abc \\
            --dataverse-url https://yourorg.crm.dynamics.com

        # Re-authenticate without waiting for completion
        copilot connections auth 12345678-1234-1234-1234-123456789abc --force
    """
    import webbrowser
    import time

    try:
        client = get_client(dataverse_url=dataverse_url)

        # Get environment ID from config if not provided
        if not environment:
            config = get_config()
            environment = config.environment_id
            if not environment:
                typer.echo(
                    "Error: Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file or use --environment.",
                    err=True
                )
                raise typer.Exit(1)

        # Get connection details
        typer.echo(f"Fetching connection {connection_id}...")
        try:
            connection = client.get_connection(connection_id, environment)
        except ClientError as e:
            typer.echo(f"Error: Could not find connection: {e}", err=True)
            raise typer.Exit(1)

        props = connection.get("properties", {})
        display_name = props.get("displayName", connection_id)
        api_id = props.get("apiId", "")

        # Extract connector_id from apiId if not provided
        # apiId format: /providers/Microsoft.PowerApps/apis/shared_asana
        if not connector_id:
            if api_id:
                parts = api_id.split("/")
                connector_id = parts[-1] if parts else ""
            if not connector_id:
                typer.echo(
                    "Error: Could not determine connector ID from connection. "
                    "Please provide --connector-id.",
                    err=True
                )
                raise typer.Exit(1)

        # Get current status
        statuses = props.get("statuses", [])
        current_status = "Unknown"
        if statuses:
            first_status = statuses[0] if isinstance(statuses, list) else statuses
            current_status = first_status.get("status", "Unknown")

        typer.echo(f"Connection: {display_name}")
        typer.echo(f"Connector: {connector_id}")
        typer.echo(f"Current Status: {current_status}")
        typer.echo("")

        # Fetch connector to check if it's OAuth-based
        typer.echo("Checking connector authentication type...")
        try:
            connector = client.get_connector(connector_id, environment)
        except ClientError as e:
            typer.echo(f"Error: Could not fetch connector definition: {e}", err=True)
            raise typer.Exit(1)

        # Check if this is an OAuth connector
        available_auth_types = extract_connector_auth_types(connector)
        is_oauth_connector = False

        if available_auth_types:
            # Multi-auth connector - check if any type is OAuth
            is_oauth_connector = any(at["is_oauth"] for at in available_auth_types)
        else:
            # Single-auth connector - check connectionParameters
            conn_props = connector.get("properties", {})
            conn_params = conn_props.get("connectionParameters", {})
            token_def = conn_params.get("token") or conn_params.get("Token", {})
            if isinstance(token_def, dict) and token_def.get("type") == "oauthSetting":
                is_oauth_connector = True

        if not is_oauth_connector:
            typer.echo("")
            typer.echo("Warning: This connector does not use OAuth authentication.", err=True)
            typer.echo("The 'auth' command only works with OAuth-based connectors.", err=True)
            typer.echo("")
            typer.echo("For non-OAuth connectors, you may need to:", err=True)
            typer.echo("  1. Delete the existing connection: copilot connections delete <id> -c <connector>", err=True)
            typer.echo("  2. Create a new connection with updated credentials", err=True)
            raise typer.Exit(1)

        typer.echo("Connector uses OAuth authentication.")

        # Check if OAuth client ID is configured
        conn_props = connector.get("properties", {})
        conn_params = conn_props.get("connectionParameters", {})
        token_def = conn_params.get("token") or conn_params.get("Token", {})
        oauth_settings = token_def.get("oAuthSettings", {}) if isinstance(token_def, dict) else {}
        oauth_client_id = oauth_settings.get("clientId", "")

        if not oauth_client_id:
            typer.echo("")
            typer.echo("Error: OAuth client ID is not configured for this connector.", err=True)
            typer.echo("")
            typer.echo("The connector's OAuth settings are missing the client ID, which means", err=True)
            typer.echo("authentication cannot proceed.", err=True)
            typer.echo("")
            typer.echo("To fix this, update the connector with OAuth credentials:", err=True)
            typer.echo("")
            typer.echo(f"  copilot custom-connector update {connector_id} \\", err=True)
            typer.echo("      --oauth-client-id YOUR_CLIENT_ID \\", err=True)
            typer.echo("      --oauth-client-secret YOUR_CLIENT_SECRET", err=True)
            typer.echo("")
            typer.echo("Then run this auth command again.", err=True)
            raise typer.Exit(1)

        typer.echo("")

        # Get the consent link for the existing connection
        typer.echo("Getting OAuth consent link...")
        try:
            consent_link = client.get_consent_link(connector_id, connection_id, environment)
        except ClientError as e:
            typer.echo(f"Error: Could not get consent link: {e}", err=True)
            typer.echo("")
            typer.echo("You can try completing authentication manually at:")
            typer.echo(f"  https://make.powerapps.com/environments/{environment}/connections")
            raise typer.Exit(1)

        if not consent_link:
            typer.echo("Error: Could not get consent link from API.", err=True)
            typer.echo(f"Complete authentication manually at:")
            typer.echo(f"  https://make.powerapps.com/environments/{environment}/connections")
            raise typer.Exit(1)

        typer.echo(f"Consent URL: {consent_link}")
        typer.echo("")
        typer.echo("Opening browser for OAuth authentication...")
        _open_url_wsl_aware(consent_link)

        if force:
            typer.echo("")
            typer.echo("Browser opened. Complete the OAuth flow to re-authenticate.")
            typer.echo(f"Check connection status: copilot connections test -c {connector_id} --table")
            return

        # Poll for connection status
        typer.echo("")
        typer.echo("Waiting for authentication to complete...")
        typer.echo("(Complete the OAuth flow in your browser, then return here)")
        typer.echo("")

        max_attempts = 60  # 5 minutes at 5-second intervals
        poll_interval = 5

        for attempt in range(max_attempts):
            time.sleep(poll_interval)

            try:
                conn = client.get_connection(connection_id, environment)
                statuses = conn.get("properties", {}).get("statuses", [])
                if statuses:
                    status = statuses[0].get("status", "Unknown")
                    if status.lower() == "connected":
                        typer.echo("")
                        print_success(f"Authentication complete! Connection '{display_name}' is now connected.")
                        return
                    elif status.lower() == "error":
                        error_obj = statuses[0].get("error", {})
                        error_msg = error_obj.get("message", "") if isinstance(error_obj, dict) else str(error_obj)
                        if error_msg:
                            typer.echo("")
                            typer.echo(f"  Connection status: Error - {error_msg}", err=True)

                # Show progress
                elapsed = (attempt + 1) * poll_interval
                typer.echo(f"  Still waiting... ({elapsed}s elapsed)", nl=False)
                typer.echo("\r", nl=False)

            except typer.Exit:
                raise
            except Exception as e:
                elapsed = (attempt + 1) * poll_interval
                typer.echo(f"  Poll error at {elapsed}s: {e}", err=True)

        typer.echo("")
        typer.echo("Timed out waiting for authentication.")
        typer.echo(f"Check connection status: copilot connections test -c {connector_id} --table")

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("bind")
def connections_bind(
    bot_id: str = typer.Argument(
        ...,
        help="The bot (agent) ID to bind the connection to (GUID)",
    ),
    connector_id: str = typer.Option(
        ...,
        "--connector-id",
        "-c",
        help="The connector's unique identifier (e.g., shared_asana, shared_asana-20tasks-5fd251d00e-...)",
    ),
    connection_id: str = typer.Option(
        ...,
        "--connection-id",
        help="The connection's unique identifier (GUID)",
    ),
    environment: Optional[str] = typer.Option(
        None,
        "--environment",
        "--env",
        help="Power Platform environment ID. Uses DATAVERSE_ENVIRONMENT_ID if not specified.",
    ),
):
    """
    Bind a connection to a Copilot Studio agent.

    This command associates a connection with a bot, enabling the bot to use
    the connection's credentials when executing connector tools. This is the
    same operation performed by clicking "Connect" in the Copilot Studio UI.

    The binding is stored at the bot level and allows the agent's connector
    tools to authenticate with the external service.

    IMPORTANT - API Permissions:
        This command uses the Power Platform user-connections API, which requires
        elevated permissions not available through standard Azure CLI authentication.
        If you receive a 403 "not authorized" error, you may need to:

        1. Use an Azure App Registration with the "Power Platform API" permissions:
           - CopilotStudio.Copilots.Invoke (delegated permission)
           - Or use interactive browser authentication via Copilot Studio UI

        2. Alternatively, bind connections through the Copilot Studio web interface:
           Settings > Connection Settings > Select connection > Manage

    Requirements:
        - The bot must exist and have at least one connector tool configured
        - The connection must exist and be in a "Connected" (authenticated) state
        - The connector ID must match the connector used by the tool
        - Appropriate Power Platform API permissions (see above)

    Examples:
        # Bind an Asana connection to an agent
        copilot connections bind abc123-bot-id \\
            --connector-id shared_asana \\
            --connection-id abcdef01-2345-6789-abcd-ef0123456789

        # Bind a custom connector connection
        copilot connections bind abc123-bot-id \\
            -c shared_asana-20tasks-20api-5fd251d00e-f825669a42b5e533 \\
            --connection-id abcdef01-2345-6789-abcd-ef0123456789

        # With explicit environment
        copilot connections bind abc123-bot-id -c shared_asana \\
            --connection-id conn-guid --env Default-tenant-id
    """
    try:
        client = get_client()

        # Get environment ID from config if not provided
        if not environment:
            config = get_config()
            environment = config.environment_id
            if not environment:
                typer.echo(
                    "Error: Environment ID not found. Please set DATAVERSE_ENVIRONMENT_ID "
                    "in your .env file or use --environment.",
                    err=True
                )
                raise typer.Exit(1)

        typer.echo(f"Binding connection to agent...")
        typer.echo(f"  Agent ID: {bot_id}")
        typer.echo(f"  Connector: {connector_id}")
        typer.echo(f"  Connection: {connection_id}")
        typer.echo("")

        result = client.bind_user_connection(
            bot_id=bot_id,
            connector_id=connector_id,
            connection_id=connection_id,
            environment_id=environment,
        )

        print_success("Connection bound to agent successfully!")
        typer.echo(f"Bot schema: {result.get('bot_schema', '')}")
        typer.echo(f"Binding key: {result.get('binding_key', '')}")
        typer.echo("")
        typer.echo("The agent can now use this connection for connector tool authentication.")
        typer.echo("Remember to publish the agent to make changes live: copilot agent publish <agent-id>")

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
