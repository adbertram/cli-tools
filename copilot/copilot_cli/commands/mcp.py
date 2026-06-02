"""MCP server commands for listing Model Context Protocol servers available as agent tools."""
import typer
import json as _json
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, handle_error


app = typer.Typer(help="Manage MCP (Model Context Protocol) servers")
tools_app = typer.Typer(help="Discover tools exposed by an MCP server")
app.add_typer(tools_app, name="tools")


# ---------------------------------------------------------------------------
# MCP protocol helpers
# ---------------------------------------------------------------------------



def _discover_mcp_auth(url: str) -> dict:
    """Discover OAuth requirements for an MCP server.

    Returns dict with keys: authorization_server, scopes, resource_metadata_url.
    Returns empty dict if server doesn't require auth.
    """
    import httpx

    # First try a lightweight request to see if auth is needed
    try:
        resp = httpx.post(
            url,
            json={"jsonrpc": "2.0", "method": "initialize", "id": 0,
                  "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                             "clientInfo": {"name": "copilot-cli", "version": "0.1.0"}}},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code != 401:
            return {}  # No auth required
    except httpx.ConnectError:
        raise typer.Exit(1)

    # Get resource metadata
    body = {}
    try:
        body = resp.json()
    except Exception:
        pass

    metadata_url = body.get("resource_metadata_url", "")
    if not metadata_url:
        # Try well-known path
        from urllib.parse import urlparse
        parsed = urlparse(url)
        metadata_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource"

    try:
        meta_resp = httpx.get(metadata_url, timeout=15)
        meta_resp.raise_for_status()
        meta = meta_resp.json()
    except Exception as e:
        return {"error": f"Failed to fetch resource metadata: {e}", "resource_metadata_url": metadata_url}

    auth_servers = meta.get("authorization_servers", [])
    scopes = meta.get("scopes_supported", [])
    if not scopes:
        scope_str = meta.get("scope", "")
        scopes = scope_str.split() if scope_str else []

    return {
        "authorization_server": auth_servers[0] if auth_servers else "",
        "scopes": scopes,
        "resource_metadata_url": metadata_url,
    }


def _acquire_mcp_token(authority: str, scopes: list[str], client_id: str = None) -> str:
    """Acquire a user token for an MCP server via device code flow.

    Args:
        authority: Azure AD authority URL
        scopes: List of OAuth scopes to request
        client_id: Explicit client ID. If not provided, uses AZURE_CLIENT_ID from
            the active profile.
    """
    import msal
    from ..config import get_config

    if not client_id:
        config = get_config()
        client_id = config.azure_client_id
        client_secret = config.azure_client_secret

    else:
        client_secret = None

    if not client_id:
        raise RuntimeError(
            "No AZURE_CLIENT_ID found. Provide --client-id or configure the active profile."
        )

    # Strip /v2.0 suffix — MSAL adds it internally
    clean_authority = authority.rstrip("/")
    if clean_authority.endswith("/v2.0"):
        clean_authority = clean_authority[:-5]

    # For confidential client apps (have client_secret), use client credentials
    # flow with .default scope. For public client apps, use device code flow.
    if client_secret:
        app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=clean_authority,
        )

        # Extract the resource URI from scopes for .default
        # e.g., api://5e418d02-.../mcp.tools -> api://5e418d02-.../.default
        resource = scopes[0].rsplit("/", 1)[0] if scopes else ""
        cc_scopes = [f"{resource}/.default"]

        result = app.acquire_token_for_client(scopes=cc_scopes)
        if "access_token" in result:
            return result["access_token"]

        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Token acquisition failed: {error}")
    else:
        app = msal.PublicClientApplication(
            client_id=client_id,
            authority=clean_authority,
        )

        # Try silent first (cached tokens)
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])
            if result and "access_token" in result:
                return result["access_token"]

        # Device code flow — user visits a URL and enters a code
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise RuntimeError(f"Device code flow failed: {flow.get('error_description', flow.get('error', 'Unknown'))}")

        typer.echo(flow["message"])
        result = app.acquire_token_by_device_flow(flow)

        if "access_token" in result:
            return result["access_token"]

        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Token acquisition failed: {error}")


class McpSession:
    """Manages a stateful MCP session with session ID tracking."""

    def __init__(self, url: str, token: str = None):
        self.url = url
        self.token = token
        self.session_id = None

    def request(self, method: str, params: dict = None, is_notification: bool = False) -> dict:
        """Send a JSON-RPC request to the MCP server."""
        import httpx

        payload = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if not is_notification:
            payload["id"] = 1
        if params:
            payload["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        resp = httpx.post(self.url, json=payload, headers=headers, timeout=30)

        if resp.status_code == 401:
            raise RuntimeError(
                "Authentication required. Run 'copilot tool mcp auth --url <url>' first."
            )
        resp.raise_for_status()

        # Capture session ID from response headers
        new_session_id = resp.headers.get("mcp-session-id")
        if new_session_id:
            self.session_id = new_session_id

        if is_notification:
            return {}

        content_type = resp.headers.get("content-type", "")

        # Direct JSON response
        if "application/json" in content_type:
            data = resp.json()
            if "error" in data:
                err = data["error"]
                raise RuntimeError(f"MCP error {err.get('code', '')}: {err.get('message', '')}")
            return data.get("result", data)

        # SSE / text/event-stream response — parse event data lines
        if "text/event-stream" in content_type:
            for line in resp.text.splitlines():
                if line.startswith("data: "):
                    try:
                        data = _json.loads(line[6:])
                        if "result" in data:
                            return data["result"]
                        if "error" in data:
                            err = data["error"]
                            raise RuntimeError(f"MCP error {err.get('code', '')}: {err.get('message', '')}")
                    except _json.JSONDecodeError:
                        continue
            raise RuntimeError("No valid JSON-RPC result in SSE response")

        # Fallback — try parsing as JSON
        try:
            data = resp.json()
            return data.get("result", data)
        except Exception:
            raise RuntimeError(f"Unexpected response content-type: {content_type}")

    def initialize(self) -> dict:
        """Initialize the MCP session and send initialized notification."""
        result = self.request("initialize", params={
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "copilot-cli", "version": "0.1.0"},
        })
        # Send initialized notification
        self.request("notifications/initialized", is_notification=True)
        return result


def _get_mcp_token_for_url(url: str) -> Optional[str]:
    """Get a cached/fresh token for an MCP server, or None if no auth needed."""
    auth_info = _discover_mcp_auth(url)
    if not auth_info or "error" in auth_info:
        return None
    if not auth_info.get("scopes"):
        return None

    try:
        return _acquire_mcp_token(auth_info["authorization_server"], auth_info["scopes"])
    except Exception:
        return None


def format_mcp_for_display(connector: dict, truncate: bool = False) -> dict:
    """Format an MCP server connector for display.

    Args:
        connector: The connector dict from the API
        truncate: If True, truncate long values for table display
    """
    name = connector.get("name", "")
    props = connector.get("properties", {})
    display_name = props.get("displayName", name)

    # Get description
    description = props.get("description") or ""
    if truncate and len(description) > 60:
        description = description[:57] + "..."

    # Get tier
    tier = props.get("tier", "")

    # Get publisher
    publisher = props.get("publisher", "")

    # Get release tag (Preview, GA, etc.)
    release_tag = props.get("releaseTag", "")

    # Get created/modified dates
    created = props.get("createdTime", "")
    if created:
        created = created.split("T")[0]

    modified = props.get("changedTime", "")
    if modified:
        modified = modified.split("T")[0]

    return {
        "name": display_name,
        "id": name,
        "publisher": publisher,
        "tier": tier,
        "release": release_tag,
        "description": description,
        "created": created,
        "modified": modified,
    }


@app.command("list")
def mcp_list(
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%microsoft%)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of MCP servers to return",
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
    List all MCP (Model Context Protocol) servers available for agents.

    MCP servers are connectors that implement the Model Context Protocol,
    allowing Copilot Studio agents to connect to external data sources and tools.
    They provide structured access to resources, tools, and prompts.

    Examples:
        copilot mcp list
        copilot mcp list --table
        copilot mcp list --filter "name:ilike:%microsoft%" --table
        copilot mcp list --limit 50
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
    from cli_tools_shared.output import print_error

    try:
        client = get_client()
        servers = client.list_mcp_servers()

        if not servers:
            print_json([])
            return

        # Apply filters using standard field:op:value syntax
        if filter:
            try:
                validate_filters(filter)
                servers = apply_filters(servers, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if not servers:
            print_json([])
            return

        # Apply limit
        servers = servers[:limit]

        use_table = table or output == "table"
        formatted = [format_mcp_for_display(s, truncate=use_table) for s in servers]

        # Sort by name
        formatted.sort(key=lambda x: x["name"].lower())

        # Apply properties filter
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            formatted = [{k: v for k, v in item.items() if k in property_list} for item in formatted]

        if use_table:
            if properties:
                property_list = [p.strip() for p in properties.split(",")]
                print_table(formatted, columns=property_list, headers=property_list)
            else:
                print_table(
                    formatted,
                    columns=["name", "publisher", "tier", "release", "description"],
                    headers=["Name", "Publisher", "Tier", "Release", "Description"],
                )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def format_mcp_record_for_display(record: dict, truncate: bool = False) -> dict:
    """Format a Dataverse mcpservers record for display.

    Args:
        record: The mcpserver record from Dataverse
        truncate: If True, truncate long values for table display
    """
    import json as _json

    mcp_id = record.get("mcpserverid", "")
    name = record.get("name", "")

    description = record.get("description") or ""
    if truncate and len(description) > 60:
        description = description[:57] + "..."

    instructions = record.get("instructions") or ""
    if truncate and len(instructions) > 60:
        instructions = instructions[:57] + "..."

    # Extract URL from configuration JSON
    url = ""
    config_str = record.get("configuration") or ""
    if config_str:
        try:
            config = _json.loads(config_str)
            url = config.get("url", "")
        except (_json.JSONDecodeError, TypeError):
            url = config_str

    is_remote = record.get("isremote", False)
    server_type = record.get("servertype", "")

    created = record.get("createdon", "")
    if created:
        created = created.split("T")[0]

    modified = record.get("modifiedon", "")
    if modified:
        modified = modified.split("T")[0]

    return {
        "id": mcp_id,
        "name": name,
        "url": url,
        "description": description,
        "instructions": instructions,
        "remote": is_remote,
        "type": server_type,
        "created": created,
        "modified": modified,
    }


@app.command("get")
def mcp_get(
    connector_id: str = typer.Argument(
        ...,
        help="The MCP server connector's unique identifier (e.g., shared_microsoftlearndocsmcpserver)",
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
    Get details for a specific MCP server.

    Examples:
        copilot mcp get shared_microsoftlearndocsmcpserver
        copilot mcp get shared_boxmcpserver
        copilot mcp get shared_boxmcpserver --table
    """
    try:
        client = get_client()
        connector = client.get_mcp_server(connector_id)

        use_table = table or output == "table"
        if use_table:
            formatted = format_mcp_for_display(connector, truncate=True)
            print_table(
                [formatted],
                columns=["name", "publisher", "tier", "release", "description"],
                headers=["Name", "Publisher", "Tier", "Release", "Description"],
            )
        else:
            formatted = format_mcp_for_display(connector, truncate=False)
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
def mcp_create(
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Display name for the MCP server",
    ),
    url: str = typer.Option(
        ...,
        "--url",
        "-u",
        help="The MCP server endpoint URL",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="Description of the MCP server",
    ),
    instructions: Optional[str] = typer.Option(
        None,
        "--instructions",
        help="Instructions for agents using this server",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        help="Scope value for the MCP server",
    ),
    audience: Optional[str] = typer.Option(
        None,
        "--audience",
        help="Audience value for the MCP server",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    Create a custom MCP server registration in Dataverse.

    Registers a remote MCP server endpoint so it can be used as a tool
    by Copilot Studio agents.

    Examples:
        copilot tool mcp create -n "My MCP Server" -u "https://example.com/mcp"

        copilot tool mcp create -n "My MCP Server" -u "https://example.com/mcp" -d "OData access"

        copilot tool mcp create -n "My Server" -u "https://example.com/mcp" --instructions "Use for data queries"
    """
    # Validate field lengths
    if len(name) > 200:
        typer.echo("Error: Name must be 200 characters or fewer.", err=True)
        raise typer.Exit(1)

    if len(url) > 2000:
        typer.echo("Error: URL must be 2000 characters or fewer.", err=True)
        raise typer.Exit(1)

    if description and len(description) > 2000:
        typer.echo("Error: Description must be 2000 characters or fewer.", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()

        typer.echo(f"Creating MCP server '{name}'...", err=True)

        result = client.create_mcp_server(
            name=name,
            url=url,
            description=description,
            instructions=instructions,
            scope=scope,
            audience=audience,
        )

        mcp_id = result.get("mcpserverid") or result.get("id", "")
        print_success(f"Created MCP server '{name}'")
        typer.echo(f"  ID: {mcp_id}", err=True)

        use_table = table
        if use_table:
            formatted = format_mcp_record_for_display(result, truncate=True)
            print_table(
                [formatted],
                columns=["id", "name", "url", "description", "created"],
                headers=["ID", "Name", "URL", "Description", "Created"],
            )
        else:
            formatted = format_mcp_record_for_display(result, truncate=False)
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("remove")
def mcp_remove(
    mcp_server_id: str = typer.Argument(
        ...,
        help="The MCP server's unique identifier (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt and delete immediately",
    ),
):
    """
    Remove a custom MCP server registration from Dataverse.

    Permanently deletes a custom MCP server registration. This action cannot be undone.

    Examples:
        copilot tool mcp remove 12345678-1234-1234-1234-123456789abc

        copilot tool mcp remove 12345678-1234-1234-1234-123456789abc --force
    """
    try:
        client = get_client()

        # Get record info for confirmation display
        try:
            record = client.get_mcp_server_record(mcp_server_id)
        except Exception:
            typer.echo(f"Error: MCP server {mcp_server_id} not found.", err=True)
            raise typer.Exit(1)

        server_name = record.get("name", mcp_server_id)

        # Confirm deletion unless --force
        if not force:
            formatted = format_mcp_record_for_display(record)
            typer.echo(f"Server: {formatted['name']}")
            typer.echo(f"ID: {formatted['id']}")
            typer.echo(f"URL: {formatted['url']}")
            typer.echo()
            typer.confirm(
                "Are you sure you want to delete this MCP server? This cannot be undone.",
                abort=True,
            )

        typer.echo(f"Deleting MCP server '{server_name}'...", err=True)
        client.delete_mcp_server(mcp_server_id)
        print_success(f"Deleted MCP server '{server_name}'")

    except typer.Abort:
        typer.echo("Aborted.")
        raise typer.Exit(0)
    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# ==========================================================================
# copilot tool mcp auth
# ==========================================================================


@app.command("auth")
def mcp_auth(
    url: str = typer.Option(
        ...,
        "--url",
        "-u",
        help="The MCP server endpoint URL",
    ),
    client_id: Optional[str] = typer.Option(
        None,
        "--client-id",
        help="Azure AD app client ID to authenticate with (defaults to AZURE_CLIENT_ID from config)",
    ),
):
    """
    Authenticate with an MCP server.

    Discovers OAuth requirements from the server, then prompts for device code
    sign-in and consent. After auth succeeds, other MCP commands (tools list,
    tools get) will work automatically.

    Examples:
        copilot tool mcp auth --url "https://mcp.example.com/sse"
    """
    try:
        typer.echo(f"Discovering auth requirements for {url}...", err=True)
        auth_info = _discover_mcp_auth(url)

        if not auth_info:
            print_success("No authentication required for this MCP server.")
            return

        if "error" in auth_info:
            typer.echo(f"Error: {auth_info['error']}", err=True)
            raise typer.Exit(1)

        scopes = auth_info.get("scopes", [])
        authority = auth_info.get("authorization_server", "")

        if not scopes or not authority:
            typer.echo("Error: Could not determine auth requirements.", err=True)
            raise typer.Exit(1)

        typer.echo(f"Authorization server: {authority}", err=True)
        typer.echo(f"Required scopes: {', '.join(scopes)}", err=True)
        typer.echo("Authenticating via device code flow...", err=True)

        token = _acquire_mcp_token(authority, scopes, client_id=client_id)

        # Verify token works by initializing a session
        typer.echo("Verifying authentication...", err=True)
        session = McpSession(url, token=token)
        result = session.initialize()

        server_name = result.get("serverInfo", {}).get("name", "Unknown")
        server_version = result.get("serverInfo", {}).get("version", "")
        print_success(f"Authenticated with MCP server: {server_name} {server_version}")

        capabilities = result.get("capabilities", {})
        if capabilities.get("tools"):
            typer.echo("  Supports: tools")
        if capabilities.get("resources"):
            typer.echo("  Supports: resources")
        if capabilities.get("prompts"):
            typer.echo("  Supports: prompts")

    except typer.Exit:
        raise
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# ==========================================================================
# copilot tool mcp tools list / get
# ==========================================================================


@tools_app.command("list")
def mcp_tools_list(
    url: str = typer.Option(
        ...,
        "--url",
        "-u",
        help="The MCP server endpoint URL",
    ),
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
        help="Maximum number of tools to return",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    List tools exposed by an MCP server.

    Connects to the MCP server, initializes a session, and retrieves the
    list of available tools with their names, descriptions, and input schemas.

    Requires authentication for servers that need it. Run 'copilot tool mcp auth'
    first if you get a 401 error.

    Examples:
        copilot tool mcp tools list --url "https://mcp.example.com/sse"
        copilot tool mcp tools list --url "https://mcp.example.com/sse" --table
        copilot tool mcp tools list --url "https://mcp.example.com/sse" --filter "name:ilike:%site%"
        copilot tool mcp tools list --url "https://mcp.example.com/sse" --properties "name,description"
    """
    from cli_tools_shared.filters import (
        FilterValidationError,
        apply_filters,
        get_nested_value,
        validate_filters,
    )
    from cli_tools_shared.output import print_error

    try:
        token = _get_mcp_token_for_url(url)

        # Initialize session and list tools
        typer.echo("Connecting to MCP server...", err=True)
        session = McpSession(url, token=token)
        session.initialize()

        result = session.request("tools/list")
        tools = result.get("tools", [])

        if not tools:
            typer.echo("No tools found on this MCP server.", err=True)
            print_json([])
            return

        formatted = [
            {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "inputSchema": tool.get("inputSchema", {}),
            }
            for tool in tools
        ]

        if filter:
            try:
                validate_filters(filter)
                formatted = apply_filters(formatted, filter)
            except FilterValidationError as exc:
                print_error(str(exc))
                raise typer.Exit(1)

        formatted = formatted[:limit]

        if properties:
            property_list = [field.strip() for field in properties.split(",") if field.strip()]
            formatted = [
                {field: get_nested_value(item, field) for field in property_list}
                for item in formatted
            ]
        else:
            property_list = []

        if table:
            if properties:
                print_table(formatted, columns=property_list, headers=property_list)
                return

            rows = []
            for tool in formatted:
                schema = tool.get("inputSchema", {}) if isinstance(tool, dict) else {}
                props = schema.get("properties", {})
                param_names = ", ".join(props.keys()) if props else ""
                required = schema.get("required", [])
                req_str = ", ".join(required) if required else ""

                desc = tool.get("description", "")
                if len(desc) > 80:
                    desc = desc[:77] + "..."

                rows.append({
                    "name": tool.get("name", ""),
                    "description": desc,
                    "parameters": param_names,
                    "required": req_str,
                })

            print_table(
                rows,
                columns=["name", "description", "parameters", "required"],
                headers=["Name", "Description", "Parameters", "Required"],
            )
        else:
            print_json(formatted)

    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@tools_app.command("invoke")
def mcp_tools_invoke(
    url: str = typer.Option(
        ...,
        "--url",
        "-u",
        help="The MCP server endpoint URL",
    ),
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Name of the tool to invoke",
    ),
    arguments: Optional[str] = typer.Option(
        None,
        "--arguments",
        "-a",
        help='Tool arguments as a JSON string (e.g., \'{"entitySet": "blogposts"}\')',
    ),
    arguments_file: Optional[str] = typer.Option(
        None,
        "--arguments-file",
        help="Path to a JSON file containing tool arguments",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        "-r",
        help="Output raw MCP response without formatting",
    ),
    persist_session: Optional[str] = typer.Option(
        None,
        "--persist-session",
        help="Path to a session file. Saves/restores the MCP session ID across invocations.",
    ),
):
    """
    Invoke a tool on an MCP server and display the result.

    Connects to the MCP server, initializes a session, and calls the
    specified tool with the provided arguments. Displays the tool's
    response content.

    Use --persist-session to maintain state across calls (e.g., select_site
    then query in separate invocations):

    Examples:
        copilot tool mcp tools invoke --url "https://example.com/mcp" --name "select_site" -a '{"url": "https://api.example.com"}' --persist-session /tmp/mcp.session

        copilot tool mcp tools invoke --url "https://example.com/mcp" --name "endpoint_metadata" --persist-session /tmp/mcp.session

        copilot tool mcp tools invoke --url "https://example.com/mcp" --name "read_entity" -a '{"entitySet": "customers"}' --persist-session /tmp/mcp.session
    """
    import json as json_mod
    from pathlib import Path

    try:
        # Parse arguments
        tool_args = {}
        if arguments_file:
            try:
                tool_args = json_mod.loads(Path(arguments_file).read_text())
            except FileNotFoundError:
                typer.echo(f"Error: File not found: {arguments_file}", err=True)
                raise typer.Exit(1)
            except json_mod.JSONDecodeError as e:
                typer.echo(f"Error: Invalid JSON in {arguments_file}: {e}", err=True)
                raise typer.Exit(1)
        elif arguments:
            try:
                tool_args = json_mod.loads(arguments)
            except json_mod.JSONDecodeError as e:
                typer.echo(f"Error: Invalid JSON arguments: {e}", err=True)
                raise typer.Exit(1)

        token = _get_mcp_token_for_url(url)

        # Restore session if persist file exists
        saved_session_id = None
        if persist_session:
            session_path = Path(persist_session)
            if session_path.exists():
                try:
                    session_data = json_mod.loads(session_path.read_text())
                    saved_session_id = session_data.get("session_id")
                except Exception:
                    pass

        typer.echo("Connecting to MCP server...", err=True)
        session = McpSession(url, token=token)

        if saved_session_id:
            # Reuse existing session — skip initialize
            session.session_id = saved_session_id
            typer.echo(f"Resuming session {saved_session_id[:12]}...", err=True)
        else:
            session.initialize()

        typer.echo(f"Invoking tool '{name}'...", err=True)
        result = session.request("tools/call", params={
            "name": name,
            "arguments": tool_args,
        })

        # Persist session for next invocation
        if persist_session and session.session_id:
            Path(persist_session).write_text(json_mod.dumps({
                "session_id": session.session_id,
                "url": url,
            }))

        if raw:
            print_json(result)
            return

        # MCP tools/call returns {"content": [...], "isError": bool}
        is_error = result.get("isError", False)
        content_items = result.get("content", [])

        if is_error:
            typer.echo("Tool returned an error:", err=True)

        for item in content_items:
            item_type = item.get("type", "text")
            if item_type == "text":
                text = item.get("text", "")
                # Try to pretty-print if it's JSON
                try:
                    parsed = json_mod.loads(text)
                    print_json(parsed)
                except (json_mod.JSONDecodeError, TypeError):
                    typer.echo(text)
            elif item_type == "resource":
                resource = item.get("resource", {})
                typer.echo(f"Resource: {resource.get('uri', '')}")
                typer.echo(resource.get("text", ""))
            else:
                print_json(item)

        if is_error:
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@tools_app.command("get")
def mcp_tools_get(
    url: str = typer.Option(
        ...,
        "--url",
        "-u",
        help="The MCP server endpoint URL",
    ),
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Name of the tool to get details for",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    Get details for a specific tool on an MCP server.

    Shows the tool's name, description, and full input schema including
    parameter types and descriptions.

    Examples:
        copilot tool mcp tools get --url "https://mcp.example.com/sse" --name "list_tables"
    """
    try:
        token = _get_mcp_token_for_url(url)

        # Initialize session and list tools
        typer.echo("Connecting to MCP server...", err=True)
        session = McpSession(url, token=token)
        session.initialize()

        result = session.request("tools/list")
        tools = result.get("tools", [])

        match = None
        for tool in tools:
            if tool.get("name", "").lower() == name.lower():
                match = tool
                break

        if not match:
            available = [t.get("name", "") for t in tools]
            typer.echo(f"Error: Tool '{name}' not found.", err=True)
            if available:
                typer.echo(f"Available tools: {', '.join(available)}", err=True)
            raise typer.Exit(1)

        if table:
            # Show tool info as key-value pairs
            schema = match.get("inputSchema", {})
            props = schema.get("properties", {})
            required = set(schema.get("required", []))

            typer.echo(f"Name: {match.get('name', '')}")
            typer.echo(f"Description: {match.get('description', '')}")
            typer.echo()

            if props:
                rows = []
                for pname, pschema in props.items():
                    rows.append({
                        "parameter": pname,
                        "type": pschema.get("type", ""),
                        "required": "yes" if pname in required else "",
                        "description": pschema.get("description", ""),
                    })

                typer.echo("Parameters:")
                print_table(
                    rows,
                    columns=["parameter", "type", "required", "description"],
                    headers=["Parameter", "Type", "Required", "Description"],
                )
            else:
                typer.echo("No parameters.")
        else:
            print_json({
                "name": match.get("name", ""),
                "description": match.get("description", ""),
                "inputSchema": match.get("inputSchema", {}),
            })

    except typer.Exit:
        raise
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
