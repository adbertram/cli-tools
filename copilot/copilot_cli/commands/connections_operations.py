"""Operations subcommands for connections — list, get, and invoke connector operations."""
import json
import typer
from typing import Optional, List

from ..client import get_client, get_access_token, ClientError
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="List, inspect, and invoke connector operations via APIM")

COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "invoke": ["custom"],
}

# Module-level storage for connection ID passed from parent callback
_connection_id: str = ""


def set_connection_id(connection_id: str):
    """Set the connection ID from the parent command."""
    global _connection_id
    _connection_id = connection_id


def _resolve_connector(client, connection_id: str) -> dict:
    """Get the connection, extract connector ID, and fetch the connector with swagger."""
    connection = client.get_connection(connection_id)
    api_id = connection.get("properties", {}).get("apiId", "")
    if not api_id:
        raise ClientError(f"Connection '{connection_id}' has no apiId property")

    # Extract connector ID from the apiId path (last segment)
    connector_id = api_id.rsplit("/", 1)[-1]

    connector = client.get_connector(connector_id)
    return connector


def _extract_operations_from_swagger(swagger: dict) -> list:
    """Extract operations from a swagger definition with full parameter details."""
    operations = []
    paths = swagger.get("paths", {})

    for path, methods in paths.items():
        for method, details in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue

            op_id = details.get("operationId")
            if not op_id:
                continue

            # Extract parameters
            params = []
            for param in details.get("parameters", []):
                params.append({
                    "name": param.get("name", ""),
                    "in": param.get("in", ""),
                    "required": param.get("required", False),
                    "type": param.get("type", param.get("schema", {}).get("type", "")),
                    "description": param.get("x-ms-summary", param.get("description", "")),
                })

            operations.append({
                "id": op_id,
                "name": details.get("summary") or op_id,
                "method": method.upper(),
                "path": path,
                "description": details.get("description") or details.get("summary") or "",
                "visibility": details.get("x-ms-visibility", "normal"),
                "deprecated": details.get("deprecated", False),
                "parameters": params,
            })

    operations.sort(key=lambda x: x["id"].lower())
    return operations


@app.command("list")
def list_operations(
    connection_id: Optional[str] = typer.Option(
        None,
        "--connection-id",
        "-c",
        help="Connection ID. Usually supplied as: copilot connections <connection-id> operations list",
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of operations to return"),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results using field:op:value syntax",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    include_deprecated: bool = typer.Option(False, "--include-deprecated", help="Include deprecated operations"),
    include_internal: bool = typer.Option(False, "--include-internal", help="Include internal-visibility operations"),
):
    """
    List operations available on the connection's connector.

    Resolves the connection to its connector, then lists all available operations
    from the connector's OpenAPI/Swagger definition.

    Examples:
        copilot connections 12345678-1234-1234-1234-123456789abc operations list
        copilot connections 12345678-1234-1234-1234-123456789abc operations list --table
    """
    try:
        resolved_connection_id = connection_id or _connection_id
        if not resolved_connection_id:
            typer.echo("Error: connection ID is required.", err=True)
            raise typer.Exit(2)

        client = get_client()
        connector = _resolve_connector(client, resolved_connection_id)
        swagger = connector.get("properties", {}).get("swagger", {})

        if not swagger:
            raise ClientError("Connector has no OpenAPI/Swagger definition")

        operations = _extract_operations_from_swagger(swagger)

        # Filter
        if not include_deprecated:
            operations = [op for op in operations if not op["deprecated"]]
        if not include_internal:
            operations = [op for op in operations if op["visibility"] != "internal"]

        if filter:
            from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
            try:
                validate_filters(filter)
                operations = apply_filters(operations, filter)
            except FilterValidationError as e:
                from cli_tools_shared.output import print_error
                print_error(str(e))
                raise typer.Exit(1)

        operations = operations[:limit]

        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            operations = [
                {k: v for k, v in item.items() if k in property_list}
                for item in operations
            ]

        if table:
            props = connector.get("properties", {})
            typer.echo(f"\nConnector: {props.get('displayName', '?')}")
            typer.echo(f"Operations: {len(operations)}")

            display_ops = []
            for op in operations:
                req_params = [p["name"] for p in op["parameters"] if p["required"] and p["name"] != "connectionId"]
                display_ops.append({
                    "id": op["id"],
                    "name": op["name"][:40] + "..." if len(op["name"]) > 40 else op["name"],
                    "method": op["method"],
                    "required_params": ", ".join(req_params) if req_params else "-",
                })

            print_table(
                display_ops,
                columns=["id", "name", "method", "required_params"],
                headers=["Operation ID", "Name", "Method", "Required Params"],
            )
        else:
            # JSON output - strip full parameter details for cleaner listing
            output = []
            for op in operations:
                output.append({
                    "id": op["id"],
                    "name": op["name"],
                    "method": op["method"],
                    "path": op["path"],
                    "description": op["description"],
                    "parameters": [
                        {k: v for k, v in p.items() if k != "description"}
                        for p in op["parameters"]
                    ],
                })
            print_json(output)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def get_operation(
    operation_id: str = typer.Argument(..., help="Operation ID (e.g., ListAccountSummaries)"),
):
    """
    Show details for a specific operation including parameters.

    Examples:
        copilot connections dc84384a-... operations get ListAccountSummaries
    """
    try:
        client = get_client()
        connector = _resolve_connector(client, _connection_id)
        swagger = connector.get("properties", {}).get("swagger", {})

        if not swagger:
            raise ClientError("Connector has no OpenAPI/Swagger definition")

        operations = _extract_operations_from_swagger(swagger)
        op = next((o for o in operations if o["id"] == operation_id), None)

        if not op:
            available = [o["id"] for o in operations]
            raise ClientError(
                f"Operation '{operation_id}' not found. "
                f"Available operations: {', '.join(available[:10])}"
                + (f" (and {len(available) - 10} more)" if len(available) > 10 else "")
            )

        print_json(op)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("invoke")
def invoke_operation(
    operation_id: str = typer.Argument(..., help="Operation ID to invoke"),
    param: Optional[List[str]] = typer.Option(
        None, "--param", "-p",
        help="Parameter as key=value (repeatable). Values are classified as path/query/body based on swagger.",
    ),
):
    """
    Invoke a connector operation through the APIM gateway.

    Builds the APIM URL from the connector's swagger definition, classifies
    parameters based on the swagger spec, and makes the HTTP call with a
    Bearer token for https://apihub.azure.com.

    Examples:
        copilot connections dc84384a-... operations invoke ListAccountSummaries
        copilot connections dc84384a-... operations invoke GetReport -p reportId=12345
    """
    try:
        client = get_client()
        connector = _resolve_connector(client, _connection_id)
        swagger = connector.get("properties", {}).get("swagger", {})

        if not swagger:
            raise ClientError("Connector has no OpenAPI/Swagger definition")

        # Parse --param key=value pairs
        params = {}
        for p in (param or []):
            if "=" not in p:
                raise ClientError(f"Invalid parameter format: '{p}'. Expected key=value.")
            key, value = p.split("=", 1)
            params[key] = value

        # Use APIM runtime URL (routes through gateway with connection auth)
        # instead of raw swagger host (which hits backend directly without auth)
        runtime_urls = connector.get("properties", {}).get("runtimeUrls", [])
        runtime_url = runtime_urls[0] if runtime_urls else None

        result = client.invoke_connector_operation(
            swagger=swagger,
            connection_id=_connection_id,
            operation_id=operation_id,
            params=params,
            runtime_url=runtime_url,
        )
        print_json(result)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
